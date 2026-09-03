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
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence

from .migrations import LATEST_VERSION, MIGRATIONS

MESSAGE_KINDS = ("task", "question", "finding", "decision", "artifact", "result")
ARTIFACT_KINDS = ("commit", "patch", "report", "log", "relay")
PROVIDERS = ("codex", "claude", "other")
TASK_OUTCOMES = ("completed", "blocked")
MAX_PAYLOAD_BYTES = 64 * 1024
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


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _check_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValidationError(
            f"{what} must be 1-{MAX_ID_LENGTH} chars of [A-Za-z0-9._:@+-], got {value!r}"
        )
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
    return record


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

    def __init__(self, connection: sqlite3.Connection, path: str, crash_hook: Optional[CrashHook] = None):
        self._conn = connection
        self.path = path
        self._crash_hook: CrashHook = crash_hook or (lambda point: None)

    # ------------------------------------------------------------------ setup
    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        crash_hook: Optional[CrashHook] = None,
    ) -> "Store":
        _check_int(busy_timeout_ms, 1, 60_000, "busy_timeout_ms")
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
        cls._ensure_wal(conn)
        return cls(conn, str(path), crash_hook)

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
        self._conn.execute(
            "INSERT INTO events (at, actor, kind, entity_type, entity_id, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (utcnow(), actor, kind, entity_type, entity_id, json.dumps(payload or {}, sort_keys=True)),
        )

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
        capabilities: Sequence[str] = (),
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        _check_id(agent_id, "agent id")
        _check_enum(provider, PROVIDERS, "provider")
        _check_text(role, "role", MAX_ID_LENGTH)
        _check_int(ttl_seconds, 1, 86_400, "ttl_seconds")
        if isinstance(capabilities, (str, bytes)):
            raise ValidationError("capabilities must be a sequence of non-empty strings")
        for capability in capabilities:
            _check_text(capability, "capability", 64)
        caps = json.dumps(sorted(set(capabilities)))
        now = utcnow()
        with self._tx("register_agent"):
            self._conn.execute(
                """INSERT INTO agents (id, provider, role, capabilities, status, ttl_seconds, last_seen_at, created_at)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET provider = excluded.provider, role = excluded.role,
                       capabilities = excluded.capabilities, status = 'active',
                       ttl_seconds = excluded.ttl_seconds, last_seen_at = excluded.last_seen_at""",
                (agent_id, provider, role, caps, ttl_seconds, now, now),
            )
            self._event(agent_id, "agent.registered", "agent", agent_id, {"provider": provider, "role": role})
        return self.get_agent(agent_id)

    def heartbeat(self, agent_id: str) -> dict[str, Any]:
        _check_id(agent_id, "agent id")
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
        _check_id(sender, "sender")
        _check_id(recipient, "recipient")
        _check_enum(kind, MESSAGE_KINDS, "kind")
        encoded = _check_json_object(payload, "payload")
        if idempotency_key is not None:
            _check_id(idempotency_key, "idempotency key")
        if reply_to is not None:
            _check_id(reply_to, "reply_to")
        if correlation_id is not None:
            _check_id(correlation_id, "correlation id")
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
                self._event(sender, "message.sent", "message", message_id, {"recipient": recipient, "kind": kind, "delivery_id": delivery_id})
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
        _check_id(agent_id, "agent id")
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
        _check_id(delivery_id, "delivery id")
        _check_id(agent_id, "agent id")
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
    ) -> dict[str, Any]:
        _check_id(created_by, "created_by")
        if assigned_to is not None:
            _check_id(assigned_to, "assigned_to")
        _check_text(title, "title", 500)
        _check_int(priority, -100, 100, "priority")
        encoded = _check_json_object(payload or {}, "payload")
        if idempotency_key is not None:
            _check_id(idempotency_key, "idempotency key")
        fingerprint = _fingerprint("create_task", title=title, created_by=created_by, payload=encoded, assigned_to=assigned_to, priority=priority)
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
                    """INSERT INTO tasks (id, title, payload, created_by_agent_id, assigned_agent_id, priority, state, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
                    (task_id, title, encoded, created_by, assigned_to, priority, now, now),
                )
                self._event(created_by, "task.created", "task", task_id, {"title": title, "assigned_to": assigned_to})
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
            params.append(_check_id(assigned_to, "assigned_to"))
        rows = self._conn.execute(
            f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY seq LIMIT ?", (*params, limit + 1)
        ).fetchall()
        items = [r for r in (_row(x) for x in rows[:limit]) if r is not None]
        return {"items": items, "next_after": items[-1]["seq"] if items else after, "has_more": len(rows) > limit}

    def claim_task(self, task_id: str, agent_id: str) -> dict[str, Any]:
        """open -> claimed. Exactly one concurrent claimer wins; the others
        get ``ConflictError``. Pre-assigned tasks accept only their assignee."""
        _check_id(task_id, "task id")
        _check_id(agent_id, "agent id")
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
            self._event(agent_id, "task.claimed", "task", task_id, {})
        return self.get_task(task_id)

    def complete_task(self, task_id: str, agent_id: str, *, result: Optional[dict[str, Any]] = None, outcome: str = "completed") -> dict[str, Any]:
        """claimed -> completed | blocked, only by the agent holding the claim."""
        _check_id(task_id, "task id")
        _check_id(agent_id, "agent id")
        _check_enum(outcome, TASK_OUTCOMES, "outcome")
        encoded = _check_json_object(result or {}, "result")
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
        _check_enum(kind, ARTIFACT_KINDS, "artifact kind")
        _check_id(produced_by, "produced_by")
        _check_text(ref, "ref", 2048)
        if sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValidationError("sha256 must be 64 lowercase hex chars")
        if task_id is not None:
            _check_id(task_id, "task id")
        if idempotency_key is not None:
            _check_id(idempotency_key, "idempotency key")
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
                    (artifact_id, task_id, kind, ref, sha256, produced_by, utcnow()),
                )
                self._event(produced_by, "artifact.published", "artifact", artifact_id, {"kind": kind, "task_id": task_id})
                self._remember(produced_by, idempotency_key, "publish_artifact", fingerprint, "artifact", artifact_id)
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        record = _row(self._conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone())
        if record is None:
            raise NotFound(f"artifact {artifact_id!r} does not exist")
        return record

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
            agents.append({**agent, "queued_deliveries": queued, "claimed_tasks": claimed})
        tasks = {
            state: int(self._conn.execute("SELECT COUNT(*) FROM tasks WHERE state = ?", (state,)).fetchone()[0])
            for state in ("open", "claimed", "completed", "blocked", "cancelled")
        }
        open_tasks = self.list_tasks(state="open", limit=50)["items"]
        return {
            "agents": agents,
            "tasks": tasks,
            "open_tasks": [{"id": t["id"], "title": t["title"], "assigned_to": t["assigned_agent_id"], "priority": t["priority"]} for t in open_tasks],
            "queued_deliveries": sum(a["queued_deliveries"] for a in agents),
            "events": int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
        }

    def counts(self) -> dict[str, int]:
        """Row counts per table; the crash suite compares these before and
        after a kill."""
        tables = ("agents", "sessions", "messages", "deliveries", "tasks", "runs", "leases", "artifacts", "events", "idempotency")
        return {t: int(self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in tables}
