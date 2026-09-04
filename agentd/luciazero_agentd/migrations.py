"""Versioned schema for the Agent Bus store.

Each entry is ``(version, sql)``. ``Store.migrate`` applies every entry above
the database's ``PRAGMA user_version`` in order, one transaction per version.
Never edit a shipped entry; append a new one.

Reserved-only structures (no logic behind them until the milestone named in
the comment): ``sessions`` (provider session identity for resume, M5/M6 --
terminal bindings live in their own table because SQLite cannot widen its
``state`` CHECK by ALTER), ``deliveries.attempts``,
``deliveries.max_attempts``, ``tasks.depends_on``, ``runs``, ``leases``.
"""

from __future__ import annotations

SCHEMA_V1 = """
CREATE TABLE agents (
    id            TEXT PRIMARY KEY,
    provider      TEXT NOT NULL CHECK (provider IN ('codex', 'claude', 'other')),
    role          TEXT NOT NULL,
    capabilities  TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    ttl_seconds   INTEGER NOT NULL DEFAULT 300 CHECK (ttl_seconds > 0),
    last_seen_at  TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE sessions (
    id                   TEXT PRIMARY KEY,
    agent_id             TEXT NOT NULL REFERENCES agents(id),
    provider             TEXT NOT NULL,
    provider_session_id  TEXT,
    generation           INTEGER NOT NULL DEFAULT 0,   -- reserved: fenced in M6
    ownership            TEXT NOT NULL CHECK (ownership IN ('human', 'managed')),
    cwd                  TEXT,
    worktree             TEXT,
    state                TEXT NOT NULL DEFAULT 'idle' CHECK (state IN ('idle', 'active', 'closed')),
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE messages (
    seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
    id                  TEXT NOT NULL UNIQUE,
    sender_agent_id     TEXT NOT NULL REFERENCES agents(id),
    recipient_agent_id  TEXT NOT NULL REFERENCES agents(id),
    kind                TEXT NOT NULL CHECK (kind IN ('task', 'question', 'finding', 'decision', 'artifact', 'result')),
    payload             TEXT NOT NULL,
    correlation_id      TEXT NOT NULL,
    reply_to            TEXT REFERENCES messages(id),
    hop_count           INTEGER NOT NULL DEFAULT 0 CHECK (hop_count >= 0),
    created_at          TEXT NOT NULL
);
CREATE TRIGGER messages_immutable_update BEFORE UPDATE ON messages
BEGIN SELECT RAISE(ABORT, 'messages are immutable'); END;
CREATE TRIGGER messages_immutable_delete BEFORE DELETE ON messages
BEGIN SELECT RAISE(ABORT, 'messages are immutable'); END;

CREATE TABLE deliveries (
    seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
    id                  TEXT NOT NULL UNIQUE,
    message_id          TEXT NOT NULL REFERENCES messages(id),
    recipient_agent_id  TEXT NOT NULL REFERENCES agents(id),
    state               TEXT NOT NULL CHECK (state IN (
                            'queued', 'claimed', 'dispatched', 'processing',
                            'acknowledged', 'completed', 'retryable_failed', 'dead_letter')),
    attempts            INTEGER NOT NULL DEFAULT 0,    -- reserved: M6
    max_attempts        INTEGER NOT NULL DEFAULT 3,    -- reserved: M6
    acknowledged_by     TEXT REFERENCES agents(id),
    acknowledged_at     TEXT,
    completed_at        TEXT,
    updated_at          TEXT NOT NULL
);
CREATE INDEX deliveries_inbox ON deliveries (recipient_agent_id, state, seq);

CREATE TABLE tasks (
    seq                  INTEGER PRIMARY KEY AUTOINCREMENT,
    id                   TEXT NOT NULL UNIQUE,
    title                TEXT NOT NULL,
    payload              TEXT NOT NULL DEFAULT '{}',
    created_by_agent_id  TEXT NOT NULL REFERENCES agents(id),
    assigned_agent_id    TEXT REFERENCES agents(id),
    priority             INTEGER NOT NULL DEFAULT 0,
    depends_on           TEXT NOT NULL DEFAULT '[]',   -- reserved: M5
    state                TEXT NOT NULL CHECK (state IN ('open', 'claimed', 'completed', 'blocked', 'cancelled')),
    result               TEXT,
    version              INTEGER NOT NULL DEFAULT 1,
    claimed_at           TEXT,
    completed_at         TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX tasks_state ON tasks (state, priority DESC, seq);

CREATE TABLE runs (                                   -- reserved: M6
    id          TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES sessions(id),
    lease_id    TEXT,
    started_at  TEXT,
    ended_at    TEXT,
    exit_state  TEXT,
    output_ref  TEXT
);

CREATE TABLE leases (                                 -- reserved: M6
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('session', 'task')),
    resource_id  TEXT NOT NULL,
    holder       TEXT NOT NULL,
    generation   INTEGER NOT NULL DEFAULT 0,
    expires_at   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE (kind, resource_id)
);

CREATE TABLE artifacts (
    seq                   INTEGER PRIMARY KEY AUTOINCREMENT,
    id                    TEXT NOT NULL UNIQUE,
    task_id               TEXT REFERENCES tasks(id),
    kind                  TEXT NOT NULL CHECK (kind IN ('commit', 'patch', 'report', 'log', 'relay')),
    ref                   TEXT NOT NULL,
    sha256                TEXT,
    produced_by_agent_id  TEXT NOT NULL REFERENCES agents(id),
    created_at            TEXT NOT NULL
);

CREATE TABLE events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT NOT NULL,
    actor        TEXT NOT NULL,
    kind         TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}'
);
CREATE TRIGGER events_append_only_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_append_only_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TABLE idempotency (
    actor_agent_id  TEXT NOT NULL REFERENCES agents(id),
    key             TEXT NOT NULL,
    operation       TEXT NOT NULL,
    fingerprint     TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (actor_agent_id, key)
);
"""

# M3: one worktree per writing worker, and human approvals that no MCP tool
# can create. The nonce is stored only as a hash; the plain nonce is shown
# once on the approver's terminal and consumed once by the claim holder.
SCHEMA_V2 = """
ALTER TABLE tasks ADD COLUMN requires_worktree INTEGER NOT NULL DEFAULT 0 CHECK (requires_worktree IN (0, 1));

CREATE TABLE worktrees (
    id            TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL UNIQUE REFERENCES agents(id),
    repo_id       TEXT NOT NULL,
    path          TEXT NOT NULL UNIQUE,
    branch        TEXT NOT NULL,
    base_oid      TEXT NOT NULL,
    head_oid      TEXT NOT NULL,
    dirty         INTEGER NOT NULL CHECK (dirty IN (0, 1)),
    recorded_at   TEXT NOT NULL,
    verified_at   TEXT NOT NULL
);

CREATE TABLE approvals (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL REFERENCES tasks(id),
    operation    TEXT NOT NULL CHECK (operation IN (
                     'delete', 'deploy', 'production', 'spend', 'force_push', 'public_contract', 'scope_expansion')),
    nonce_hash   TEXT NOT NULL UNIQUE,
    granted_by   TEXT NOT NULL,
    granted_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    consumed_by  TEXT REFERENCES agents(id),
    consumed_at  TEXT
);
CREATE INDEX approvals_task ON approvals (task_id, operation);
"""

SCHEMA_V3 = """
CREATE TABLE bindings (
    id                  TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    credential_hash     TEXT NOT NULL UNIQUE,
    provider            TEXT NOT NULL CHECK (provider IN ('codex', 'claude', 'other')),
    ownership           TEXT NOT NULL CHECK (ownership IN ('human', 'managed')),
    tty                 TEXT,
    pid                 INTEGER,
    process_started_at  TEXT,
    cwd                 TEXT,
    generation          INTEGER NOT NULL DEFAULT 0,
    state               TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'revoked', 'stale')),
    bound_by            TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    expires_at          TEXT NOT NULL,
    ended_at            TEXT,
    ended_reason        TEXT
);
-- One live binding per agent, and one per terminal: the user cannot end up
-- with two windows answering as the same role, or one window as two roles.
CREATE UNIQUE INDEX bindings_one_live_per_agent ON bindings (agent_id) WHERE state = 'active';
CREATE UNIQUE INDEX bindings_one_live_per_tty ON bindings (tty) WHERE state = 'active' AND tty IS NOT NULL;
CREATE INDEX bindings_live ON bindings (state, expires_at);
"""

MIGRATIONS: list[tuple[int, str]] = [
    (1, SCHEMA_V1),
    (2, SCHEMA_V2),
    (3, SCHEMA_V3),
]

LATEST_VERSION = MIGRATIONS[-1][0]
