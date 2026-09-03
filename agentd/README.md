# luciazero-agentd

Companion package to [luciazero](../README.md): the local daemon behind the
Agent Bus. Python 3.10+ standard library only, no pip dependencies. Not
published; the release decision is milestone M8 in
[the roadmap](../docs/agent-bus-roadmap.md).

Current milestone: **M3, Git isolation and safety.** The package owns the
SQLite schema (`luciazero_agentd/migrations.py`), the store operations the
pull beta uses (`luciazero_agentd/store.py`): agent registration, message
send and inbox, delivery acknowledgement, task create/claim/complete,
artifact publish, an append-only event log, and idempotent replays; the MCP
Streamable HTTP server that exposes them as fifteen tools on loopback behind
a bearer token (`luciazero_agentd/server.py`); and the M3 safety rules: one
git worktree per writing worker whose identity the daemon reads itself
(`luciazero_agentd/gitinfo.py`), single-use human approval nonces that no
MCP tool can create, worktree-contained artifact paths, and secret
redaction on everything stored or returned (`luciazero_agentd/redact.py`).

The daemon CLI (run from this directory, or with `PYTHONPATH=agentd` from
the repository root):

```bash
python3 -m luciazero_agentd serve           # foreground on 127.0.0.1:8765; writes endpoint.json
python3 -m luciazero_agentd status [--json] # read-only queue summary; never mints a token
python3 -m luciazero_agentd client-config   # `codex mcp add` / `claude mcp add` commands
python3 -m luciazero_agentd approve TASK OP  # interactive only: one single-use approval nonce
```

State lives under `${LUCIAZERO_AGENT_BUS_HOME:-~/.luciazero/agent-bus}`
(directory `0700`, token `0600`). Tests and gates always point that variable
at a temporary directory and never touch the developer's real state.

Verify:

```bash
./test.sh --agent-bus-store        # from the repository root
./test.sh --agent-bus-mcp          # real Codex and Claude CLIs discover the server
./test.sh --agent-bus-security     # M3 safety fixtures on their own
python3 -m unittest discover -s tests -t .   # from this directory
```

The suite proves migrations are versioned and repeatable, WAL and foreign
keys are on, concurrent claimers of one task get exactly one winner, a
replayed request creates nothing twice, events cannot be updated or deleted,
a process killed at any point around a pull-beta transition leaves the
store either fully before or fully after that transition, and the HTTP
server follows the MCP 2025-06-18 session, error, and protocol-version
rules while refusing non-loopback binds without `--allow-remote`. The M3
fixtures prove concurrent writers never share a worktree, a stale or
vanished worktree refuses claims and publishes, approvals are bound to one
task, operation and nonce and cannot be replayed or forwarded through the
bus, artifact paths cannot escape the worktree or pass through symlinks,
and known secret shapes never reach the database or a peer.
