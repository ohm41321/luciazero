"""Durable SQLite store for the Agent Bus (M1).

Design rules, each proven by ``agentd/tests``:

- One writer transaction per operation (``BEGIN IMMEDIATE``), so every state
  change and its audit event commit together or not at all.
- Claims are single-statement conditional updates; the row count decides the
  winner, never a read-then-write in Python.
- Replays carrying an idempotency key return the original entity and create
  nothing; the same key with a different request is a conflict.
- ``messages`` and ``events`` are immutable at the schema level (triggers), so
  no code path can rewrite history.
- ``crash_hook`` is a test seam: the crash suite kills the process at named
  points around ``COMMIT`` and proves the store is atomic across restarts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence

from .gitinfo import GitError, commit_exists, inspect_worktree, is_oid
from .migrations import LATEST_VERSION, MIGRATIONS
from .redact import DEFAULT as DEFAULT_REDACTOR
from .redact import NONCE_PATTERN, NONCE_PREFIX, Redactor, find_credential_url

MESSAGE_KINDS = ("task", "question", "finding", "decision", "artifact", "result")
ARTIFACT_KINDS = ("commit", "patch", "report", "log", "relay")
PATH_ARTIFACT_KINDS = ("patch", "report", "log", "relay")
PROVIDERS = ("codex", "claude", "other")
TASK_OUTCOMES = ("completed", "blocked")
# Operations that need a human approval nonce (ADR 0003). Fixed set: the
# store cannot be talked into a new category through any tool.
SENSITIVE_OPERATIONS = ("delete", "deploy", "production", "spend", "force_push", "public_contract", "scope_expansion")
APPROVAL_TTL_SECONDS = 900
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_PATH_LENGTH = 1024
MAX_ID_LENGTH = 128
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
DEFAULT_BUSY_TIMEOUT_MS = 5000

CrashHook = Callable[[str], None]


class StoreError(Exception):
    """Base class for store failures."""


class ValidationError(StoreError):
    """Input rejected before touching the database."""


class NotFound(StoreError):
    """The referenced entity does not exist."""


class ConflictError(StoreError):
    """A conditional transition lost: wrong state, wrong owner, or a lost claim."""


class IdempotencyConflict(StoreError):
    """The idempotency key was already used for a different request."""


class WorktreeMismatch(ConflictError):
    """The agent's recorded worktree no longer matches what is on disk."""


class ApprovalRefused(ConflictError):
    """No valid, unused approval for this task, operation, nonce, and holder."""


class UnsafeReference(ValidationError):
    """An artifact reference escapes the worktree, is a symlink, is too
    large, points into .git, or carries credentials."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _check_id(value: Any, what: str, redactor: Redactor = DEFAULT_REDACTOR) -> str:
    """Ids cannot be scrubbed without breaking them, so a secret-shaped id (an
    approval nonce or the daemon token as correlation_id, idempotency_key,
    agent_id, ...) is refused outright; the message never echoes the value.
    ``Store`` passes its own redactor so the check knows the daemon token."""
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValidationError(
            f"{what} must be 1-{MAX_ID_LENGTH} chars of [A-Za-z0-9._:@+-], got {value!r}"
        )
    if redactor.scan(value):
        raise ValidationError(f"{what} carries a secret-shaped value and is refused")
    return value


CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _check_text(value: Any, what: str, max_len: int) -> str:
    """Free text shown to humans: no C0/C1 control characters, so a peer
    cannot smuggle terminal escapes or forged lines into status output."""
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise ValidationError(f"{what} must be a non-empty string of at most {max_len} chars")
    if CONTROL_CHARS.search(value):
        raise ValidationError(f"{what} must not contain control characters")
    return value


def _check_enum(value: Any, allowed: Sequence[str], what: str) -> str:
    if value not in allowed:
        raise ValidationError(f"{what} must be one of {', '.join(allowed)}, got {value!r}")
    return str(value)


def _check_int(value: Any, lo: int, hi: int, what: str) -> int:
    # bool is an int subclass; True would silently become 1.
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValidationError(f"{what} must be an integer within {lo}..{hi}, got {value!r}")
    return value


def _check_json_object(value: Any, what: str) -> str:
    if not isinstance(value, dict):
        raise ValidationError(f"{what} must be a JSON object")
    try:
        # allow_nan=False: NaN/Infinity are not JSON and strict consumers reject them.
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{what} is not strict JSON: {exc}") from exc
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValidationError(f"{what} exceeds {MAX_PAYLOAD_BYTES} bytes; publish an artifact instead")
    return encoded


def _fingerprint(operation: str, **fields: Any) -> str:
    blob = json.dumps({"op": operation, **fields}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _row(cursor_row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if cursor_row is None:
        return None
    record = dict(cursor_row)
    for key in ("payload", "capabilities", "depends_on", "result"):
        if key in record and isinstance(record[key], str):
            try:
                record[key] = json.loads(record[key])
            except json.JSONDecodeError:
                pass
    for key in ("dirty", "requires_worktree"):
        if key in record and isinstance(record[key], int):
            record[key] = bool(record[key])
    return record


def _check_path_arg(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_PATH_LENGTH:
        raise ValidationError(f"path must be a non-empty string of at most {MAX_PATH_LENGTH} chars")
    if CONTROL_CHARS.search(value):
        raise ValidationError("path must not contain control characters")
    if not os.path.isabs(os.path.expanduser(value)):
        raise ValidationError("path must be absolute")
    return os.path.expanduser(value)


def _same_path(a: str, b: str) -> bool:
    """Inode comparison: catches ``.GIT`` on a case-insensitive filesystem
    and any other spelling that lands on the same directory."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _contained_file(toplevel: str, ref: str, expected_sha256: Optional[str], *, git_dirs: Sequence[str], redactor: Redactor) -> tuple[int, str]:
    """Resolve a worktree-relative artifact path and prove it stays inside
    the worktree: no absolute or ``..`` segments, no symlink at any component,
    no component that is (or spells, on any filesystem) a git metadata
    directory, a regular file under the size cap whose content carries no
    strict secret shape. Returns the size and sha256; a caller-supplied digest
    must match the file."""
    if os.path.isabs(ref) or ref.startswith("~"):
        raise UnsafeReference("artifact paths are relative to the bound worktree")
    parts = ref.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise UnsafeReference("artifact paths must not contain empty, '.' or '..' segments")
    if any(part.casefold() == ".git" for part in parts):
        raise UnsafeReference("artifact paths must not point into .git")
    current = toplevel
    for part in parts:
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise UnsafeReference(f"artifact path component {part!r} is a symlink")
        if any(_same_path(current, git_dir) for git_dir in git_dirs):
            raise UnsafeReference("artifact paths must not point into .git")
    real = os.path.realpath(current)
    if os.path.commonpath([real, toplevel]) != toplevel:
        raise UnsafeReference("artifact path escapes the bound worktree")
    if any(os.path.commonpath([real, git_dir]) == git_dir for git_dir in git_dirs):
        raise UnsafeReference("artifact paths must not point into .git")
    if not os.path.isfile(current):
        raise UnsafeReference("artifact path is not a regular file in the bound worktree")
    size = os.path.getsize(current)
    if size > MAX_ARTIFACT_BYTES:
        raise UnsafeReference(f"artifact is {size} bytes; the cap is {MAX_ARTIFACT_BYTES}")
    with open(current, "rb") as handle:
        data = handle.read(MAX_ARTIFACT_BYTES + 1)
    if len(data) > MAX_ARTIFACT_BYTES:  # grew between stat and read
        raise UnsafeReference(f"artifact exceeds the {MAX_ARTIFACT_BYTES} byte cap")
    actual = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and expected_sha256 != actual:
        raise ValidationError("sha256 does not match the file in the bound worktree")
    found = redactor.scan(data.decode("utf-8", errors="replace"))
    if found:
        raise UnsafeReference(f"artifact content carries a secret-shaped value ({', '.join(sorted(set(found)))}); scrub it before publishing")
    return len(data), actual


def _split_statements(sql: str) -> list[str]:
    """Split a migration script into complete statements. Trigger bodies
    contain semicolons, so rely on SQLite's own completeness check."""
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise StoreError("migration script ends with an incomplete statement")
    return statements


class Store:
    """One connection to the bus database. Not shared across threads; open one
    ``Store`` per thread or process."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        path: str,
        crash_hook: Optional[CrashHook] = None,
        redactor: Optional[Redactor] = None,
    ):
        self._conn = connection
        self.path = path
        self._crash_hook: CrashHook = crash_hook or (lambda point: None)
        self._redactor = redactor or Redactor()

    # ------------------------------------------------------------------ setup
    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        crash_hook: Optional[CrashHook] = None,
        redact_literals: Sequence[str] = (),
    ) -> "Store":
        """``redact_literals`` are exact secrets the caller knows (the daemon's
        own bearer token) that must never be stored or echoed."""
        _check_int(busy_timeout_ms, 1, 60_000, "busy_timeout_ms")
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
        cls._ensure_wal(conn)
        return cls(conn, str(path), crash_hook, Redactor(redact_literals))

    def redact(self, text: str) -> str:
        """Scrub a string with this store's redactor (patterns plus literals)."""
        return self._redactor.text(text)[0]

    @staticmethod
    def _ensure_wal(conn: sqlite3.Connection, attempts: int = 25) -> None:
        """Switch a fresh database to WAL. The first switch needs an exclusive
        lock that SQLite takes without consulting the busy handler, so two
        connections opening a brand-new file at once can race; retry briefly.
        An already-WAL database never needs the switch."""
        for attempt in range(attempts):
            if conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal":
                return
            try:
                mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or attempt == attempts - 1:
                    raise
                time.sleep(0.005 * (attempt + 1))
                continue
            if mode == "wal":
                return
        raise StoreError("could not switch the database to WAL journal mode")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def pragmas(self) -> dict[str, Any]:
        return {
            "journal_mode": self._conn.execute("PRAGMA journal_mode").fetchone()[0],
            "foreign_keys": self._conn.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout": self._conn.execute("PRAGMA busy_timeout").fetchone()[0],
            "user_version": self.schema_version(),
        }

    def schema_version(self) -> int:
        return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> int:
        """Apply pending migrations in order; repeatable and safe to call from
        several connections at once. Each version is decided and applied under
        the write lock, so a concurrent opener either applies it or finds it
        already applied; a failure rolls back and leaves the connection usable."""
        current = self.schema_version()
        if current > LATEST_VERSION:
            raise StoreError(f"database schema {current} is newer than this daemon ({LATEST_VERSION})")
        for version, sql in MIGRATIONS:
            if version <= current:
                continue
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                current = self.schema_version()  # re-read under the lock
                if version <= current:
                    self._conn.execute("COMMIT")
                    continue
                for statement in _split_statements(sql):
                    self._conn.execute(statement)
                self._conn.execute(f"PRAGMA user_version = {int(version)}")
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
            current = version
        return current

    # ----------------------------------------------------------- transactions
    @contextmanager
    def _tx(self, name: str) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._crash_hook(f"before_commit:{name}")
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:  # SQLite may already have rolled back (FULL/IOERR)
                self._conn.execute("ROLLBACK")
            raise
        self._crash_hook(f"after_commit:{name}")

    def _event(self, actor: str, kind: str, entity_type: str, entity_id: str, payload: Optional[dict[str, Any]] = None) -> None:
        scrubbed, _ = self._redactor.json(payload or {})
        self._conn.execute(
            "INSERT INTO events (at, actor, kind, entity_type, entity_id, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (utcnow(), actor, kind, entity_type, entity_id, json.dumps(scrubbed, sort_keys=True)),
        )

    def _payload(self, value: Any, what: str) -> tuple[str, int]:
        """Validate a free-form JSON object from a peer: credential-bearing
        URLs are refused outright, known secret shapes are scrubbed, and the
        result is size-capped. Returns the encoding and the redaction count."""
        if not isinstance(value, dict):
            raise ValidationError(f"{what} must be a JSON object")
        hit = find_credential_url(value)
        if hit is not None:
            raise UnsafeReference(f"{what} carries a credential-bearing URL; peers fetch repositories with their own credentials")
        scrubbed, count = self._redactor.json(value)
        return _check_json_object(scrubbed, what), count

    def _replay(self, actor: str, key: Optional[str], operation: str, fingerprint: str) -> Optional[str]:
        """Return the entity id ``actor`` recorded for ``key`` or ``None`` when
        unused. Keys are namespaced per actor so no agent can squat another's.
        Must be called inside the operation's transaction."""
        if key is None:
            return None
        row = self._conn.execute(
            "SELECT operation, fingerprint, entity_id FROM idempotency WHERE actor_agent_id = ? AND key = ?",
            (actor, key),
        ).fetchone()
        if row is None:
            return None
        if row["operation"] != operation or row["fingerprint"] != fingerprint:
            raise IdempotencyConflict(f"idempotency key {key!r} was already used by {actor!r} for a different request")
        return str(row["entity_id"])

    def _remember(self, actor: str, key: Optional[str], operation: str, fingerprint: str, entity_type: str, entity_id: str) -> None:
        if key is None:
            return
        self._conn.execute(
            "INSERT INTO idempotency (actor_agent_id, key, operation, fingerprint, entity_type, entity_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (actor, key, operation, fingerprint, entity_type, entity_id, utcnow()),
        )

    def _require_agent(self, agent_id: str) -> None:
        if self._conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone() is None:
            raise NotFound(f"agent {agent_id!r} is not registered")

    # ----------------------------------------------------------------- agents
    def register_agent(
        self,
        agent_id: str,
        *,
        provider: str,
        role: str,
        capabilities: Optional[Sequence[str]] = None,
        ttl_seconds: int = 300,
        by: Optional[str] = None,
    ) -> dict[str, Any]:
        """Upsert a stable agent identity. ``capabilities=None`` keeps what is
        recorded (empty for a new row). ``by`` names a human actor for the
        roster command; the audit event then reads ``agent.rostered`` under
        that actor instead of the agent registering itself."""
        _check_id(agent_id, "agent id", self._redactor)
        _check_enum(provider, PROVIDERS, "provider")
        role = self.redact(_check_text(role, "role", MAX_ID_LENGTH))
        _check_int(ttl_seconds, 1, 86_400, "ttl_seconds")
        if isinstance(capabilities, (str, bytes)):
            raise ValidationError("capabilities must be a sequence of non-empty strings")
        caps: Optional[str] = None
        if capabilities is not None:
            cleaned = [self.redact(_check_text(capability, "capability", 64)) for capability in capabilities]
            caps = json.dumps(sorted(set(cleaned)))
        actor = self.redact(_check_text(by, "by", 128)) if by is not None else agent_id
        now = utcnow()
        with self._tx("register_agent"):
            self._conn.execute(
                """INSERT INTO agents (id, provider, role, capabilities, status, ttl_seconds, last_seen_at, created_at)
                   VALUES (?, ?, ?, COALESCE(?, '[]'), 'active', ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET provider = excluded.provider, role = excluded.role,
                       capabilities = COALESCE(?, capabilities), status = 'active',
                       ttl_seconds = excluded.ttl_seconds, last_seen_at = excluded.last_seen_at""",
                (agent_id, provider, role, caps, ttl_seconds, now, now, caps),
            )
            self._event(actor, "agent.rostered" if by is not None else "agent.registered", "agent", agent_id, {"provider": provider, "role": role})
        return self.get_agent(agent_id)

    def heartbeat(self, agent_id: str) -> dict[str, Any]:
        _check_id(agent_id, "agent id", self._redactor)
        with self._tx("heartbeat"):
            cur = self._conn.execute("UPDATE agents SET last_seen_at = ? WHERE id = ?", (utcnow(), agent_id))
            if cur.rowcount != 1:
                raise NotFound(f"agent {agent_id!r} is not registered")
        return self.get_agent(agent_id)

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone())
        if record is None:
            raise NotFound(f"agent {agent_id!r} is not registered")
        return record

    def list_agents(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM agents ORDER BY id").fetchall()
        return [r for r in (_row(x) for x in rows) if r is not None]

    # --------------------------------------------------------------- messages
    def send_message(
        self,
        *,
        sender: str,
        recipient: str,
        kind: str,
        payload: dict[str, Any],
        correlation_id: Optional[str] = None,
        reply_to: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        hop_count: int = 0,
    ) -> dict[str, Any]:
        """Persist one immutable message and its queued delivery together."""
        _check_id(sender, "sender", self._redactor)
        _check_id(recipient, "recipient", self._redactor)
        _check_enum(kind, MESSAGE_KINDS, "kind")
        encoded, redactions = self._payload(payload, "payload")
        if idempotency_key is not None:
            _check_id(idempotency_key, "idempotency key", self._redactor)
        if reply_to is not None:
            _check_id(reply_to, "reply_to", self._redactor)
        if correlation_id is not None:
            _check_id(correlation_id, "correlation id", self._redactor)
        _check_int(hop_count, 0, 1_000, "hop_count")
        fingerprint = _fingerprint(
            "send_message", sender=sender, recipient=recipient, kind=kind,
            payload=encoded, correlation_id=correlation_id, reply_to=reply_to, hop_count=hop_count,
        )
        with self._tx("send_message"):
            existing = self._replay(sender, idempotency_key, "send_message", fingerprint)
            if existing is not None:
                message_id = existing
            else:
                self._require_agent(sender)
                self._require_agent(recipient)
                if reply_to is not None and self._conn.execute("SELECT 1 FROM messages WHERE id = ?", (reply_to,)).fetchone() is None:
                    raise NotFound(f"reply_to message {reply_to!r} does not exist")
                message_id = new_id("msg")
                delivery_id = new_id("dlv")
                now = utcnow()
                self._conn.execute(
                    """INSERT INTO messages (id, sender_agent_id, recipient_agent_id, kind, payload,
                                             correlation_id, reply_to, hop_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (message_id, sender, recipient, kind, encoded, correlation_id or message_id, reply_to, hop_count, now),
                )
                self._conn.execute(
                    "INSERT INTO deliveries (id, message_id, recipient_agent_id, state, updated_at) VALUES (?, ?, ?, 'queued', ?)",
                    (delivery_id, message_id, recipient, now),
                )
                self._event(sender, "message.sent", "message", message_id, {"recipient": recipient, "kind": kind, "delivery_id": delivery_id, "redactions": redactions})
                self._remember(sender, idempotency_key, "send_message", fingerprint, "message", message_id)
        return self.get_message(message_id)

    def get_message(self, message_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())
        if record is None:
            raise NotFound(f"message {message_id!r} does not exist")
        return record

    def inbox(
        self,
        agent_id: str,
        *,
        states: Sequence[str] = ("queued",),
        limit: int = 50,
        after: int = 0,
    ) -> dict[str, Any]:
        """Deliveries for ``agent_id`` in stable ``seq`` order with cursor
        pagination: pass the returned ``next_after`` back as ``after``."""
        _check_id(agent_id, "agent id", self._redactor)
        _check_int(limit, 1, 500, "limit")
        _check_int(after, 0, 2**62, "after")
        for state in states:
            _check_enum(state, ("queued", "claimed", "dispatched", "processing", "acknowledged", "completed", "retryable_failed", "dead_letter"), "state")
        placeholders = ",".join("?" for _ in states)
        rows = self._conn.execute(
            f"""SELECT d.seq AS delivery_seq, d.id AS delivery_id, d.state AS delivery_state,
                       d.acknowledged_at, d.completed_at,
                       m.id AS message_id, m.sender_agent_id AS sender, m.kind, m.payload,
                       m.correlation_id, m.reply_to, m.hop_count, m.created_at
                FROM deliveries d JOIN messages m ON m.id = d.message_id
                WHERE d.recipient_agent_id = ? AND d.state IN ({placeholders}) AND d.seq > ?
                ORDER BY d.seq LIMIT ?""",
            (agent_id, *states, after, limit + 1),
        ).fetchall()
        items = [r for r in (_row(x) for x in rows[:limit]) if r is not None]
        return {
            "items": items,
            "next_after": items[-1]["delivery_seq"] if items else after,
            "has_more": len(rows) > limit,
        }

    def _transition_delivery(self, delivery_id: str, agent_id: str, *, from_state: str, to_state: str, stamp: str, event: str) -> dict[str, Any]:
        _check_id(delivery_id, "delivery id", self._redactor)
        _check_id(agent_id, "agent id", self._redactor)
        with self._tx(f"delivery_{to_state}"):
            row = self._conn.execute("SELECT state, recipient_agent_id FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
            if row is None:
                raise NotFound(f"delivery {delivery_id!r} does not exist")
            now = utcnow()
            cur = self._conn.execute(
                f"""UPDATE deliveries SET state = ?, {stamp} = ?, acknowledged_by = COALESCE(acknowledged_by, ?), updated_at = ?
                    WHERE id = ? AND state = ? AND recipient_agent_id = ?""",
                (to_state, now, agent_id, now, delivery_id, from_state, agent_id),
            )
            if cur.rowcount != 1:
                raise ConflictError(
                    f"delivery {delivery_id!r} is {row['state']} for {row['recipient_agent_id']!r}; "
                    f"{agent_id!r} cannot move it from {from_state} to {to_state}"
                )
            self._event(agent_id, event, "delivery", delivery_id, {"from": from_state, "to": to_state})
        return self.get_delivery(delivery_id)

    def ack_delivery(self, delivery_id: str, agent_id: str) -> dict[str, Any]:
        """queued -> acknowledged: the recipient has read the message."""
        return self._transition_delivery(delivery_id, agent_id, from_state="queued", to_state="acknowledged", stamp="acknowledged_at", event="delivery.acknowledged")

    def complete_delivery(self, delivery_id: str, agent_id: str) -> dict[str, Any]:
        """acknowledged -> completed: the recipient has finished handling it."""
        return self._transition_delivery(delivery_id, agent_id, from_state="acknowledged", to_state="completed", stamp="completed_at", event="delivery.completed")

    def get_delivery(self, delivery_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone())
        if record is None:
            raise NotFound(f"delivery {delivery_id!r} does not exist")
        return record

    # ------------------------------------------------------------------ tasks
    def create_task(
        self,
        *,
        title: str,
        created_by: str,
        payload: Optional[dict[str, Any]] = None,
        assigned_to: Optional[str] = None,
        priority: int = 0,
        idempotency_key: Optional[str] = None,
        requires_worktree: bool = False,
    ) -> dict[str, Any]:
        _check_id(created_by, "created_by", self._redactor)
        if assigned_to is not None:
            _check_id(assigned_to, "assigned_to", self._redactor)
        title = self.redact(_check_text(title, "title", 500))
        _check_int(priority, -100, 100, "priority")
        if not isinstance(requires_worktree, bool):
            raise ValidationError("requires_worktree must be a boolean")
        encoded, redactions = self._payload(payload or {}, "payload")
        if idempotency_key is not None:
            _check_id(idempotency_key, "idempotency key", self._redactor)
        fingerprint = _fingerprint("create_task", title=title, created_by=created_by, payload=encoded, assigned_to=assigned_to, priority=priority, requires_worktree=requires_worktree)
        with self._tx("create_task"):
            existing = self._replay(created_by, idempotency_key, "create_task", fingerprint)
            if existing is not None:
                task_id = existing
            else:
                self._require_agent(created_by)
                if assigned_to is not None:
                    self._require_agent(assigned_to)
                task_id = new_id("tsk")
                now = utcnow()
                self._conn.execute(
                    """INSERT INTO tasks (id, title, payload, created_by_agent_id, assigned_agent_id, priority, state, requires_worktree, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
                    (task_id, title, encoded, created_by, assigned_to, priority, int(requires_worktree), now, now),
                )
                self._event(created_by, "task.created", "task", task_id, {"title": title, "assigned_to": assigned_to, "requires_worktree": requires_worktree, "redactions": redactions})
                self._remember(created_by, idempotency_key, "create_task", fingerprint, "task", task_id)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
        if record is None:
            raise NotFound(f"task {task_id!r} does not exist")
        return record

    def list_tasks(
        self,
        *,
        state: Optional[str] = None,
        assigned_to: Optional[str] = None,
        limit: int = 50,
        after: int = 0,
    ) -> dict[str, Any]:
        _check_int(limit, 1, 500, "limit")
        _check_int(after, 0, 2**62, "after")
        clauses = ["seq > ?"]
        params: list[Any] = [after]
        if state is not None:
            clauses.append("state = ?")
            params.append(_check_enum(state, ("open", "claimed", "completed", "blocked", "cancelled"), "state"))
        if assigned_to is not None:
            clauses.append("assigned_agent_id = ?")
            params.append(_check_id(assigned_to, "assigned_to", self._redactor))
        rows = self._conn.execute(
            f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY seq LIMIT ?", (*params, limit + 1)
        ).fetchall()
        items = [r for r in (_row(x) for x in rows[:limit]) if r is not None]
        return {"items": items, "next_after": items[-1]["seq"] if items else after, "has_more": len(rows) > limit}

    def claim_task(self, task_id: str, agent_id: str) -> dict[str, Any]:
        """open -> claimed. Exactly one concurrent claimer wins; the others
        get ``ConflictError``. Pre-assigned tasks accept only their assignee.
        A task that requires a worktree needs one bound and still matching;
        any bound worktree is re-verified against disk first (M3)."""
        _check_id(task_id, "task id", self._redactor)
        _check_id(agent_id, "agent id", self._redactor)
        pre = self._conn.execute("SELECT requires_worktree FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if pre is None:
            raise NotFound(f"task {task_id!r} does not exist")
        info = self._check_worktree(agent_id, required=bool(pre["requires_worktree"]), action="task_claim")
        with self._tx("claim_task"):
            row = self._conn.execute("SELECT state, assigned_agent_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise NotFound(f"task {task_id!r} does not exist")
            self._require_agent(agent_id)
            now = utcnow()
            cur = self._conn.execute(
                """UPDATE tasks SET state = 'claimed', assigned_agent_id = ?, version = version + 1, claimed_at = ?, updated_at = ?
                   WHERE id = ? AND state = 'open' AND (assigned_agent_id IS NULL OR assigned_agent_id = ?)""",
                (agent_id, now, now, task_id, agent_id),
            )
            if cur.rowcount != 1:
                raise ConflictError(
                    f"task {task_id!r} is {row['state']}"
                    + (f" and assigned to {row['assigned_agent_id']!r}" if row["assigned_agent_id"] else "")
                    + f"; {agent_id!r} did not claim it"
                )
            self._refresh_worktree(agent_id, info)
            self._event(agent_id, "task.claimed", "task", task_id, {"worktree": info["path"] if info else None})
        return self.get_task(task_id)

    def complete_task(self, task_id: str, agent_id: str, *, result: Optional[dict[str, Any]] = None, outcome: str = "completed") -> dict[str, Any]:
        """claimed -> completed | blocked, only by the agent holding the claim."""
        _check_id(task_id, "task id", self._redactor)
        _check_id(agent_id, "agent id", self._redactor)
        _check_enum(outcome, TASK_OUTCOMES, "outcome")
        encoded, _ = self._payload(result or {}, "result")
        with self._tx("complete_task"):
            row = self._conn.execute("SELECT state, assigned_agent_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise NotFound(f"task {task_id!r} does not exist")
            now = utcnow()
            cur = self._conn.execute(
                """UPDATE tasks SET state = ?, result = ?, version = version + 1, completed_at = ?, updated_at = ?
                   WHERE id = ? AND state = 'claimed' AND assigned_agent_id = ?""",
                (outcome, encoded, now, now, task_id, agent_id),
            )
            if cur.rowcount != 1:
                raise ConflictError(
                    f"task {task_id!r} is {row['state']} held by {row['assigned_agent_id']!r}; {agent_id!r} cannot complete it"
                )
            self._event(agent_id, f"task.{outcome}", "task", task_id, {})
        return self.get_task(task_id)

    def cancel_task(self, task_id: str, by: str, *, reason: Optional[str] = None) -> dict[str, Any]:
        """open | claimed -> cancelled, from the human channel (the CLI, never
        an MCP tool). The claim holder's next ``task_complete`` fails with a
        conflict, so a worker learns on its next turn; the record keeps who
        cancelled and why."""
        _check_id(task_id, "task id", self._redactor)
        by = self.redact(_check_text(by, "by", 128))
        note = self.redact(_check_text(reason, "reason", 500)) if reason is not None else None
        with self._tx("cancel_task"):
            row = self._conn.execute("SELECT state, assigned_agent_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise NotFound(f"task {task_id!r} does not exist")
            now = utcnow()
            cur = self._conn.execute(
                """UPDATE tasks SET state = 'cancelled', result = ?, version = version + 1, completed_at = ?, updated_at = ?
                   WHERE id = ? AND state IN ('open', 'claimed')""",
                (json.dumps({"cancelled_by": by, "reason": note}, sort_keys=True), now, now, task_id),
            )
            if cur.rowcount != 1:
                raise ConflictError(f"task {task_id!r} is {row['state']}; only open or claimed tasks can be cancelled")
            # Queued task messages for this task are dead work now: dead-letter
            # them so `bus status` stops asking for a turn nobody should start.
            # Acknowledged ones stay with their reader to complete.
            queued = self._conn.execute(
                """SELECT d.id, m.payload FROM deliveries d JOIN messages m ON m.id = d.message_id
                   WHERE d.state = 'queued' AND m.kind = 'task'"""
            ).fetchall()
            dead = []
            for delivery in queued:
                try:
                    payload = json.loads(delivery["payload"])
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict) and payload.get("task_id") == task_id:
                    self._conn.execute("UPDATE deliveries SET state = 'dead_letter', updated_at = ? WHERE id = ? AND state = 'queued'", (now, delivery["id"]))
                    self._event(by, "delivery.dead_letter", "delivery", delivery["id"], {"task_id": task_id, "reason": "task cancelled"})
                    dead.append(delivery["id"])
            self._event(by, "task.cancelled", "task", task_id, {"was": row["state"], "holder": row["assigned_agent_id"], "reason": note, "dead_lettered": dead})
        return self.get_task(task_id)

    # -------------------------------------------------------------- artifacts
    def publish_artifact(
        self,
        *,
        kind: str,
        ref: str,
        produced_by: str,
        task_id: Optional[str] = None,
        sha256: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record an artifact produced in the caller's bound worktree (M3):
        ``commit`` refs must be full object ids present in that worktree;
        every other kind is a worktree-relative path that must resolve to a
        regular, non-symlinked file inside it under the size cap. The stored
        sha256 is computed by the daemon; a supplied one must match."""
        _check_enum(kind, ARTIFACT_KINDS, "artifact kind")
        _check_id(produced_by, "produced_by", self._redactor)
        _check_text(ref, "ref", 2048)
        if sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValidationError("sha256 must be 64 lowercase hex chars")
        if task_id is not None:
            _check_id(task_id, "task id", self._redactor)
        if idempotency_key is not None:
            _check_id(idempotency_key, "idempotency key", self._redactor)
        if "://" in ref:
            raise UnsafeReference("artifact refs are commit ids or worktree-relative paths, never URLs")
        leaked = self._redactor.scan(ref)
        if leaked:
            # A ref cannot be scrubbed without breaking it, so it is refused;
            # the message names the shape, never the value.
            raise UnsafeReference(f"artifact ref carries a secret-shaped value ({', '.join(sorted(set(leaked)))}); rename it before publishing")
        info = self._check_worktree(produced_by, required=True, action="artifact_publish")
        assert info is not None
        if kind == "commit":
            if not is_oid(ref):
                raise UnsafeReference("commit refs must be a full 40- or 64-hex object id")
            if sha256 is not None:
                raise ValidationError("commit refs carry no sha256; the object id is the digest")
            if not commit_exists(info["path"], ref):
                raise ConflictError(f"commit {ref} is not in the bound worktree {info['path']}")
            size, digest = None, None
        else:
            size, digest = _contained_file(info["path"], ref, sha256, git_dirs=info["git_dirs"], redactor=self._redactor)
        fingerprint = _fingerprint("publish_artifact", kind=kind, ref=ref, produced_by=produced_by, task_id=task_id, sha256=sha256)
        with self._tx("publish_artifact"):
            existing = self._replay(produced_by, idempotency_key, "publish_artifact", fingerprint)
            if existing is not None:
                artifact_id = existing
            else:
                self._require_agent(produced_by)
                if task_id is not None and self._conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
                    raise NotFound(f"task {task_id!r} does not exist")
                artifact_id = new_id("art")
                self._conn.execute(
                    "INSERT INTO artifacts (id, task_id, kind, ref, sha256, produced_by_agent_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (artifact_id, task_id, kind, ref, digest, produced_by, utcnow()),
                )
                self._refresh_worktree(produced_by, info)
                self._event(produced_by, "artifact.published", "artifact", artifact_id, {"kind": kind, "task_id": task_id, "worktree": info["path"], "bytes": size})
                self._remember(produced_by, idempotency_key, "publish_artifact", fingerprint, "artifact", artifact_id)
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone())
        if record is None:
            raise NotFound(f"artifact {artifact_id!r} does not exist")
        return record

    # -------------------------------------------------------------- worktrees
    def bind_worktree(self, agent_id: str, path: str, *, base: Optional[str] = None) -> dict[str, Any]:
        """Record the one worktree ``agent_id`` writes in. The daemon reads
        the identity from disk itself; a toplevel another agent holds is
        refused, so concurrent writers never share a worktree. Rebinding
        replaces the agent's previous record."""
        _check_id(agent_id, "agent id", self._redactor)
        path = _check_path_arg(path)
        if self._redactor.scan(path):
            raise ValidationError("worktree path carries a secret-shaped value; it would be stored and shown as is")
        if base is not None:
            _check_text(base, "base", 256)
            if base.startswith("-"):
                raise ValidationError("base must be a ref name or commit id")
        try:
            info = inspect_worktree(path, base)
        except GitError as exc:
            raise ValidationError(f"not a usable git worktree: {exc}") from exc
        now = utcnow()
        with self._tx("bind_worktree"):
            self._require_agent(agent_id)
            other = self._conn.execute("SELECT agent_id FROM worktrees WHERE path = ? AND agent_id != ?", (info["path"], agent_id)).fetchone()
            if other is not None:
                raise ConflictError(f"worktree {info['path']} is owned by {other['agent_id']!r}; concurrent writers never share a worktree")
            previous = self._conn.execute("SELECT path, repo_id FROM worktrees WHERE agent_id = ?", (agent_id,)).fetchone()
            if previous is not None and (previous["path"] != info["path"] or previous["repo_id"] != info["repo_id"]):
                # Moving elsewhere while holding worktree-bound work would let a
                # stale worker finish a task against the wrong checkout.
                held = int(self._conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE assigned_agent_id = ? AND state = 'claimed' AND requires_worktree = 1", (agent_id,)
                ).fetchone()[0])
                if held:
                    raise ConflictError(
                        f"{agent_id!r} holds {held} claimed worktree task(s) in {previous['path']}; complete or block them before binding another worktree"
                    )
            self._conn.execute(
                """INSERT INTO worktrees (id, agent_id, repo_id, path, branch, base_oid, head_oid, dirty, recorded_at, verified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id) DO UPDATE SET repo_id = excluded.repo_id, path = excluded.path, branch = excluded.branch,
                       base_oid = excluded.base_oid, head_oid = excluded.head_oid, dirty = excluded.dirty,
                       recorded_at = excluded.recorded_at, verified_at = excluded.verified_at""",
                (new_id("wt"), agent_id, info["repo_id"], info["path"], info["branch"], info["base_oid"], info["head_oid"], int(info["dirty"]), now, now),
            )
            self._event(agent_id, "worktree.bound", "worktree", agent_id, {"path": info["path"], "branch": info["branch"], "head_oid": info["head_oid"], "base_oid": info["base_oid"], "dirty": info["dirty"], "previous_path": previous["path"] if previous else None})
        return self.get_worktree(agent_id)

    def get_worktree(self, agent_id: str) -> dict[str, Any]:
        _check_id(agent_id, "agent id", self._redactor)
        record = _row(self._conn.execute("SELECT * FROM worktrees WHERE agent_id = ?", (agent_id,)).fetchone())
        if record is None:
            raise NotFound(f"agent {agent_id!r} has no bound worktree")
        return record

    def _check_worktree(self, agent_id: str, *, required: bool, action: str) -> Optional[dict[str, Any]]:
        """Re-read the agent's bound worktree from disk and compare it with
        the record. Runs before the operation's transaction so a slow ``git``
        never holds the write lock. A mismatch is recorded as an event and
        raised; ``required`` turns a missing record into a refusal too."""
        record = _row(self._conn.execute("SELECT * FROM worktrees WHERE agent_id = ?", (agent_id,)).fetchone())
        if record is None:
            if required:
                raise ConflictError(f"{action} needs a bound worktree; call worktree_bind first")
            return None
        problem: Optional[str]
        try:
            info = inspect_worktree(record["path"])
        except GitError as exc:
            info, problem = None, f"recorded worktree is unusable: {exc}"
        else:
            problems = []
            if info["path"] != record["path"]:
                problems.append(f"toplevel is now {info['path']}")
            if info["repo_id"] != record["repo_id"]:
                problems.append("repository identity changed")
            if info["branch"] != record["branch"]:
                problems.append(f"branch is now {info['branch']!r}, recorded {record['branch']!r}")
            problem = "; ".join(problems) or None
        if problem is not None:
            with self._tx("worktree_mismatch"):
                self._event(agent_id, "worktree.mismatch", "worktree", agent_id, {"action": action, "path": record["path"], "problem": problem})
            raise WorktreeMismatch(f"{action} refused for {agent_id!r}: worktree {record['path']} no longer matches its record ({problem})")
        return info

    def _refresh_worktree(self, agent_id: str, info: Optional[dict[str, Any]]) -> None:
        """Inside a transaction: store the HEAD and dirty state just verified."""
        if info is None:
            return
        self._conn.execute(
            "UPDATE worktrees SET head_oid = ?, dirty = ?, verified_at = ? WHERE agent_id = ?",
            (info["head_oid"], int(info["dirty"]), utcnow(), agent_id),
        )

    # -------------------------------------------------------------- approvals
    def grant_approval(self, task_id: str, operation: str, *, granted_by: str, ttl_seconds: int = APPROVAL_TTL_SECONDS) -> tuple[dict[str, Any], str]:
        """Human channel only (never an MCP tool): mint one single-use nonce
        bound to one task and one operation. Only the hash is stored; the
        plain nonce is returned once for the approver's terminal."""
        _check_id(task_id, "task id", self._redactor)
        _check_enum(operation, SENSITIVE_OPERATIONS, "operation")
        _check_text(granted_by, "granted_by", 128)
        _check_int(ttl_seconds, 1, 86_400, "ttl_seconds")
        nonce = NONCE_PREFIX + secrets.token_hex(16)
        digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        approval_id = new_id("apv")
        with self._tx("grant_approval"):
            task = self._conn.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise NotFound(f"task {task_id!r} does not exist")
            if task["state"] not in ("open", "claimed"):
                raise ConflictError(f"task {task_id!r} is {task['state']}; approvals attach to open or claimed tasks")
            now = datetime.now(timezone.utc)
            expires = (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="microseconds")
            self._conn.execute(
                "INSERT INTO approvals (id, task_id, operation, nonce_hash, granted_by, granted_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (approval_id, task_id, operation, digest, granted_by, now.isoformat(timespec="microseconds"), expires),
            )
            self._event(granted_by, "approval.granted", "approval", approval_id, {"task_id": task_id, "operation": operation, "expires_at": expires})
        return self.get_approval(approval_id), nonce

    def consume_approval(self, task_id: str, operation: str, nonce: str, agent_id: str) -> dict[str, Any]:
        """Spend an approval: the caller must hold the task claim, and the
        nonce must be unused, unexpired, and bound to exactly this task and
        operation. One conditional update decides; a refusal is recorded as
        an event (without the nonce) and raised."""
        _check_id(task_id, "task id", self._redactor)
        _check_enum(operation, SENSITIVE_OPERATIONS, "operation")
        _check_id(agent_id, "agent id", self._redactor)
        if not isinstance(nonce, str) or not NONCE_PATTERN.fullmatch(nonce):
            raise ValidationError("nonce has the wrong shape")  # never echo the value
        digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        approval_id: Optional[str] = None
        reason: Optional[str] = None
        with self._tx("consume_approval"):
            task = self._conn.execute("SELECT state, assigned_agent_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise NotFound(f"task {task_id!r} does not exist")
            self._require_agent(agent_id)
            if task["state"] != "claimed" or task["assigned_agent_id"] != agent_id:
                reason = "caller does not hold the task claim"
            else:
                now = utcnow()
                cur = self._conn.execute(
                    """UPDATE approvals SET consumed_by = ?, consumed_at = ?
                       WHERE nonce_hash = ? AND task_id = ? AND operation = ? AND consumed_at IS NULL AND expires_at > ?""",
                    (agent_id, now, digest, task_id, operation, now),
                )
                if cur.rowcount == 1:
                    row = self._conn.execute("SELECT id FROM approvals WHERE nonce_hash = ?", (digest,)).fetchone()
                    approval_id = str(row["id"])
                    self._event(agent_id, "approval.consumed", "approval", approval_id, {"task_id": task_id, "operation": operation})
                else:
                    reason = self._approval_refusal_reason(digest, task_id, operation, now)
            if reason is not None:
                self._event(agent_id, "approval.refused", "approval", task_id, {"operation": operation, "reason": reason})
        if reason is not None:
            raise ApprovalRefused(f"approval refused for {operation} on task {task_id!r}: {reason}")
        assert approval_id is not None
        return self.get_approval(approval_id)

    def _approval_refusal_reason(self, digest: str, task_id: str, operation: str, now: str) -> str:
        row = self._conn.execute("SELECT task_id, operation, consumed_at, expires_at FROM approvals WHERE nonce_hash = ?", (digest,)).fetchone()
        if row is None:
            return "no such approval"
        if row["task_id"] != task_id or row["operation"] != operation:
            return "approval is bound to a different task or operation"
        if row["consumed_at"] is not None:
            return "approval already used"
        if row["expires_at"] <= now:
            return "approval expired"
        return "approval not usable"

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone())
        if record is None:
            raise NotFound(f"approval {approval_id!r} does not exist")
        record.pop("nonce_hash", None)
        return record

    def pending_approvals(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, task_id, operation, granted_by, granted_at, expires_at FROM approvals WHERE consumed_at IS NULL AND expires_at > ? ORDER BY granted_at",
            (utcnow(),),
        ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------- events
    def events(self, *, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        _check_int(limit, 1, 500, "limit")
        _check_int(after, 0, 2**62, "after")
        rows = self._conn.execute("SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?", (after, limit)).fetchall()
        return [r for r in (_row(x) for x in rows) if r is not None]

    def status(self) -> dict[str, Any]:
        """Human-facing summary: what is waiting on whom. Read-only."""
        agents = []
        for agent in self.list_agents():
            queued = int(self._conn.execute(
                "SELECT COUNT(*) FROM deliveries WHERE recipient_agent_id = ? AND state = 'queued'", (agent["id"],)
            ).fetchone()[0])
            claimed = int(self._conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assigned_agent_id = ? AND state = 'claimed'", (agent["id"],)
            ).fetchone()[0])
            worktree = _row(self._conn.execute("SELECT path, branch, head_oid, dirty, verified_at FROM worktrees WHERE agent_id = ?", (agent["id"],)).fetchone())
            agents.append({**agent, "queued_deliveries": queued, "claimed_tasks": claimed, "worktree": worktree})
        tasks = {
            state: int(self._conn.execute("SELECT COUNT(*) FROM tasks WHERE state = ?", (state,)).fetchone()[0])
            for state in ("open", "claimed", "completed", "blocked", "cancelled")
        }
        open_tasks = self.list_tasks(state="open", limit=50)["items"]
        pending = self.pending_approvals()
        return {
            "agents": agents,
            "tasks": tasks,
            "open_tasks": [{"id": t["id"], "title": t["title"], "assigned_to": t["assigned_agent_id"], "priority": t["priority"], "requires_worktree": t["requires_worktree"]} for t in open_tasks],
            "queued_deliveries": sum(a["queued_deliveries"] for a in agents),
            "approvals_pending": len(pending),
            "pending_approvals": pending,
            "events": int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
        }

    def counts(self) -> dict[str, int]:
        """Row counts per table; the crash suite compares these before and
        after a kill."""
        tables = ("agents", "sessions", "messages", "deliveries", "tasks", "runs", "leases", "artifacts", "events", "idempotency", "worktrees", "approvals")
        return {t: int(self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in tables}
