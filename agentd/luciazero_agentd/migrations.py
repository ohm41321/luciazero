"""Versioned schema for the Agent Bus store.

Each entry is ``(version, sql)``. ``Store.migrate`` applies every entry above
the database's ``PRAGMA user_version`` in order, one transaction per version.
Never edit a shipped entry; append a new one.

Reserved-only structures (no logic behind them until the milestone named in
the comment): ``sessions`` (provider session identity for resume, M5/M6 --
terminal bindings live in their own table because SQLite cannot widen its
``state`` CHECK by ALTER), ``deliveries.attempts``,
``deliveries.max_attempts`` (M6).
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

# M5: the task graph, budgets and artifact provenance. SQLite cannot widen the
# ``state`` CHECK of a shipped table by ALTER, so ``tasks`` is rebuilt by the
# documented copy-drop-rename procedure. ``Store.migrate`` runs every migration
# with ``foreign_keys`` off and a ``foreign_key_check`` before the commit, so a
# rebuild that left a dangling reference would fail here rather than ship.
SCHEMA_V4 = """
CREATE TABLE tasks_v4 (
    seq                  INTEGER PRIMARY KEY AUTOINCREMENT,
    id                   TEXT NOT NULL UNIQUE,
    title                TEXT NOT NULL,
    payload              TEXT NOT NULL DEFAULT '{}',
    created_by_agent_id  TEXT NOT NULL REFERENCES agents(id),
    assigned_agent_id    TEXT REFERENCES agents(id),
    priority             INTEGER NOT NULL DEFAULT 0,
    depends_on           TEXT NOT NULL DEFAULT '[]',
    budget               TEXT NOT NULL DEFAULT '{}',
    spent                TEXT NOT NULL DEFAULT '{}',
    deadline_at          TEXT,
    state                TEXT NOT NULL CHECK (state IN (
                             'open', 'waiting', 'claimed', 'completed', 'blocked', 'cancelled', 'exhausted')),
    result               TEXT,
    version              INTEGER NOT NULL DEFAULT 1,
    requires_worktree    INTEGER NOT NULL DEFAULT 0 CHECK (requires_worktree IN (0, 1)),
    claimed_at           TEXT,
    completed_at         TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

INSERT INTO tasks_v4 (seq, id, title, payload, created_by_agent_id, assigned_agent_id, priority,
                      depends_on, state, result, version, requires_worktree,
                      claimed_at, completed_at, created_at, updated_at)
        SELECT seq, id, title, payload, created_by_agent_id, assigned_agent_id, priority,
               depends_on, state, result, version, requires_worktree,
               claimed_at, completed_at, created_at, updated_at
          FROM tasks;

-- AUTOINCREMENT high-water mark: copying rows sets the new table's mark from
-- the copied seq values, so a mark standing above the surviving rows (a task
-- deleted before the migration) would be forgotten and handed out again. seq
-- is the paging cursor, so a reused one makes `after` skip or repeat a task.
DELETE FROM sqlite_sequence WHERE name = 'tasks_v4';

INSERT INTO sqlite_sequence (name, seq) SELECT 'tasks_v4', seq FROM sqlite_sequence WHERE name = 'tasks';

DROP TABLE tasks;

-- Renaming the new table into place is the safe direction: SQLite rewrites
-- references TO the renamed name, and nothing references `tasks_v4`, so
-- `artifacts.task_id` and `approvals.task_id` keep pointing at `tasks`.
ALTER TABLE tasks_v4 RENAME TO tasks;

CREATE INDEX tasks_state ON tasks (state, priority DESC, seq);
CREATE INDEX tasks_deadline ON tasks (deadline_at) WHERE deadline_at IS NOT NULL;

-- The edge table is the graph the daemon walks; ``tasks.depends_on`` keeps the
-- same list on the task record for readers. Both are written together at
-- creation and never edited, because an edge set that could change after the
-- fact could introduce a cycle no creation-time check ever saw.
CREATE TABLE task_deps (
    task_id        TEXT NOT NULL REFERENCES tasks(id),
    depends_on_id  TEXT NOT NULL REFERENCES tasks(id),
    created_at     TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on_id)
);
CREATE INDEX task_deps_reverse ON task_deps (depends_on_id);

-- ADR 0004 again: an artifact record says how much its producer's identity was
-- worth when it was published, so provenance survives without event archaeology.
ALTER TABLE artifacts ADD COLUMN trust TEXT NOT NULL DEFAULT 'asserted';
"""


# M6: managed dispatch. `workers` says which agents the dispatcher may start
# and how; `runs` is rebuilt (it was reserved and empty since M1) to record one
# provider turn with the lease and generation it held. `leases` and
# `sessions.generation`, also reserved since M1, come into use unchanged.
SCHEMA_V5 = """
CREATE TABLE workers (
    agent_id              TEXT PRIMARY KEY REFERENCES agents(id),
    provider              TEXT NOT NULL CHECK (provider IN ('codex', 'claude', 'other')),
    command               TEXT NOT NULL,
    cwd                   TEXT,
    max_attempts          INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    turn_timeout_seconds  INTEGER NOT NULL DEFAULT 600 CHECK (turn_timeout_seconds BETWEEN 10 AND 7200),
    enabled               INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    enrolled_by           TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

DROP TABLE runs;

CREATE TABLE runs (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    id           TEXT NOT NULL UNIQUE,
    agent_id     TEXT NOT NULL REFERENCES agents(id),
    session_id   TEXT REFERENCES sessions(id),
    binding_id   TEXT REFERENCES bindings(id),
    lease_id     TEXT,
    generation   INTEGER NOT NULL DEFAULT 0,
    delivery_id  TEXT REFERENCES deliveries(id),
    task_id      TEXT REFERENCES tasks(id),
    attempt      INTEGER NOT NULL DEFAULT 1,
    state        TEXT NOT NULL CHECK (state IN ('running', 'completed', 'failed', 'abandoned')),
    exit_state   TEXT,
    error        TEXT,
    output_ref   TEXT,
    -- The provider process this run started: a killed dispatcher orphans it,
    -- and recovery needs to know what to revoke and what to stop.
    provider_pid         INTEGER,
    provider_started_at  TEXT,
    started_at   TEXT NOT NULL,
    ended_at     TEXT
);
CREATE INDEX runs_agent ON runs (agent_id, seq);
-- Partial index on the only rows the dispatcher scans on every pass.
CREATE INDEX runs_live ON runs (state, seq) WHERE state = 'running';
CREATE INDEX runs_delivery ON runs (delivery_id);

-- A lease is dead when it expires OR when the process holding it is gone. The
-- second test is what lets a killed dispatcher be recovered from in seconds
-- instead of at the end of a TTL nobody is waiting out.
ALTER TABLE leases ADD COLUMN holder_pid INTEGER;

ALTER TABLE leases ADD COLUMN holder_started_at TEXT;
"""


# M6 slice B: how far a managed turn may go on the user's machine. The Codex
# adapter runs `approvalPolicy: "on-request"` (ADR 0001 null result 3: "never"
# fails a model-selected MCP tool call before it reaches the bus), so somebody
# has to answer those requests. The answer is the user's, recorded per worker
# when they enrol it, and the default is the one that can do the least.
SCHEMA_V6 = """
ALTER TABLE workers ADD COLUMN approval_policy TEXT NOT NULL DEFAULT 'deny'
    CHECK (approval_policy IN ('deny', 'workspace', 'accept'));
"""


SCHEMA_V7 = """
-- What the run was allowed to do without asking, as it stood when the turn
-- started. The worker row can be re-enrolled at any time; an audit asking what
-- governed *this* turn must not read a policy chosen after it ended.
ALTER TABLE runs ADD COLUMN approval_policy TEXT;
"""


# M7c: how a session that was started as an ordinary `claude` or `codex` gets
# an identity. An MCP client sends its headers once, at connect time, so a
# session that opened with the shared token can never present a credential
# afterwards -- which is why binding a terminal used to mean starting the
# provider through `run`. The request is pinned to the MCP session that opened
# it before the request id exists, so the id is a reference and not a bearer
# token: stealing it buys nothing, because approving it binds the session that
# asked, never the one that presents it.
#
# The session id itself is stored as a sha256, like every other credential
# here: `claim list` shows the request to a human, and must not hand its
# reader the key to that session.
#
# The approval code is what makes the second phase a boundary rather than a
# speed bump. Process ancestry cannot be one: both CLIs can run shell
# commands, and one `( cmd & )` orphans the process so no ancestry check sees
# the session it came from, while `script` supplies the pty that satisfies an
# isatty gate. So the code is emitted on the daemon's own console -- the one
# place a process on this machine cannot read without being that process --
# and never through MCP, never into the store in the clear, never into a file
# the daemon writes.
SCHEMA_V8 = """
CREATE TABLE claim_requests (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    id              TEXT NOT NULL UNIQUE,
    agent_id        TEXT NOT NULL,
    session_hash    TEXT NOT NULL,
    provider        TEXT NOT NULL CHECK (provider IN ('codex', 'claude', 'other')),
    client          TEXT,
    state           TEXT NOT NULL CHECK (state IN ('open', 'approved', 'denied', 'superseded', 'expired')),
    code_hash       TEXT NOT NULL,
    code_attempts   INTEGER NOT NULL DEFAULT 0,
    binding_id      TEXT REFERENCES bindings(id),
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    decided_at      TEXT,
    decided_by      TEXT,
    decided_tty     TEXT,
    decided_pid     INTEGER
);
-- One request in flight per session: a second ask supersedes the first rather
-- than leaving two ids a human could approve for two different agents.
CREATE UNIQUE INDEX claim_requests_one_open_per_session
    ON claim_requests (session_hash) WHERE state = 'open';
CREATE INDEX claim_requests_live ON claim_requests (state, expires_at);
"""


SCHEMA_V9 = """
-- A binding renews itself while its terminal is alive, so the window it was
-- created with has to survive the first renewal: without it a session started
-- with a deliberately short `--ttl` would silently inherit the default one.
ALTER TABLE bindings ADD COLUMN ttl_seconds INTEGER NOT NULL DEFAULT 43200;
"""


MIGRATIONS: list[tuple[int, str]] = [
    (1, SCHEMA_V1),
    (2, SCHEMA_V2),
    (3, SCHEMA_V3),
    (4, SCHEMA_V4),
    (5, SCHEMA_V5),
    (6, SCHEMA_V6),
    (7, SCHEMA_V7),
    (8, SCHEMA_V8),
    (9, SCHEMA_V9),
]

LATEST_VERSION = MIGRATIONS[-1][0]
