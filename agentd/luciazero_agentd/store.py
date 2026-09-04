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

from . import procinfo
from .adapters import dangling_option, reserved_flags_in
from .gitinfo import GitError, commit_exists, inspect_worktree, is_oid
from .migrations import LATEST_VERSION, MIGRATIONS
from .redact import CREDENTIAL_PATTERN, CREDENTIAL_PREFIX
from .redact import DEFAULT as DEFAULT_REDACTOR
from .redact import NONCE_PATTERN, NONCE_PREFIX, Redactor, find_credential_url

MESSAGE_KINDS = ("task", "question", "finding", "decision", "artifact", "result")
ARTIFACT_KINDS = ("commit", "patch", "report", "log", "relay")
PATH_ARTIFACT_KINDS = ("patch", "report", "log", "relay")
PROVIDERS = ("codex", "claude", "other")
TASK_OUTCOMES = ("completed", "blocked")
TASK_STATES = ("open", "waiting", "claimed", "completed", "blocked", "cancelled", "exhausted")
LIVE_TASK_STATES = ("open", "waiting", "claimed")
STOPPED_TASK_STATES = ("blocked", "cancelled", "exhausted")
# M5 loop stoppers. A hop is one message the conversation already carries, so
# the cap bounds a reply loop whether or not the models thread `reply_to`.
MAX_HOPS = 32
CONVERSATION_TTL_SECONDS = 24 * 3600
MAX_DEPENDENCIES = 32
MAX_GRAPH_NODES = 64
# What a task may be limited by. `seconds` and `turns` are measured by the
# daemon itself and cannot be under-reported; `tokens` and `cost_usd` can only
# come from a provider, so they are recorded with the reporter's trust label
# and may only ever grow.
BUDGET_DIMENSIONS = ("seconds", "turns", "tokens", "cost_usd")
REPORTED_DIMENSIONS = ("tokens", "cost_usd")
TASK_NODE_FIELDS = ("key", "title", "payload", "assigned_to", "priority", "requires_worktree", "depends_on", "budget")
# Operations that need a human approval nonce (ADR 0003). Fixed set: the
# store cannot be talked into a new category through any tool.
SENSITIVE_OPERATIONS = ("delete", "deploy", "production", "spend", "force_push", "public_contract", "scope_expansion")
APPROVAL_TTL_SECONDS = 900
# A terminal binding outlives a long working session but not a weekend; the
# credential dies with it (ADR 0004).
BINDING_TTL_SECONDS = 12 * 3600
# ADR 0006 adds "system": the dispatcher's own bookkeeping is neither a human's
# command nor a bound session's claim, and borrowing "human" for it would make
# the log say a person did what a machine did.
TRUST_LABELS = ("bound", "human", "system", "asserted")
LEASE_KINDS = ("session", "task")
LEASE_TTL_SECONDS = 300
RUN_STATES = ("running", "completed", "failed", "abandoned")
# A delivery the dispatcher may still start: never started, or a failed attempt
# with tries left.
DISPATCHABLE_DELIVERY_STATES = ("queued", "retryable_failed")
RUNNING_DELIVERY_STATES = ("dispatched", "processing")
# Everything the recipient has not read yet. A dispatched or processing
# delivery is still unread work: the dispatcher marks that a turn is running
# for it, which must not hide it from the worker that turn started.
PENDING_DELIVERY_STATES = ("queued", "dispatched", "processing")
MAX_WORKER_COMMAND = 32
DEFAULT_TURN_TIMEOUT_SECONDS = 600
# How far a managed turn may go on the user's machine when the provider asks:
# nothing beyond the model's own reply, commands and edits inside the bound
# worktree, or whatever it asks for. The default is the one that can do least.
APPROVAL_POLICIES = ("deny", "workspace", "accept")
BINDING_STATES = ("active", "revoked", "stale")
OWNERSHIPS = ("human", "managed")
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


class IdentityMismatch(ConflictError):
    """A credentialed session named an agent other than the one it is bound
    to (ADR 0004)."""


class DependencyRefused(ValidationError):
    """A task graph is not a DAG, or an edge names something undependable."""


class BudgetExceeded(ConflictError):
    """A per-task budget is spent. The task is stopped; nothing more runs on it."""


class ConversationLimit(ConflictError):
    """The conversation hit its hop cap or outlived its TTL."""


class GenerationFenced(ConflictError):
    """A run holding a stale generation tried to write; a newer lease owns the
    session now."""


class MootWork(ConflictError):
    """The work behind a delivery is finished, cancelled, or stopped, so there
    is nothing to start."""


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
    for key in ("payload", "capabilities", "depends_on", "result", "budget", "spent"):
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


def _elapsed_seconds(since: str, now: str) -> float:
    """Seconds between two ``utcnow()`` stamps; 0.0 if either cannot be read,
    so a malformed row can never manufacture an expiry."""
    try:
        return (datetime.fromisoformat(now) - datetime.fromisoformat(since)).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def _plus_seconds(stamp: str, seconds: int) -> str:
    return (datetime.fromisoformat(stamp) + timedelta(seconds=seconds)).isoformat(timespec="microseconds")


def _find_cycle(edges: dict[str, set[str]]) -> list[str]:
    """One cycle in ``node -> prerequisites``, for the refusal message."""
    colour: dict[str, int] = {}
    stack: list[str] = []

    def walk(node: str) -> Optional[list[str]]:
        colour[node] = 1
        stack.append(node)
        for nxt in sorted(edges.get(node, ())):
            if colour.get(nxt, 0) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if colour.get(nxt, 0) == 0:
                found = walk(nxt)
                if found:
                    return found
        stack.pop()
        colour[node] = 2
        return None

    for node in sorted(edges):
        if colour.get(node, 0) == 0:
            found = walk(node)
            if found:
                return found
    return []


def _topological_order(edges: dict[str, set[str]]) -> list[str]:
    """Kahn's algorithm over ``node -> prerequisites``, refusing a cycle before
    anything is written. Only edges inside the batch matter: a task that
    already exists cannot gain an edge later, so it can never close a cycle."""
    remaining = {node: set(deps) for node, deps in edges.items()}
    order: list[str] = []
    ready = sorted(node for node, deps in remaining.items() if not deps)
    seen = set(ready)
    while ready:
        node = ready.pop(0)
        order.append(node)
        for other, deps in remaining.items():
            if node in deps:
                deps.discard(node)
                if not deps and other not in seen:
                    ready.append(other)
                    seen.add(other)
        ready.sort()
    if len(order) != len(remaining):
        cycle = _find_cycle(edges)
        raise DependencyRefused(
            "dependency cycle: " + " -> ".join(cycle) if cycle else "the task graph contains a dependency cycle"
        )
    return order


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
        # How much the caller's identity is worth on this connection (ADR
        # 0004): "bound" only for a session that presented a live credential,
        # "human" for the user's own terminal commands, "system" for the
        # dispatcher's own bookkeeping (ADR 0006). The default is the weakest
        # label, so nothing reads as proven by accident.
        self.trust: str = "asserted"

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
            # Rebuilding a table means renaming and dropping one that other
            # tables reference, which SQLite only allows with foreign keys off
            # (and the pragma is a no-op inside a transaction, so it goes
            # here). `foreign_key_check` before the commit is what makes that
            # safe: a migration that leaves a dangling reference fails instead
            # of shipping one.
            self._conn.execute("PRAGMA foreign_keys = OFF")
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    current = self.schema_version()  # re-read under the lock
                    if version <= current:
                        self._conn.execute("COMMIT")
                        continue
                    for statement in _split_statements(sql):
                        self._conn.execute(statement)
                    violations = self._conn.execute("PRAGMA foreign_key_check").fetchall()
                    if violations:
                        raise StoreError(f"migration {version} left {len(violations)} dangling foreign key reference(s)")
                    self._conn.execute(f"PRAGMA user_version = {int(version)}")
                    self._conn.execute("COMMIT")
                except BaseException:
                    if self._conn.in_transaction:
                        self._conn.execute("ROLLBACK")
                    raise
            finally:
                self._conn.execute("PRAGMA foreign_keys = ON")
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
        # ADR 0004 invariant: an event never reads as proven unless it is.
        # The field is always present, so a missing one is a bug, not a maybe.
        payload = {**(payload or {}), "trust": self.trust}
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
    ) -> dict[str, Any]:
        """Persist one immutable message and its queued delivery together.

        The daemon sets ``hop_count`` itself -- how many messages the
        conversation already carries -- because a sender that could set its own
        hop count could reset a loop to zero forever. A reply inherits the
        conversation of the message it answers: threading with ``reply_to``
        alone must not open a fresh hop window, and a ``correlation_id`` that
        contradicts the parent is refused rather than honoured. Past
        ``MAX_HOPS``, or once the conversation outlives
        ``CONVERSATION_TTL_SECONDS``, the send is refused and recorded. A payload naming a task spends one
        of that task's turns; the send that would overspend stops the task
        instead of being delivered."""
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
        fingerprint = _fingerprint(
            "send_message", sender=sender, recipient=recipient, kind=kind,
            payload=encoded, correlation_id=correlation_id, reply_to=reply_to,
        )
        refusal: Optional[tuple[str, str, dict[str, Any]]] = None
        stopped: Optional[dict[str, Any]] = None
        stopped_task: Optional[str] = None
        message_id = ""
        with self._tx("send_message"):
            existing = self._replay(sender, idempotency_key, "send_message", fingerprint)
            if existing is not None:
                message_id = existing
            else:
                self._require_agent(sender)
                self._require_agent(recipient)
                conversation = correlation_id
                if reply_to is not None:
                    parent = self._conn.execute("SELECT correlation_id FROM messages WHERE id = ?", (reply_to,)).fetchone()
                    if parent is None:
                        raise NotFound(f"reply_to message {reply_to!r} does not exist")
                    # The parent's conversation is a fact, not an argument: a
                    # reply that could file itself elsewhere would open a fresh
                    # hop and TTL window every turn, and the loop stopper would
                    # stop nothing.
                    if conversation is None:
                        conversation = parent["correlation_id"]
                    elif conversation != parent["correlation_id"]:
                        raise ConflictError(
                            f"reply_to {reply_to!r} belongs to conversation {parent['correlation_id']!r}, not {conversation!r}; "
                            "omit reply_to to start a new conversation"
                        )
                now = utcnow()
                hop = 0
                if conversation is not None:
                    row = self._conn.execute(
                        "SELECT COUNT(*) AS hops, MIN(created_at) AS started_at FROM messages WHERE correlation_id = ?", (conversation,)
                    ).fetchone()
                    hop = int(row["hops"])
                    age = _elapsed_seconds(row["started_at"], now) if row["started_at"] else 0.0
                    if hop > MAX_HOPS:
                        refusal = ("conversation.hop_limit",
                                   f"conversation {conversation!r} reached the {MAX_HOPS}-hop limit; start a new one with a fresh correlation_id",
                                   {"hops": hop, "limit": MAX_HOPS, "sender": sender, "recipient": recipient})
                    elif age > CONVERSATION_TTL_SECONDS:
                        refusal = ("conversation.expired",
                                   f"conversation {conversation!r} is older than its {CONVERSATION_TTL_SECONDS}s time to live; start a new one with a fresh correlation_id",
                                   {"age_seconds": round(age, 3), "ttl_seconds": CONVERSATION_TTL_SECONDS, "sender": sender, "recipient": recipient})
                task_row = None
                if refusal is None and isinstance(payload, dict) and isinstance(payload.get("task_id"), str):
                    task_row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (payload["task_id"],)).fetchone()
                    if task_row is not None:
                        stopped = self._over_budget(task_row, now)
                        if stopped is None and task_row["state"] in LIVE_TASK_STATES:
                            budget = self._decode(task_row["budget"])
                            spent = self._decode(task_row["spent"])
                            turns = int(spent.get("turns", 0)) + 1
                            if "turns" in budget and turns > int(budget["turns"]):
                                stopped = {"dimension": "turns", "limit": budget["turns"], "spent": turns}
                        if stopped is not None:
                            stopped_task = str(task_row["id"])
                            self._exhaust_task(stopped_task, over=stopped, actor=sender, now=now)
                if refusal is not None:
                    self._event(sender, refusal[0], "message", conversation or "", refusal[2])
                elif stopped is None:
                    message_id = new_id("msg")
                    delivery_id = new_id("dlv")
                    self._conn.execute(
                        """INSERT INTO messages (id, sender_agent_id, recipient_agent_id, kind, payload,
                                                 correlation_id, reply_to, hop_count, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (message_id, sender, recipient, kind, encoded, conversation or message_id, reply_to, hop, now),
                    )
                    self._conn.execute(
                        "INSERT INTO deliveries (id, message_id, recipient_agent_id, state, updated_at) VALUES (?, ?, ?, 'queued', ?)",
                        (delivery_id, message_id, recipient, now),
                    )
                    if task_row is not None and task_row["state"] in LIVE_TASK_STATES:
                        spent = self._decode(task_row["spent"])
                        spent["turns"] = int(spent.get("turns", 0)) + 1
                        self._conn.execute("UPDATE tasks SET spent = ?, updated_at = ? WHERE id = ?", (json.dumps(spent, sort_keys=True), now, task_row["id"]))
                    self._event(sender, "message.sent", "message", message_id, {"recipient": recipient, "kind": kind, "delivery_id": delivery_id, "hop_count": hop, "redactions": redactions})
                    self._remember(sender, idempotency_key, "send_message", fingerprint, "message", message_id)
        if refusal is not None:
            raise ConversationLimit(refusal[1])
        if stopped is not None and stopped_task is not None:
            raise BudgetExceeded(self._budget_message(stopped_task, stopped))
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
        states: Sequence[str] = PENDING_DELIVERY_STATES,
        limit: int = 50,
        after: int = 0,
    ) -> dict[str, Any]:
        """Deliveries for ``agent_id`` in stable ``seq`` order with cursor
        pagination: pass the returned ``next_after`` back as ``after``.

        The default is everything unread, which includes the two states a
        managed turn passes through: a worker the dispatcher started must see
        the work it was started for."""
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

    def _transition_delivery(self, delivery_id: str, agent_id: str, *, from_state: Sequence[str], to_state: str, stamp: str, event: str) -> dict[str, Any]:
        _check_id(delivery_id, "delivery id", self._redactor)
        _check_id(agent_id, "agent id", self._redactor)
        allowed = (from_state,) if isinstance(from_state, str) else tuple(from_state)
        with self._tx(f"delivery_{to_state}"):
            row = self._conn.execute("SELECT state, recipient_agent_id FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
            if row is None:
                raise NotFound(f"delivery {delivery_id!r} does not exist")
            now = utcnow()
            cur = self._conn.execute(
                f"""UPDATE deliveries SET state = ?, {stamp} = ?, acknowledged_by = COALESCE(acknowledged_by, ?), updated_at = ?
                    WHERE id = ? AND state IN ({', '.join('?' * len(allowed))}) AND recipient_agent_id = ?""",
                (to_state, now, agent_id, now, delivery_id, *allowed, agent_id),
            )
            if cur.rowcount != 1:
                raise ConflictError(
                    f"delivery {delivery_id!r} is {row['state']} for {row['recipient_agent_id']!r}; "
                    f"{agent_id!r} cannot move it from {' or '.join(allowed)} to {to_state}"
                )
            self._event(agent_id, event, "delivery", delivery_id, {"from": from_state, "to": to_state})
        return self.get_delivery(delivery_id)

    def ack_delivery(self, delivery_id: str, agent_id: str) -> dict[str, Any]:
        """unread -> acknowledged: the recipient has read the message. A
        delivery a dispatcher is running a turn for is still unread, and the
        worker acknowledges it exactly as it would in the pull beta."""
        return self._transition_delivery(delivery_id, agent_id, from_state=PENDING_DELIVERY_STATES, to_state="acknowledged", stamp="acknowledged_at", event="delivery.acknowledged")

    def complete_delivery(self, delivery_id: str, agent_id: str) -> dict[str, Any]:
        """acknowledged -> completed: the recipient has finished handling it."""
        return self._transition_delivery(delivery_id, agent_id, from_state=("acknowledged",), to_state="completed", stamp="completed_at", event="delivery.completed")

    def get_delivery(self, delivery_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone())
        if record is None:
            raise NotFound(f"delivery {delivery_id!r} does not exist")
        return record

    # ------------------------------------------------------------------ tasks
    def _check_budget(self, value: Any) -> dict[str, Any]:
        """A budget names limits the daemon will stop the task on. Unknown
        dimensions are refused rather than ignored: a typo that silently
        removed the limit would be the worst possible failure here."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValidationError("budget must be an object")
        out: dict[str, Any] = {}
        for key in sorted(value):
            if key not in BUDGET_DIMENSIONS:
                raise ValidationError(f"budget has no dimension {key!r}; use {', '.join(BUDGET_DIMENSIONS)}")
            raw = value[key]
            if key == "cost_usd":
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    raise ValidationError("budget.cost_usd must be a number")
                if not 0 < float(raw) <= 1_000_000:
                    raise ValidationError("budget.cost_usd must be greater than 0")
                out[key] = float(raw)
            else:
                out[key] = _check_int(raw, 1, 10**9, f"budget.{key}")
        return out

    def _normalize_task(self, node: dict[str, Any], *, index: int) -> dict[str, Any]:
        """Validate one task description, single or a node of a graph."""
        where = "task" if index < 0 else f"node {index}"
        if not isinstance(node, dict):
            raise ValidationError(f"{where} must be an object")
        unknown = sorted(set(node) - set(TASK_NODE_FIELDS))
        if unknown:
            raise ValidationError(f"{where} has unknown keys: {', '.join(unknown)}")
        assigned_to = node.get("assigned_to")
        if assigned_to is not None:
            _check_id(assigned_to, f"{where} assigned_to", self._redactor)
        requires_worktree = node.get("requires_worktree", False)
        if not isinstance(requires_worktree, bool):
            raise ValidationError(f"{where} requires_worktree must be a boolean")
        raw_deps = node.get("depends_on") or []
        if not isinstance(raw_deps, (list, tuple)):
            raise ValidationError(f"{where} depends_on must be an array")
        if len(raw_deps) > MAX_DEPENDENCIES:
            raise ValidationError(f"{where} depends_on has more than {MAX_DEPENDENCIES} entries")
        depends_on: list[str] = []
        for dep in raw_deps:
            _check_id(dep, f"{where} depends_on entry", self._redactor)
            if dep not in depends_on:
                depends_on.append(dep)
        key = node.get("key")
        if key is not None:
            _check_id(key, f"{where} key", self._redactor)
            if key in depends_on:
                raise DependencyRefused(f"task {key!r} cannot depend on itself")
        encoded, redactions = self._payload(node.get("payload") or {}, f"{where} payload")
        return {
            "key": key,
            "title": self.redact(_check_text(node.get("title"), f"{where} title", 500)),
            "payload": encoded,
            "redactions": redactions,
            "assigned_to": assigned_to,
            "priority": _check_int(node.get("priority", 0), -100, 100, f"{where} priority"),
            "requires_worktree": requires_worktree,
            "depends_on": depends_on,
            "budget": self._check_budget(node.get("budget")),
        }

    def _dependency_states(self, task_id: str) -> dict[str, str]:
        rows = self._conn.execute(
            """SELECT d.depends_on_id AS id, t.state AS state
                 FROM task_deps d JOIN tasks t ON t.id = d.depends_on_id
                WHERE d.task_id = ? ORDER BY d.depends_on_id""",
            (task_id,),
        ).fetchall()
        return {row["id"]: row["state"] for row in rows}

    def _require_dependencies(self, depends_on: Sequence[str]) -> dict[str, str]:
        """Existing prerequisites and their states. Missing ones are refused:
        an edge to a task that does not exist would wait forever."""
        states: dict[str, str] = {}
        for dep in depends_on:
            row = self._conn.execute("SELECT state FROM tasks WHERE id = ?", (dep,)).fetchone()
            if row is None:
                raise NotFound(f"task {dep!r} does not exist; a dependency must name a task that already exists")
            states[dep] = row["state"]
        return states

    def _insert_task(self, prepared: dict[str, Any], *, created_by: str, task_id: str, now: str, dep_states: dict[str, str]) -> None:
        """Insert one task, its edges, and the state its prerequisites imply."""
        blocked_by = [dep for dep, state in dep_states.items() if state in STOPPED_TASK_STATES]
        unmet = [dep for dep, state in dep_states.items() if state != "completed"]
        result = None
        if blocked_by:
            state = "blocked"
            result = json.dumps({"blocked_by": blocked_by[0], "prerequisite_state": dep_states[blocked_by[0]]}, sort_keys=True)
        elif unmet:
            state = "waiting"
        else:
            state = "open"
        budget = prepared["budget"]
        deadline = _plus_seconds(now, int(budget["seconds"])) if "seconds" in budget else None
        self._conn.execute(
            """INSERT INTO tasks (id, title, payload, created_by_agent_id, assigned_agent_id, priority,
                                  depends_on, budget, spent, deadline_at, state, result, requires_worktree, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, prepared["title"], prepared["payload"], created_by, prepared["assigned_to"], prepared["priority"],
             json.dumps(list(dep_states), sort_keys=True), json.dumps(budget, sort_keys=True),
             json.dumps({"turns": 0, "tokens": 0, "cost_usd": 0.0}, sort_keys=True),
             deadline, state, result, int(prepared["requires_worktree"]), now, now),
        )
        for dep in dep_states:
            self._conn.execute("INSERT INTO task_deps (task_id, depends_on_id, created_at) VALUES (?, ?, ?)", (task_id, dep, now))
        self._event(created_by, "task.created", "task", task_id, {
            "title": prepared["title"], "assigned_to": prepared["assigned_to"], "requires_worktree": prepared["requires_worktree"],
            "state": state, "depends_on": list(dep_states), "budget": budget, "redactions": prepared["redactions"],
        })

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
        depends_on: Optional[Sequence[str]] = None,
        budget: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """One task. ``depends_on`` may only name tasks that already exist, so
        a single creation cannot close a cycle; ``create_task_graph`` is how
        tasks that depend on one another are created together. A task with an
        unfinished prerequisite starts ``waiting`` and cannot be claimed until
        the daemon opens it."""
        _check_id(created_by, "created_by", self._redactor)
        if idempotency_key is not None:
            _check_id(idempotency_key, "idempotency key", self._redactor)
        prepared = self._normalize_task({
            "title": title, "payload": payload, "assigned_to": assigned_to, "priority": priority,
            "requires_worktree": requires_worktree, "depends_on": depends_on, "budget": budget,
        }, index=-1)
        fingerprint = _fingerprint(
            "create_task", title=prepared["title"], created_by=created_by, payload=prepared["payload"],
            assigned_to=prepared["assigned_to"], priority=prepared["priority"], requires_worktree=prepared["requires_worktree"],
            depends_on=prepared["depends_on"], budget=prepared["budget"],
        )
        with self._tx("create_task"):
            existing = self._replay(created_by, idempotency_key, "create_task", fingerprint)
            if existing is not None:
                task_id = existing
            else:
                self._require_agent(created_by)
                if prepared["assigned_to"] is not None:
                    self._require_agent(prepared["assigned_to"])
                dep_states = self._require_dependencies(prepared["depends_on"])
                task_id = new_id("tsk")
                self._insert_task(prepared, created_by=created_by, task_id=task_id, now=utcnow(), dep_states=dep_states)
                self._remember(created_by, idempotency_key, "create_task", fingerprint, "task", task_id)
        return self.get_task(task_id)

    def create_task_graph(self, *, nodes: Sequence[dict[str, Any]], created_by: str, idempotency_key: Optional[str] = None) -> list[dict[str, Any]]:
        """Create several tasks and the edges between them in one transaction.
        A node's ``depends_on`` names either another node's ``key`` in the same
        batch or a task that already exists. A batch with a cycle is refused
        whole, so a half-built graph is never committed. With an
        ``idempotency_key`` each node replays under ``<key>:<node key>``, so a
        retried batch returns the same tasks instead of a second graph."""
        _check_id(created_by, "created_by", self._redactor)
        if idempotency_key is not None:
            _check_id(idempotency_key, "idempotency key", self._redactor)
        if not isinstance(nodes, (list, tuple)) or not nodes:
            raise ValidationError("nodes must be a non-empty array")
        if len(nodes) > MAX_GRAPH_NODES:
            raise ValidationError(f"a task graph carries at most {MAX_GRAPH_NODES} nodes, got {len(nodes)}")
        prepared: dict[str, dict[str, Any]] = {}
        for index, node in enumerate(nodes):
            item = self._normalize_task(node, index=index)
            if item["key"] is None:
                raise ValidationError(f"node {index} needs a key naming it inside the batch")
            if item["key"] in prepared:
                raise ValidationError(f"node key {item['key']!r} is used twice")
            prepared[item["key"]] = item
        local_edges = {key: {dep for dep in item["depends_on"] if dep in prepared} for key, item in prepared.items()}
        order = _topological_order(local_edges)
        created: dict[str, str] = {}
        with self._tx("create_task_graph"):
            self._require_agent(created_by)
            fingerprints = {
                key: _fingerprint(
                    "create_task", title=item["title"], created_by=created_by, payload=item["payload"],
                    assigned_to=item["assigned_to"], priority=item["priority"], requires_worktree=item["requires_worktree"],
                    depends_on=item["depends_on"], budget=item["budget"],
                )
                for key, item in prepared.items()
            }
            now = utcnow()
            for key in order:
                item = prepared[key]
                node_key = f"{idempotency_key}:{key}" if idempotency_key is not None else None
                existing = self._replay(created_by, node_key, "create_task", fingerprints[key])
                if existing is not None:
                    created[key] = existing
                    continue
                if item["assigned_to"] is not None:
                    self._require_agent(item["assigned_to"])
                external = [dep for dep in item["depends_on"] if dep not in prepared]
                dep_states = self._require_dependencies(external)
                for dep in item["depends_on"]:
                    if dep in prepared:
                        dep_states[created[dep]] = self._conn.execute("SELECT state FROM tasks WHERE id = ?", (created[dep],)).fetchone()["state"]
                task_id = new_id("tsk")
                self._insert_task(item, created_by=created_by, task_id=task_id, now=now, dep_states=dep_states)
                self._remember(created_by, node_key, "create_task", fingerprints[key], "task", task_id)
                created[key] = task_id
            self._event(created_by, "task_graph.created", "task", created[order[0]], {"nodes": [created[key] for key in order], "keys": list(order)})
        return [self.get_task(created[key]) for key in order]

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
            params.append(_check_enum(state, TASK_STATES, "state"))
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
        stopped: Optional[dict[str, Any]] = None
        with self._tx("claim_task"):
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise NotFound(f"task {task_id!r} does not exist")
            self._require_agent(agent_id)
            now = utcnow()
            stopped = self._over_budget(row, now)
            if stopped is not None:
                # Stopping is a write that has to survive the refusal, so it
                # commits with this transaction and the caller is told after.
                self._exhaust_task(task_id, over=stopped, actor=agent_id, now=now)
            else:
                cur = self._conn.execute(
                    """UPDATE tasks SET state = 'claimed', assigned_agent_id = ?, version = version + 1, claimed_at = ?, updated_at = ?
                       WHERE id = ? AND state = 'open' AND (assigned_agent_id IS NULL OR assigned_agent_id = ?)""",
                    (agent_id, now, now, task_id, agent_id),
                )
                if cur.rowcount != 1:
                    unmet = [dep for dep, state in self._dependency_states(task_id).items() if state != "completed"] if row["state"] == "waiting" else []
                    raise ConflictError(
                        f"task {task_id!r} is {row['state']}"
                        + (f" on {', '.join(unmet)}" if unmet else "")
                        + (f" and assigned to {row['assigned_agent_id']!r}" if row["assigned_agent_id"] else "")
                        + f"; {agent_id!r} did not claim it"
                    )
                self._refresh_worktree(agent_id, info)
                self._event(agent_id, "task.claimed", "task", task_id, {"worktree": info["path"] if info else None})
        if stopped is not None:
            raise BudgetExceeded(self._budget_message(task_id, stopped))
        return self.get_task(task_id)

    def complete_task(
        self,
        task_id: str,
        agent_id: str,
        *,
        result: Optional[dict[str, Any]] = None,
        outcome: str = "completed",
        artifacts: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        """claimed -> completed | blocked, only by the agent holding the claim.
        ``artifacts`` cites artifact records as the evidence for the result;
        each must already exist, so a result cannot name work nobody published.
        Completing a task settles everything waiting on it in the same
        transaction: dependents whose prerequisites are all done open, and
        dependents of a task that ended any other way are blocked, because a
        prerequisite that will never complete can never be waited out."""
        _check_id(task_id, "task id", self._redactor)
        _check_id(agent_id, "agent id", self._redactor)
        _check_enum(outcome, TASK_OUTCOMES, "outcome")
        body = dict(result or {})
        cited: list[str] = []
        if artifacts is not None:
            if not isinstance(artifacts, (list, tuple)):
                raise ValidationError("artifacts must be an array of artifact ids")
            if "artifacts" in body:
                raise ValidationError("pass cited artifacts once: either in result.artifacts or in artifacts, not both")
            for artifact_id in artifacts:
                _check_id(artifact_id, "artifact id", self._redactor)
                if artifact_id not in cited:
                    cited.append(artifact_id)
            body["artifacts"] = cited
        encoded, _ = self._payload(body, "result")
        with self._tx("complete_task"):
            row = self._conn.execute("SELECT state, assigned_agent_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise NotFound(f"task {task_id!r} does not exist")
            for artifact_id in cited:
                if self._conn.execute("SELECT 1 FROM artifacts WHERE id = ?", (artifact_id,)).fetchone() is None:
                    raise NotFound(f"artifact {artifact_id!r} does not exist; publish it before citing it")
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
            self._event(agent_id, f"task.{outcome}", "task", task_id, {"artifacts": cited})
            self._settle_dependents(task_id, state=outcome, actor=agent_id, now=now)
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
            dead = self._dead_letter_task(task_id, actor=by, reason="task cancelled", now=now)
            self._event(by, "task.cancelled", "task", task_id, {"was": row["state"], "holder": row["assigned_agent_id"], "reason": note, "dead_lettered": dead})
            self._settle_dependents(task_id, state="cancelled", actor=by, now=now)
        return self.get_task(task_id)

    # --------------------------------------------------- dependencies, budgets
    def _dead_letter_task(self, task_id: str, *, actor: str, reason: str, now: str) -> list[str]:
        """Queued task messages for a stopped task are dead work: dead-letter
        them so `bus status` stops asking for a turn nobody should start.
        Acknowledged ones stay with their reader to complete."""
        queued = self._conn.execute(
            """SELECT d.id, m.payload FROM deliveries d JOIN messages m ON m.id = d.message_id
               WHERE d.state = 'queued' AND m.kind = 'task'"""
        ).fetchall()
        dead: list[str] = []
        for delivery in queued:
            try:
                payload = json.loads(delivery["payload"])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("task_id") == task_id:
                self._conn.execute("UPDATE deliveries SET state = 'dead_letter', updated_at = ? WHERE id = ? AND state = 'queued'", (now, delivery["id"]))
                self._event(actor, "delivery.dead_letter", "delivery", delivery["id"], {"task_id": task_id, "reason": reason})
                dead.append(delivery["id"])
        return dead

    def _settle_dependents(self, task_id: str, *, state: str, actor: str, now: str) -> dict[str, str]:
        """Move everything waiting on a finished task, transactionally. A
        completed prerequisite opens the dependents whose other prerequisites
        are done; any other ending blocks them, and blocking cascades down the
        graph, because a task waiting on a task that will never complete would
        otherwise wait forever."""
        settled: dict[str, str] = {}
        pending: list[tuple[str, str]] = [(task_id, state)]
        while pending:
            finished, finished_state = pending.pop(0)
            rows = self._conn.execute(
                """SELECT t.id AS id FROM task_deps d JOIN tasks t ON t.id = d.task_id
                    WHERE d.depends_on_id = ? AND t.state = 'waiting' ORDER BY t.seq""",
                (finished,),
            ).fetchall()
            for row in rows:
                dependent = row["id"]
                if finished_state == "completed":
                    unmet = [dep for dep, dep_state in self._dependency_states(dependent).items() if dep_state != "completed"]
                    if unmet:
                        continue
                    self._conn.execute(
                        "UPDATE tasks SET state = 'open', version = version + 1, updated_at = ? WHERE id = ? AND state = 'waiting'",
                        (now, dependent),
                    )
                    self._event(actor, "task.unblocked", "task", dependent, {"prerequisite": finished})
                    settled[dependent] = "open"
                else:
                    self._conn.execute(
                        """UPDATE tasks SET state = 'blocked', result = ?, version = version + 1, completed_at = ?, updated_at = ?
                           WHERE id = ? AND state = 'waiting'""",
                        (json.dumps({"blocked_by": finished, "prerequisite_state": finished_state}, sort_keys=True), now, now, dependent),
                    )
                    self._event(actor, "task.blocked", "task", dependent, {"blocked_by": finished, "prerequisite_state": finished_state})
                    settled[dependent] = "blocked"
                    pending.append((dependent, "blocked"))
        return settled

    @staticmethod
    def _decode(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return {}
        return value if isinstance(value, dict) else {}

    def _over_budget(self, row: Any, now: str) -> Optional[dict[str, Any]]:
        """The first budget dimension a live task has already spent, or None.
        A task that is already finished is never reported over: stopping is
        only meaningful while there is something left to stop."""
        if row["state"] not in LIVE_TASK_STATES:
            return None
        budget = self._decode(row["budget"])
        if not budget:
            return None
        spent = self._decode(row["spent"])
        if "seconds" in budget and row["deadline_at"] and now > row["deadline_at"]:
            return {"dimension": "seconds", "limit": budget["seconds"], "spent": round(_elapsed_seconds(row["created_at"], now), 3)}
        for dimension in ("turns", "tokens", "cost_usd"):
            if dimension in budget and float(spent.get(dimension, 0)) > float(budget[dimension]):
                return {"dimension": dimension, "limit": budget[dimension], "spent": spent.get(dimension, 0)}
        return None

    def _budget_message(self, task_id: str, over: dict[str, Any]) -> str:
        return (f"task {task_id!r} is stopped: its {over['dimension']} budget of {over['limit']} is spent "
                f"({over['spent']}); a human reopens it by creating a new task")

    def _exhaust_task(self, task_id: str, *, over: dict[str, Any], actor: str, now: str) -> None:
        """Stop a task on a spent budget: terminal state, queued work dead-
        lettered, dependents settled. M6's dispatcher never resumes a task in
        this state, which is what makes a budget a stop and not a warning."""
        self._conn.execute(
            """UPDATE tasks SET state = 'exhausted', result = ?, version = version + 1, completed_at = ?, updated_at = ?
               WHERE id = ? AND state IN ('open', 'waiting', 'claimed')""",
            (json.dumps({"stopped": "budget", **over}, sort_keys=True), now, now, task_id),
        )
        dead = self._dead_letter_task(task_id, actor=actor, reason="task budget spent", now=now)
        self._event(actor, "task.exhausted", "task", task_id, {**over, "dead_lettered": dead})
        self._settle_dependents(task_id, state="exhausted", actor=actor, now=now)

    def record_usage(self, task_id: str, agent_id: str, *, tokens: Optional[int] = None, cost_usd: Optional[float] = None) -> dict[str, Any]:
        """Add provider-measured usage to a task. The daemon measures turns and
        elapsed time itself; tokens and cost can only come from the provider,
        so they are additive only -- a report may raise a total, never lower one
        -- and the event keeps what the reporter's identity was worth. Spending
        the budget stops the task rather than raising: the reporter is telling
        the truth about work already done. Only the agent holding the claim may
        report: a peer that could credit usage to a task it never claimed could
        spend another agent's budget and stop its work, and a stop has no
        reopening."""
        _check_id(task_id, "task id", self._redactor)
        _check_id(agent_id, "agent id", self._redactor)
        if tokens is None and cost_usd is None:
            raise ValidationError(f"record usage with at least one of {', '.join(REPORTED_DIMENSIONS)}")
        if tokens is not None:
            _check_int(tokens, 0, 10**9, "tokens")
        if cost_usd is not None:
            if isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)):
                raise ValidationError("cost_usd must be a number")
            if not 0 <= float(cost_usd) <= 1_000_000:
                raise ValidationError("cost_usd must be 0 or more")
        with self._tx("record_usage"):
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise NotFound(f"task {task_id!r} does not exist")
            self._require_agent(agent_id)
            if row["state"] != "claimed" or row["assigned_agent_id"] != agent_id:
                holder = f" held by {row['assigned_agent_id']!r}" if row["assigned_agent_id"] else ""
                raise ConflictError(
                    f"task {task_id!r} is {row['state']}{holder}; only the agent holding the claim records usage against it"
                )
            now = utcnow()
            spent = self._decode(row["spent"])
            if tokens is not None:
                spent["tokens"] = int(spent.get("tokens", 0)) + int(tokens)
            if cost_usd is not None:
                spent["cost_usd"] = round(float(spent.get("cost_usd", 0.0)) + float(cost_usd), 6)
            self._conn.execute("UPDATE tasks SET spent = ?, updated_at = ? WHERE id = ?", (json.dumps(spent, sort_keys=True), now, task_id))
            self._event(agent_id, "task.usage", "task", task_id, {"tokens": tokens, "cost_usd": cost_usd, "spent": spent})
            over = self._over_budget(self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone(), now)
            if over is not None:
                self._exhaust_task(task_id, over=over, actor=agent_id, now=now)
        return self.get_task(task_id)

    def task_view(self, task_id: str) -> dict[str, Any]:
        """The task record plus what a worker needs to decide what to do with
        it: prerequisite states, what is still unmet, what the budget has left,
        and the artifacts published against it with their provenance."""
        record = self.get_task(task_id)
        states = self._dependency_states(task_id)
        record["dependencies"] = [{"task_id": dep, "state": state} for dep, state in states.items()]
        record["unmet_dependencies"] = [dep for dep, state in states.items() if state != "completed"]
        record["blocks"] = [row["task_id"] for row in self._conn.execute(
            "SELECT task_id FROM task_deps WHERE depends_on_id = ? ORDER BY task_id", (task_id,)).fetchall()]
        record["artifacts"] = self.list_artifacts(task_id=task_id)["items"]
        budget = self._decode(record.get("budget"))
        spent = self._decode(record.get("spent"))
        remaining: dict[str, Any] = {}
        for dimension, limit in budget.items():
            if dimension == "seconds":
                used = _elapsed_seconds(record["created_at"], utcnow())
                remaining[dimension] = round(float(limit) - used, 3)
            else:
                remaining[dimension] = round(float(limit) - float(spent.get(dimension, 0)), 6)
        record["budget_remaining"] = remaining
        return record

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
                if task_id is not None:
                    task_row = self._conn.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()
                    if task_row is None:
                        raise NotFound(f"task {task_id!r} does not exist")
                    # A stopped task takes no new work. A finished one still
                    # accepts a late report, which is how a verifier files
                    # evidence about a task somebody else completed.
                    if task_row["state"] in ("cancelled", "exhausted"):
                        raise ConflictError(f"task {task_id!r} is {task_row['state']}; no more artifacts are published against it")
                artifact_id = new_id("art")
                self._conn.execute(
                    "INSERT INTO artifacts (id, task_id, kind, ref, sha256, produced_by_agent_id, trust, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (artifact_id, task_id, kind, ref, digest, produced_by, self.trust, utcnow()),
                )
                self._refresh_worktree(produced_by, info)
                self._event(produced_by, "artifact.published", "artifact", artifact_id, {"kind": kind, "task_id": task_id, "worktree": info["path"], "bytes": size, "trust": self.trust})
                self._remember(produced_by, idempotency_key, "publish_artifact", fingerprint, "artifact", artifact_id)
        return self.get_artifact(artifact_id)

    def list_artifacts(self, *, task_id: Optional[str] = None, produced_by: Optional[str] = None, limit: int = 50, after: int = 0) -> dict[str, Any]:
        """Artifacts in stable order, filtered by the task they belong to or
        the agent that produced them. Each row carries the producer and the
        trust its identity had at publication, so provenance is readable
        without walking the event log."""
        _check_int(limit, 1, 500, "limit")
        _check_int(after, 0, 2**62, "after")
        clauses = ["seq > ?"]
        params: list[Any] = [after]
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(_check_id(task_id, "task id", self._redactor))
        if produced_by is not None:
            clauses.append("produced_by_agent_id = ?")
            params.append(_check_id(produced_by, "produced_by", self._redactor))
        rows = self._conn.execute(
            f"SELECT * FROM artifacts WHERE {' AND '.join(clauses)} ORDER BY seq LIMIT ?", (*params, limit + 1)
        ).fetchall()
        items = [r for r in (_row(x) for x in rows[:limit]) if r is not None]
        return {"items": items, "next_after": items[-1]["seq"] if items else after, "has_more": len(rows) > limit}

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

    # --------------------------------------------------------------- bindings
    def bind_terminal(
        self,
        agent_id: str,
        *,
        provider: str,
        by: str,
        tty: Optional[str] = None,
        pid: Optional[int] = None,
        process_started_at: Optional[str] = None,
        cwd: Optional[str] = None,
        ownership: str = "human",
        ttl_seconds: int = BINDING_TTL_SECONDS,
    ) -> tuple[dict[str, Any], str]:
        """Human channel only (never an MCP tool): bind one terminal to one
        agent and mint the session credential that proves it. Only the hash
        is stored; the plain credential is returned once, for the command
        that will hand it to that terminal's provider process.

        An agent may hold one live binding, and a terminal may hold one, so
        binding either again revokes the previous one instead of creating a
        second way to answer as the same role."""
        _check_id(agent_id, "agent id", self._redactor)
        _check_enum(provider, PROVIDERS, "provider")
        _check_enum(ownership, OWNERSHIPS, "ownership")
        _check_text(by, "by", 128)
        _check_int(ttl_seconds, 60, 86_400, "ttl_seconds")
        if tty is not None:
            tty = _check_text(tty, "tty", 64)
            if self._redactor.scan(tty):
                raise UnsafeReference("tty carries a secret shape")
        if pid is not None:
            pid = _check_int(pid, 1, 2**31 - 1, "pid")
        if process_started_at is not None:
            process_started_at = _check_text(process_started_at, "process_started_at", 64)
        if cwd is not None:
            cwd = _check_path_arg(cwd)
            if self._redactor.scan(cwd):
                raise UnsafeReference("cwd carries a secret shape")
        credential = CREDENTIAL_PREFIX + secrets.token_hex(16)
        digest = hashlib.sha256(credential.encode("utf-8")).hexdigest()
        binding_id = new_id("bind")
        with self._tx("bind_terminal"):
            self._require_agent(agent_id)
            # ADR 0001: a human-owned session is out of the dispatcher's reach.
            # Binding replaces whatever the agent had, so without this the
            # dispatcher could take an agent away from the terminal the user is
            # sitting in front of, which is the one thing ownership promises.
            if ownership == "managed":
                current = self.binding_of(agent_id)
                if current is not None and current["ownership"] == "human":
                    raise ConflictError(
                        f"agent {agent_id!r} is bound to a human terminal ({current['tty'] or 'no tty'}); "
                        "the dispatcher never takes over a session the user owns"
                    )
            now = datetime.now(timezone.utc)
            stamp = now.isoformat(timespec="microseconds")
            expires = (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="microseconds")
            replaced = [dict(r) for r in self._conn.execute(
                "SELECT id, agent_id, tty FROM bindings WHERE state = 'active' AND (agent_id = ? OR (tty IS NOT NULL AND tty = ?))",
                (agent_id, tty),
            ).fetchall()]
            for old in replaced:
                self._end_binding(str(old["id"]), state="revoked", by=by, reason="rebound", now=stamp)
            generation = int(self._conn.execute(
                "SELECT COALESCE(MAX(generation), -1) + 1 AS g FROM bindings WHERE agent_id = ?", (agent_id,)
            ).fetchone()["g"])
            self._conn.execute(
                """INSERT INTO bindings (id, agent_id, credential_hash, provider, ownership, tty, pid,
                                         process_started_at, cwd, generation, state, bound_by, created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
                (binding_id, agent_id, digest, provider, ownership, tty, pid, process_started_at, cwd, generation, by, stamp, stamp, expires),
            )
            self._event(by, "binding.created", "binding", binding_id, {
                "agent_id": agent_id, "provider": provider, "ownership": ownership, "tty": tty,
                "pid": pid, "cwd": cwd, "generation": generation, "expires_at": expires,
                "replaced": [str(r["id"]) for r in replaced],
            })
        return self.get_binding(binding_id), credential

    def _end_binding(self, binding_id: str, *, state: str, by: str, reason: str, now: str) -> None:
        """Inside a transaction: finish a live binding, which is what kills
        its credential."""
        cur = self._conn.execute(
            "UPDATE bindings SET state = ?, ended_at = ?, ended_reason = ?, updated_at = ? WHERE id = ? AND state = 'active'",
            (state, now, reason, now, binding_id),
        )
        if cur.rowcount == 1:
            self._event(by, "binding.revoked" if state == "revoked" else "binding.stale", "binding", binding_id, {"reason": reason})

    def bind_process(self, binding_id: str, *, pid: int, process_started_at: Optional[str], tty: Optional[str] = None, cwd: Optional[str] = None) -> dict[str, Any]:
        """Fill in the process identity of a binding created before the
        process existed. `run` mints the credential, spawns the provider with
        it, and only then knows the pid: without this the reaper would have
        nothing to check."""
        _check_id(binding_id, "binding id", self._redactor)
        pid = _check_int(pid, 1, 2**31 - 1, "pid")
        if process_started_at is not None:
            process_started_at = _check_text(process_started_at, "process_started_at", 64)
        if tty is not None:
            tty = _check_text(tty, "tty", 64)
        if cwd is not None:
            cwd = _check_path_arg(cwd)
        with self._tx("bind_process"):
            row = self._conn.execute("SELECT state, pid FROM bindings WHERE id = ?", (binding_id,)).fetchone()
            if row is None:
                raise NotFound(f"binding {binding_id!r} does not exist")
            if row["state"] != "active":
                raise ConflictError(f"binding {binding_id!r} is {row['state']}")
            if row["pid"] is not None:
                raise ConflictError(f"binding {binding_id!r} already names a process")
            now = utcnow()
            self._conn.execute(
                """UPDATE bindings SET pid = ?, process_started_at = ?,
                       tty = COALESCE(?, tty), cwd = COALESCE(?, cwd), updated_at = ?
                   WHERE id = ?""",
                (pid, process_started_at, tty, cwd, now, binding_id),
            )
            self._event("daemon", "binding.process", "binding", binding_id, {"pid": pid, "tty": tty, "cwd": cwd})
        return self.get_binding(binding_id)

    def revoke_binding(self, binding_id: str, *, by: str, reason: str = "detached") -> dict[str, Any]:
        """Human channel: detach a terminal. The credential stops working on
        the next request, which is every request."""
        _check_id(binding_id, "binding id", self._redactor)
        _check_text(by, "by", 128)
        _check_text(reason, "reason", 256)
        with self._tx("revoke_binding"):
            row = self._conn.execute("SELECT state FROM bindings WHERE id = ?", (binding_id,)).fetchone()
            if row is None:
                raise NotFound(f"binding {binding_id!r} does not exist")
            if row["state"] != "active":
                raise ConflictError(f"binding {binding_id!r} is already {row['state']}")
            self._end_binding(binding_id, state="revoked", by=by, reason=reason, now=utcnow())
        return self.get_binding(binding_id)

    def resolve_credential(self, credential: Any, *, alive: Callable[[Optional[int], Optional[str]], bool] = procinfo.alive) -> Optional[dict[str, Any]]:
        """Which agent is this credential? None when it is unknown, revoked,
        expired, or its process is gone.

        Called on every request, not only at MCP initialize: that is what
        makes `detach` and a dead terminal take effect rather than being
        recorded opinions. A binding whose process disappeared is marked
        stale here, once."""
        if not isinstance(credential, str) or not CREDENTIAL_PATTERN.fullmatch(credential):
            return None  # never echo the value
        digest = hashlib.sha256(credential.encode("utf-8")).hexdigest()
        row = _row(self._conn.execute("SELECT * FROM bindings WHERE credential_hash = ?", (digest,)).fetchone())
        if row is None or row["state"] != "active":
            return None
        now = utcnow()
        if str(row["expires_at"]) <= now:
            with self._tx("expire_binding"):
                self._end_binding(str(row["id"]), state="stale", by="daemon", reason="expired", now=now)
            return None
        try:
            still_there = alive(row["pid"], row["process_started_at"])
        except procinfo.ProcessError:
            still_there = False  # cannot verify the terminal: refuse, never assume
        if not still_there:
            with self._tx("stale_binding"):
                self._end_binding(str(row["id"]), state="stale", by="daemon", reason="process gone", now=now)
            return None
        row.pop("credential_hash", None)
        return row

    def refuse_identity(self, binding: dict[str, Any], *, claimed: str, field: str, tool: str) -> None:
        """Record that a bound session named another agent, then let the
        caller raise. The claim is kept: this is the signal that a session is
        confused or lying."""
        self._event(str(binding["agent_id"]), "session.identity_refused", "binding", str(binding["id"]), {
            "claimed": self.redact(str(claimed)[:MAX_ID_LENGTH]), "field": field, "tool": tool,
        })

    def get_binding(self, binding_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM bindings WHERE id = ?", (binding_id,)).fetchone())
        if record is None:
            raise NotFound(f"binding {binding_id!r} does not exist")
        record.pop("credential_hash", None)
        return record

    def list_bindings(self, *, states: Sequence[str] = ("active",), alive: Optional[Callable[[Optional[int], Optional[str]], bool]] = procinfo.alive) -> list[dict[str, Any]]:
        """Live bindings, reaping any whose process has gone. The human
        commands walk this, so looking is what cleans up."""
        for state in states:
            _check_enum(state, BINDING_STATES, "state")
        if alive is not None and "active" in states:
            now = utcnow()
            for row in self._conn.execute("SELECT id, pid, process_started_at, expires_at FROM bindings WHERE state = 'active'").fetchall():
                reason = "expired" if str(row["expires_at"]) <= now else (None if alive(row["pid"], row["process_started_at"]) else "process gone")
                if reason is not None:
                    with self._tx("reap_binding"):
                        self._end_binding(str(row["id"]), state="stale", by="daemon", reason=reason, now=now)
        marks = ",".join("?" for _ in states)
        rows = self._conn.execute(
            f"SELECT * FROM bindings WHERE state IN ({marks}) ORDER BY created_at DESC", tuple(states)
        ).fetchall()
        out = []
        for row in rows:
            record = dict(row)
            record.pop("credential_hash", None)
            out.append(record)
        return out

    def binding_of(self, agent_id: str, *, alive: Optional[Callable[[Optional[int], Optional[str]], bool]] = procinfo.alive) -> Optional[dict[str, Any]]:
        """The live binding of one agent, if it has one.

        "Live" has to mean the same thing here as it does on the wire, or a
        status view would keep calling an agent verified after its credential
        died. Expiry and liveness are checked, exactly as `resolve_credential`
        checks them; unlike the reaper this only reports, so a read-only
        status path never writes."""
        _check_id(agent_id, "agent id", self._redactor)
        record = _row(self._conn.execute(
            "SELECT * FROM bindings WHERE agent_id = ? AND state = 'active' AND expires_at > ?",
            (agent_id, utcnow()),
        ).fetchone())
        if record is None:
            return None
        if alive is not None and not alive(record["pid"], record["process_started_at"]):
            return None
        record.pop("credential_hash", None)
        return record

    # ------------------------------------------------- managed dispatch (M6)
    def enrol_worker(
        self,
        agent_id: str,
        *,
        provider: str,
        command: Sequence[str],
        cwd: Optional[str] = None,
        max_attempts: int = 3,
        turn_timeout_seconds: int = DEFAULT_TURN_TIMEOUT_SECONDS,
        approval_policy: str = "deny",
        enabled: bool = True,
        by: str,
    ) -> dict[str, Any]:
        """Record that an agent may be started by the dispatcher, and how.
        Enrolling is a human act (ADR 0006): nothing on the bus can add a
        worker, because that is the decision to let a machine start turns."""
        _check_id(agent_id, "agent id", self._redactor)
        _check_enum(provider, PROVIDERS, "provider")
        by = self.redact(_check_text(by, "by", 128))
        if not isinstance(command, (list, tuple)) or not command:
            raise ValidationError("command must be a non-empty array of arguments")
        if len(command) > MAX_WORKER_COMMAND:
            raise ValidationError(f"command carries at most {MAX_WORKER_COMMAND} arguments, got {len(command)}")
        argv = [_check_text(part, "command argument", 1024) for part in command]
        for part in argv:
            leaked = self._redactor.scan(part)
            if leaked:
                # A command is executed verbatim, so it cannot be scrubbed
                # without changing what runs; it is refused instead.
                raise UnsafeReference(f"worker command carries a secret-shaped value ({', '.join(sorted(set(leaked)))}); pass it through the environment instead")
        taken = reserved_flags_in(provider, argv)
        if taken:
            # What the turn may do without asking is the human's decision at
            # enrolment, and it is carried by flags the dispatcher sets itself.
            # A command that names one of them could override that decision, so
            # the enrolment is refused rather than quietly disarmed.
            raise ValidationError(
                f"worker command names {', '.join(taken)}, which the dispatcher sets itself for a "
                f"{provider} turn; drop it and choose what the turn may do with approval_policy"
            )
        dangling = dangling_option(provider, argv)
        if dangling:
            raise ValidationError(
                f"worker command ends in {dangling}, an option with no value; it would swallow the flag "
                f"the dispatcher appends after it. Write it as {dangling}=value or give it its value"
            )
        if cwd is not None:
            cwd = _check_path_arg(cwd)
        _check_int(max_attempts, 1, 10, "max_attempts")
        _check_int(turn_timeout_seconds, 10, 7200, "turn_timeout_seconds")
        _check_enum(approval_policy, APPROVAL_POLICIES, "approval_policy")
        if not isinstance(enabled, bool):
            raise ValidationError("enabled must be a boolean")
        with self._tx("enrol_worker"):
            self._require_agent(agent_id)
            now = utcnow()
            self._conn.execute(
                """INSERT INTO workers (agent_id, provider, command, cwd, max_attempts, turn_timeout_seconds, approval_policy, enabled, enrolled_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (agent_id) DO UPDATE SET
                       provider = excluded.provider, command = excluded.command, cwd = excluded.cwd,
                       max_attempts = excluded.max_attempts, turn_timeout_seconds = excluded.turn_timeout_seconds,
                       approval_policy = excluded.approval_policy,
                       enabled = excluded.enabled, enrolled_by = excluded.enrolled_by, updated_at = excluded.updated_at""",
                (agent_id, provider, json.dumps(argv), cwd, max_attempts, turn_timeout_seconds, approval_policy, int(enabled), by, now, now),
            )
            self._event(by, "worker.enrolled", "worker", agent_id, {"provider": provider, "enabled": enabled, "max_attempts": max_attempts, "approval_policy": approval_policy})
        return self.get_worker(agent_id)

    def get_worker(self, agent_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM workers WHERE agent_id = ?", (agent_id,)).fetchone())
        if record is None:
            raise NotFound(f"agent {agent_id!r} is not a managed worker")
        record["command"] = json.loads(record["command"])
        record["enabled"] = bool(record["enabled"])
        return record

    def list_workers(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        clause = " WHERE enabled = 1" if enabled_only else ""
        rows = self._conn.execute(f"SELECT agent_id FROM workers{clause} ORDER BY agent_id").fetchall()
        return [self.get_worker(row["agent_id"]) for row in rows]

    def set_worker_enabled(self, agent_id: str, enabled: bool, *, by: str) -> dict[str, Any]:
        """The user's stop button: a disabled worker keeps its enrolment and
        its queue, and nothing starts it."""
        if not isinstance(enabled, bool):
            raise ValidationError("enabled must be a boolean")
        by = self.redact(_check_text(by, "by", 128))
        with self._tx("set_worker_enabled"):
            cur = self._conn.execute("UPDATE workers SET enabled = ?, updated_at = ? WHERE agent_id = ?", (int(enabled), utcnow(), agent_id))
            if cur.rowcount != 1:
                raise NotFound(f"agent {agent_id!r} is not a managed worker")
            self._event(by, "worker.enabled" if enabled else "worker.disabled", "worker", agent_id, {})
        return self.get_worker(agent_id)

    def remove_worker(self, agent_id: str, *, by: str) -> None:
        by = self.redact(_check_text(by, "by", 128))
        with self._tx("remove_worker"):
            cur = self._conn.execute("DELETE FROM workers WHERE agent_id = ?", (agent_id,))
            if cur.rowcount != 1:
                raise NotFound(f"agent {agent_id!r} is not a managed worker")
            self._event(by, "worker.removed", "worker", agent_id, {})

    # ----------------------------------------------------- managed sessions
    def ensure_session(self, agent_id: str, *, provider: str, ownership: str = "managed", cwd: Optional[str] = None) -> dict[str, Any]:
        """The provider session a managed worker resumes into. One open row per
        agent and ownership: ADR 0001 keeps human sessions out of the
        dispatcher's reach, so the two never share a record."""
        _check_id(agent_id, "agent id", self._redactor)
        _check_enum(provider, PROVIDERS, "provider")
        _check_enum(ownership, OWNERSHIPS, "ownership")
        with self._tx("ensure_session"):
            self._require_agent(agent_id)
            row = self._conn.execute(
                "SELECT id FROM sessions WHERE agent_id = ? AND ownership = ? AND state != 'closed' ORDER BY created_at LIMIT 1",
                (agent_id, ownership),
            ).fetchone()
            if row is not None:
                session_id = str(row["id"])
            else:
                session_id = new_id("ses")
                now = utcnow()
                self._conn.execute(
                    """INSERT INTO sessions (id, agent_id, provider, ownership, cwd, state, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'idle', ?, ?)""",
                    (session_id, agent_id, provider, ownership, cwd, now, now),
                )
                self._event(agent_id, "session.created", "session", session_id, {"ownership": ownership, "provider": provider})
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())
        if record is None:
            raise NotFound(f"session {session_id!r} does not exist")
        return record

    def record_provider_session(self, session_id: str, *, provider_session_id: str, generation: int) -> dict[str, Any]:
        """Keep the provider's own session id (a Codex thread, a Claude
        session) so the next turn resumes instead of starting over. Fenced:
        a run whose generation is stale no longer speaks for this session."""
        _check_id(session_id, "session id", self._redactor)
        provider_session_id = _check_text(provider_session_id, "provider session id", 256)
        with self._tx("record_provider_session"):
            self._fence_session(session_id, generation, action="record_provider_session")
            self._conn.execute(
                "UPDATE sessions SET provider_session_id = ?, state = 'active', updated_at = ? WHERE id = ?",
                (provider_session_id, utcnow(), session_id),
            )
            self._event("dispatcher", "session.recorded", "session", session_id, {"generation": generation})
        return self.get_session(session_id)

    def _fence_session(self, session_id: str, generation: Any, *, action: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise NotFound(f"session {session_id!r} does not exist")
        _check_int(generation, 0, 2**62, "generation")
        if int(row["generation"]) != int(generation):
            raise GenerationFenced(
                f"{action} refused: session {session_id!r} is at generation {row['generation']}, this run holds {generation}"
            )
        return dict(row)

    # ---------------------------------------------------------------- leases
    def _lease_dead(self, row: Any, now: str, alive: Optional[Callable[[Optional[int], Optional[str]], bool]]) -> Optional[str]:
        """Why a lease no longer holds, or None. A lease dies when it expires
        or when the process that took it is gone -- the second test is what
        makes a killed dispatcher recoverable in seconds instead of at the end
        of a TTL nobody is waiting out."""
        if row["expires_at"] <= now:
            return "expired"
        if alive is not None and row["holder_pid"] is not None and not alive(int(row["holder_pid"]), row["holder_started_at"]):
            return "holder gone"
        return None

    def acquire_lease(
        self,
        kind: str,
        resource_id: str,
        *,
        holder: str,
        ttl_seconds: int = LEASE_TTL_SECONDS,
        holder_pid: Optional[int] = None,
        holder_started_at: Optional[str] = None,
        session_id: Optional[str] = None,
        alive: Optional[Callable[[Optional[int], Optional[str]], bool]] = procinfo.alive,
    ) -> dict[str, Any]:
        """Take the one lease on a resource, or refuse. Taking a session lease
        bumps that session's generation, which fences whatever held it before:
        two dispatchers cannot resume one provider session, and the loser finds
        out on its next write rather than by corrupting the first one's run."""
        _check_enum(kind, LEASE_KINDS, "lease kind")
        _check_id(resource_id, "resource id", self._redactor)
        holder = self.redact(_check_text(holder, "holder", 128))
        _check_int(ttl_seconds, 1, 86400, "ttl_seconds")
        if holder_pid is not None:
            _check_int(holder_pid, 1, 2**31, "holder_pid")
        with self._tx("acquire_lease"):
            now = utcnow()
            row = self._conn.execute("SELECT * FROM leases WHERE kind = ? AND resource_id = ?", (kind, resource_id)).fetchone()
            if row is not None:
                dead = self._lease_dead(row, now, alive)
                if dead is None:
                    raise ConflictError(
                        f"lease on {kind} {resource_id!r} is held by {row['holder']!r} until {row['expires_at']}"
                    )
                self._conn.execute("DELETE FROM leases WHERE id = ?", (row["id"],))
                self._event(holder, "lease.reclaimed", "lease", str(row["id"]), {"kind": kind, "resource": resource_id, "was": row["holder"], "reason": dead})
            generation = 0
            if session_id is not None:
                if self._conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is None:
                    raise NotFound(f"session {session_id!r} does not exist")
                self._conn.execute("UPDATE sessions SET generation = generation + 1, updated_at = ? WHERE id = ?", (now, session_id))
                generation = int(self._conn.execute("SELECT generation FROM sessions WHERE id = ?", (session_id,)).fetchone()["generation"])
            lease_id = new_id("lse")
            self._conn.execute(
                """INSERT INTO leases (id, kind, resource_id, holder, generation, expires_at, created_at, holder_pid, holder_started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (lease_id, kind, resource_id, holder, generation, _plus_seconds(now, ttl_seconds), now, holder_pid, holder_started_at),
            )
            self._event(holder, "lease.acquired", "lease", lease_id, {"kind": kind, "resource": resource_id, "generation": generation, "session_id": session_id})
        return self.get_lease(lease_id)

    def renew_lease(
        self,
        lease_id: str,
        *,
        ttl_seconds: int = LEASE_TTL_SECONDS,
        pid: Optional[int] = None,
        process_started_at: Optional[str] = None,
        alive: Callable[[Optional[int], Optional[str]], bool] = procinfo.alive,
    ) -> dict[str, Any]:
        """Extend a lease only while the work it covers is still alive. A
        renewal for a provider that has died is refused and the lease released,
        so a dead worker cannot hold its own session hostage for a TTL."""
        _check_id(lease_id, "lease id", self._redactor)
        _check_int(ttl_seconds, 1, 86400, "ttl_seconds")
        with self._tx("renew_lease"):
            row = self._conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
            if row is None:
                raise NotFound(f"lease {lease_id!r} does not exist")
            now = utcnow()
            if row["expires_at"] <= now:
                raise ConflictError(f"lease {lease_id!r} expired at {row['expires_at']}; acquire a new one")
            gone = pid is not None and not alive(pid, process_started_at)
            if gone:
                # The release has to survive the refusal, so it commits with
                # this transaction and the caller is told afterwards.
                self._conn.execute("DELETE FROM leases WHERE id = ?", (lease_id,))
                self._event(str(row["holder"]), "lease.released", "lease", lease_id, {"reason": "owned process is gone", "pid": pid})
            else:
                self._conn.execute("UPDATE leases SET expires_at = ? WHERE id = ?", (_plus_seconds(now, ttl_seconds), lease_id))
        if gone:
            raise ConflictError(f"lease {lease_id!r} covers process {pid}, which is gone; the lease is released")
        return self.get_lease(lease_id)

    def release_lease(self, lease_id: str, *, by: str, reason: str = "released") -> None:
        _check_id(lease_id, "lease id", self._redactor)
        by = self.redact(_check_text(by, "by", 128))
        with self._tx("release_lease"):
            row = self._conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
            if row is None:
                return
            self._conn.execute("DELETE FROM leases WHERE id = ?", (lease_id,))
            self._event(by, "lease.released", "lease", lease_id, {"kind": row["kind"], "resource": row["resource_id"], "reason": self.redact(_check_text(reason, "reason", 200))})

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone())
        if record is None:
            raise NotFound(f"lease {lease_id!r} does not exist")
        return record

    def lease_on(self, kind: str, resource_id: str) -> Optional[dict[str, Any]]:
        return _row(self._conn.execute("SELECT * FROM leases WHERE kind = ? AND resource_id = ?", (kind, resource_id)).fetchone())

    def list_leases(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM leases ORDER BY created_at").fetchall()
        return [r for r in (_row(x) for x in rows) if r is not None]

    # ------------------------------------------------------------- dispatch
    def _delivery_context(self, delivery_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            """SELECT d.*, m.kind AS message_kind, m.payload AS message_payload, m.correlation_id AS correlation_id
                 FROM deliveries d JOIN messages m ON m.id = d.message_id WHERE d.id = ?""",
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise NotFound(f"delivery {delivery_id!r} does not exist")
        record = dict(row)
        record["task_id"] = None
        try:
            payload = json.loads(record["message_payload"])
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("task_id"), str):
            record["task_id"] = payload["task_id"]
        return record

    def _moot_reason(self, task_id: Optional[str]) -> Optional[str]:
        """Why starting a turn for this delivery would be wasted work. M5's
        stop is honoured here: a task the daemon stopped is never started."""
        if task_id is None:
            return None
        row = self._conn.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return f"task {task_id} does not exist"
        if row["state"] in ("completed", "blocked", "cancelled", "exhausted"):
            return f"task {task_id} is {row['state']}"
        return None

    def delivery_context(self, delivery_id: str) -> dict[str, Any]:
        """The delivery with the message that carries it, the task it names,
        and why (if at all) starting a turn for it would be wasted work."""
        record = self._delivery_context(delivery_id)
        record["moot"] = self._moot_reason(record["task_id"])
        return record

    def set_run_output(self, run_id: str, output_ref: str) -> dict[str, Any]:
        """Point a run at its log. Kept separate from `finish_run` so the file
        is recorded even when the turn ends in a way that skips settlement."""
        _check_id(run_id, "run id", self._redactor)
        output_ref = _check_text(output_ref, "output_ref", MAX_PATH_LENGTH)
        with self._tx("set_run_output"):
            cur = self._conn.execute("UPDATE runs SET output_ref = ? WHERE id = ?", (output_ref, run_id))
            if cur.rowcount != 1:
                raise NotFound(f"run {run_id!r} does not exist")
        return self.get_run(run_id)

    def dispatchable_deliveries(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Queued work addressed to an enabled managed worker, oldest first. A
        failed attempt with tries left is dispatchable again; one that ran out
        of them is not, and neither is anything addressed to a human-owned
        agent, which the dispatcher may never resume."""
        _check_int(limit, 1, 100, "limit")
        rows = self._conn.execute(
            f"""SELECT d.id AS id FROM deliveries d
                  JOIN workers w ON w.agent_id = d.recipient_agent_id AND w.enabled = 1
                 WHERE d.state IN ({', '.join('?' * len(DISPATCHABLE_DELIVERY_STATES))})
                   AND d.attempts < d.max_attempts
                 ORDER BY d.seq LIMIT ?""",
            (*DISPATCHABLE_DELIVERY_STATES, limit),
        ).fetchall()
        out = []
        for row in rows:
            context = self._delivery_context(str(row["id"]))
            context["moot"] = self._moot_reason(context["task_id"])
            out.append(context)
        return out

    def dead_letter_delivery(self, delivery_id: str, *, by: str, reason: str) -> dict[str, Any]:
        """Stop trying. Used for work that is moot and for a permanent failure;
        a retry of a configuration error is a loop with a bill attached."""
        by = self.redact(_check_text(by, "by", 128))
        reason = self.redact(_check_text(reason, "reason", 500))
        with self._tx("dead_letter_delivery"):
            row = self._conn.execute("SELECT state FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
            if row is None:
                raise NotFound(f"delivery {delivery_id!r} does not exist")
            if row["state"] in ("completed", "dead_letter"):
                raise ConflictError(f"delivery {delivery_id!r} is {row['state']}")
            self._conn.execute("UPDATE deliveries SET state = 'dead_letter', updated_at = ? WHERE id = ?", (utcnow(), delivery_id))
            self._event(by, "delivery.dead_letter", "delivery", delivery_id, {"reason": reason, "was": row["state"]})
        return self.get_delivery(delivery_id)

    def _dispatch_locked(self, delivery_id: str, *, agent_id: str, lease_id: str, generation: int, session_id: str, max_attempts: Optional[int], now: str) -> dict[str, Any]:
        """The dispatch decision itself; the caller owns the transaction."""
        self._fence_session(session_id, generation, action="dispatch")
        self._require_live_lease(lease_id, generation)
        context = self._delivery_context(delivery_id)
        if context["recipient_agent_id"] != agent_id:
            raise ConflictError(f"delivery {delivery_id!r} is addressed to {context['recipient_agent_id']!r}, not {agent_id!r}")
        if context["state"] not in DISPATCHABLE_DELIVERY_STATES:
            raise ConflictError(f"delivery {delivery_id!r} is {context['state']}; only queued or retryable_failed work is dispatched")
        moot = self._moot_reason(context["task_id"])
        if moot is not None:
            raise MootWork(f"delivery {delivery_id!r} needs no turn: {moot}")
        attempts = int(context["attempts"]) + 1
        limit = max_attempts if max_attempts is not None else int(context["max_attempts"])
        self._conn.execute(
            "UPDATE deliveries SET state = 'dispatched', attempts = ?, max_attempts = ?, updated_at = ? WHERE id = ?",
            (attempts, limit, now, delivery_id),
        )
        self._event("dispatcher", "delivery.dispatched", "delivery", delivery_id, {"agent_id": agent_id, "attempt": attempts, "max_attempts": limit, "lease_id": lease_id, "generation": generation})
        context["attempts"], context["max_attempts"], context["state"] = attempts, limit, "dispatched"
        return context

    def _start_run_locked(self, context: dict[str, Any], *, agent_id: str, session_id: str, lease_id: str, generation: int, binding_id: Optional[str], output_ref: Optional[str], approval_policy: Optional[str], now: str) -> str:
        """The run row and the processing state; the caller owns the transaction."""
        run_id = new_id("run")
        self._conn.execute(
            """INSERT INTO runs (id, agent_id, session_id, binding_id, lease_id, generation, delivery_id, task_id, attempt, state, output_ref, approval_policy, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)""",
            (run_id, agent_id, session_id, binding_id, lease_id, generation, context["id"], context["task_id"], int(context["attempts"]), output_ref, approval_policy, now),
        )
        self._conn.execute("UPDATE deliveries SET state = 'processing', updated_at = ? WHERE id = ?", (now, context["id"]))
        self._event("dispatcher", "run.started", "run", run_id, {"agent_id": agent_id, "delivery_id": context["id"], "attempt": int(context["attempts"]), "generation": generation})
        return run_id

    def begin_turn(
        self,
        delivery_id: str,
        *,
        agent_id: str,
        lease_id: str,
        generation: int,
        session_id: str,
        binding_id: Optional[str] = None,
        max_attempts: Optional[int] = None,
        output_ref: Optional[str] = None,
        approval_policy: Optional[str] = None,
    ) -> dict[str, Any]:
        """Count the attempt and record the run that covers it, together.

        Review finding: as two calls, a kill (or a lease that expired) between
        them left the delivery `dispatched` with no run -- invisible to
        recovery, which scans runs, and to dispatch, which scans queued work --
        with one attempt silently spent. One transaction removes the window."""
        _check_id(delivery_id, "delivery id", self._redactor)
        _check_id(agent_id, "agent id", self._redactor)
        if max_attempts is not None:
            _check_int(max_attempts, 1, 10, "max_attempts")
        if approval_policy is not None:
            _check_enum(approval_policy, APPROVAL_POLICIES, "approval_policy")
        with self._tx("begin_turn"):
            now = utcnow()
            context = self._dispatch_locked(delivery_id, agent_id=agent_id, lease_id=lease_id, generation=generation,
                                            session_id=session_id, max_attempts=max_attempts, now=now)
            run_id = self._start_run_locked(context, agent_id=agent_id, session_id=session_id, lease_id=lease_id,
                                            generation=generation, binding_id=binding_id, output_ref=output_ref,
                                            approval_policy=approval_policy, now=now)
        return self.get_run(run_id)

    def dispatch_delivery(self, delivery_id: str, *, agent_id: str, lease_id: str, generation: int, session_id: str, max_attempts: Optional[int] = None) -> dict[str, Any]:
        """queued | retryable_failed -> dispatched, under a live lease and the
        current generation. Counting the attempt here, before a provider is
        started, is what makes a killed dispatcher cost one attempt rather than
        none. Dispatchers use `begin_turn`, which does this and the run in one
        transaction."""
        _check_id(delivery_id, "delivery id", self._redactor)
        _check_id(agent_id, "agent id", self._redactor)
        if max_attempts is not None:
            _check_int(max_attempts, 1, 10, "max_attempts")
        with self._tx("dispatch_delivery"):
            self._dispatch_locked(delivery_id, agent_id=agent_id, lease_id=lease_id, generation=generation,
                                  session_id=session_id, max_attempts=max_attempts, now=utcnow())
        return self.get_delivery(delivery_id)

    def _require_live_lease(self, lease_id: str, generation: Any) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        if row is None:
            raise GenerationFenced(f"lease {lease_id!r} is gone; another dispatcher owns this work now")
        if row["expires_at"] <= utcnow():
            raise GenerationFenced(f"lease {lease_id!r} expired at {row['expires_at']}")
        if int(row["generation"]) != int(generation):
            raise GenerationFenced(f"lease {lease_id!r} is at generation {row['generation']}, this run holds {generation}")
        return dict(row)

    def start_run(
        self,
        *,
        agent_id: str,
        delivery_id: str,
        session_id: str,
        lease_id: str,
        generation: int,
        binding_id: Optional[str] = None,
        output_ref: Optional[str] = None,
        approval_policy: Optional[str] = None,
    ) -> dict[str, Any]:
        """dispatched -> processing, with the run that covers it. The run keeps
        the lease and generation it holds, so its later writes can be fenced."""
        _check_id(agent_id, "agent id", self._redactor)
        _check_id(delivery_id, "delivery id", self._redactor)
        with self._tx("start_run"):
            self._fence_session(session_id, generation, action="start_run")
            self._require_live_lease(lease_id, generation)
            context = self._delivery_context(delivery_id)
            if context["state"] != "dispatched":
                raise ConflictError(f"delivery {delivery_id!r} is {context['state']}; only a dispatched delivery starts a run")
            run_id = self._start_run_locked(context, agent_id=agent_id, session_id=session_id, lease_id=lease_id,
                                            generation=generation, binding_id=binding_id, output_ref=output_ref,
                                            approval_policy=approval_policy, now=utcnow())
        return self.get_run(run_id)

    def record_run_process(self, run_id: str, *, pid: int, started_at: Optional[str] = None) -> dict[str, Any]:
        """Remember which process a run started. A dispatcher that is killed
        orphans that process with a live credential, so recovery has to be able
        to name it."""
        _check_id(run_id, "run id", self._redactor)
        _check_int(pid, 1, 2**31, "pid")
        with self._tx("record_run_process"):
            cur = self._conn.execute("UPDATE runs SET provider_pid = ?, provider_started_at = ? WHERE id = ?", (pid, started_at, run_id))
            if cur.rowcount != 1:
                raise NotFound(f"run {run_id!r} does not exist")
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())
        if record is None:
            raise NotFound(f"run {run_id!r} does not exist")
        return record

    def list_runs(self, *, agent_id: Optional[str] = None, state: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        _check_int(limit, 1, 500, "limit")
        clauses, params = ["1 = 1"], []
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(_check_id(agent_id, "agent id", self._redactor))
        if state is not None:
            clauses.append("state = ?")
            params.append(_check_enum(state, RUN_STATES, "state"))
        rows = self._conn.execute(f"SELECT * FROM runs WHERE {' AND '.join(clauses)} ORDER BY seq DESC LIMIT ?", (*params, limit)).fetchall()
        return [r for r in (_row(x) for x in rows) if r is not None]

    def finish_run(
        self,
        run_id: str,
        *,
        exit_state: Optional[str] = None,
        error: Optional[str] = None,
        output_ref: Optional[str] = None,
        permanent: bool = False,
        state: str = "completed",
        fenced: bool = False,
    ) -> dict[str, Any]:
        """End a run and settle its delivery by looking at what the worker
        actually did. The dispatcher never acknowledges or completes a delivery
        itself (ADR 0006): if the worker left it untouched, the attempt failed,
        however cleanly the provider exited."""
        _check_id(run_id, "run id", self._redactor)
        _check_enum(state, ("completed", "failed", "abandoned"), "state")
        if exit_state is not None:
            exit_state = self.redact(_check_text(exit_state, "exit_state", 200))
        if error is not None:
            error = self.redact(_check_text(error, "error", 2000))
        with self._tx("finish_run"):
            run = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise NotFound(f"run {run_id!r} does not exist")
            if run["state"] != "running":
                raise ConflictError(f"run {run_id!r} is {run['state']}")
            if fenced:
                # A dispatcher settling its own turn proves it still owns the
                # session: a run whose lease was reclaimed while it ran must not
                # settle a delivery somebody else is now working.
                self._fence_session(str(run["session_id"]), run["generation"], action="finish_run")
                self._require_live_lease(str(run["lease_id"]), run["generation"])
            now = utcnow()
            context = self._delivery_context(str(run["delivery_id"]))
            worker_moved_it = context["state"] not in RUNNING_DELIVERY_STATES
            outcome = state if state != "completed" else ("completed" if worker_moved_it else "failed")
            delivery_state = context["state"]
            if not worker_moved_it:
                attempts, limit = int(context["attempts"]), int(context["max_attempts"])
                if permanent or attempts >= limit:
                    delivery_state = "dead_letter"
                    reason = error or ("permanent failure" if permanent else f"no progress after {attempts} attempt(s)")
                    self._event("dispatcher", "delivery.dead_letter", "delivery", str(run["delivery_id"]), {"reason": reason, "attempts": attempts, "run_id": run_id})
                else:
                    delivery_state = "retryable_failed"
                    self._event("dispatcher", "delivery.retryable_failed", "delivery", str(run["delivery_id"]), {"attempts": attempts, "max_attempts": limit, "run_id": run_id})
                self._conn.execute("UPDATE deliveries SET state = ?, updated_at = ? WHERE id = ?", (delivery_state, now, str(run["delivery_id"])))
            self._conn.execute(
                "UPDATE runs SET state = ?, exit_state = ?, error = ?, output_ref = COALESCE(?, output_ref), ended_at = ? WHERE id = ?",
                (outcome, exit_state, error, output_ref, now, run_id),
            )
            self._event("dispatcher", "run.finished", "run", run_id, {
                "agent_id": run["agent_id"], "delivery_id": run["delivery_id"], "outcome": outcome,
                "delivery_state": delivery_state, "exit_state": exit_state, "worker_moved_it": worker_moved_it,
            })
        record = self.get_run(run_id)
        record["delivery_state"] = delivery_state
        return record

    def recover_deliveries(self, *, by: str = "dispatcher") -> list[dict[str, Any]]:
        """Settle deliveries left mid-turn that no live run covers.

        Review finding: a delivery could sit in `dispatched` or `processing`
        with no run row -- recovery scans runs, dispatch scans queued work, so
        nothing could see it and an attempt was spent for nothing. This sweep
        is what makes "exactly one outcome" true however the turn was lost."""
        stranded = self._conn.execute(
            f"""SELECT d.id AS id FROM deliveries d
                 WHERE d.state IN ({', '.join('?' * len(RUNNING_DELIVERY_STATES))})
                   AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.delivery_id = d.id AND r.state = 'running')
                 ORDER BY d.seq""",
            RUNNING_DELIVERY_STATES,
        ).fetchall()
        settled = []
        for row in stranded:
            delivery_id = str(row["id"])
            with self._tx("recover_delivery"):
                context = self._delivery_context(delivery_id)
                if context["state"] not in RUNNING_DELIVERY_STATES:
                    continue
                attempts, limit = int(context["attempts"]), int(context["max_attempts"])
                now = utcnow()
                if attempts >= limit:
                    state, kind = "dead_letter", "delivery.dead_letter"
                else:
                    state, kind = "retryable_failed", "delivery.retryable_failed"
                self._conn.execute("UPDATE deliveries SET state = ?, updated_at = ? WHERE id = ?", (state, now, delivery_id))
                self._event(by, kind, "delivery", delivery_id, {
                    "reason": "the turn that was working this delivery left no live run",
                    "attempts": attempts, "max_attempts": limit, "was": context["state"],
                })
            settled.append(self.get_delivery(delivery_id))
        return settled

    def recover_runs(self, *, alive: Optional[Callable[[Optional[int], Optional[str]], bool]] = procinfo.alive, by: str = "dispatcher") -> list[dict[str, Any]]:
        """Settle runs whose dispatcher is gone. Called at startup: a kill at
        any point leaves at most one attempt to account for, and the delivery
        still reaches exactly one outcome."""
        recovered = []
        for run in self.list_runs(state="running", limit=500):
            lease = _row(self._conn.execute("SELECT * FROM leases WHERE id = ?", (run["lease_id"],)).fetchone()) if run["lease_id"] else None
            now = utcnow()
            reason = "lease is gone" if lease is None else self._lease_dead(lease, now, alive)
            if reason is None:
                continue
            if lease is not None:
                self.release_lease(str(lease["id"]), by=by, reason=f"run {run['id']} abandoned: {reason}")
            if run["binding_id"]:
                # The orphaned provider still holds a working credential until
                # this happens; revoking it is the first thing recovery does.
                try:
                    self.revoke_binding(str(run["binding_id"]), by=by, reason=f"run {run['id']} abandoned")
                except StoreError:
                    pass
            recovered.append(self.finish_run(str(run["id"]), state="abandoned", exit_state="abandoned", error=f"the dispatcher that owned this run is gone ({reason})"))
        return recovered

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
            # ADR 0004: an agent with no live binding is unverified, and says
            # so on its own line. `--allow-unattributed` decides whether such
            # a session may act; it never changes this label.
            binding = self.binding_of(agent["id"])
            agents.append({
                **agent, "queued_deliveries": queued, "claimed_tasks": claimed, "worktree": worktree,
                "verified": binding is not None,
                "binding": None if binding is None else {
                    "id": binding["id"], "tty": binding["tty"], "pid": binding["pid"],
                    "provider": binding["provider"], "ownership": binding["ownership"],
                    "generation": binding["generation"], "expires_at": binding["expires_at"],
                },
            })
        tasks = {
            state: int(self._conn.execute("SELECT COUNT(*) FROM tasks WHERE state = ?", (state,)).fetchone()[0])
            for state in TASK_STATES
        }
        open_tasks = self.list_tasks(state="open", limit=50)["items"]
        # M5: a task the daemon stopped on a budget is not open, not claimed,
        # and nobody is coming back to it -- so it says so on the status view
        # rather than disappearing from every list a human reads.
        stopped = [
            {"id": t["id"], "title": t["title"], "dimension": (t["result"] or {}).get("dimension") if isinstance(t["result"], dict) else None}
            for t in self.list_tasks(state="exhausted", limit=20)["items"]
        ]
        pending = self.pending_approvals()
        return {
            "agents": agents,
            "tasks": tasks,
            "open_tasks": [{"id": t["id"], "title": t["title"], "assigned_to": t["assigned_agent_id"], "priority": t["priority"], "requires_worktree": t["requires_worktree"]} for t in open_tasks],
            "stopped_tasks": stopped,
            # M6: who the machine may start, and what it is running now. A
            # managed worker is the one thing on this view the user did not
            # start by hand, so it says so on its own line.
            "workers": [
                {"agent_id": w["agent_id"], "provider": w["provider"], "enabled": w["enabled"],
                 "max_attempts": w["max_attempts"]}
                for w in self.list_workers()
            ],
            "running_runs": [
                {"id": r["id"], "agent_id": r["agent_id"], "attempt": r["attempt"], "started_at": r["started_at"]}
                for r in self.list_runs(state="running", limit=20)
            ],
            "queued_deliveries": sum(a["queued_deliveries"] for a in agents),
            "approvals_pending": len(pending),
            "pending_approvals": pending,
            "unverified_agents": [a["id"] for a in agents if not a["verified"]],
            "events": int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
        }

    def counts(self) -> dict[str, int]:
        """Row counts per table; the crash suite compares these before and
        after a kill."""
        tables = ("agents", "sessions", "messages", "deliveries", "tasks", "task_deps", "runs", "leases", "artifacts", "events", "idempotency", "worktrees", "approvals", "bindings")
        return {t: int(self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in tables}
