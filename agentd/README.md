# luciazero-agentd

Companion package to [luciazero](../README.md): the local daemon behind the
Agent Bus. Python 3.10+ standard library only, no pip dependencies. Not
published; the release decision is milestone M8 in
[the roadmap](../docs/agent-bus-roadmap.md).

Current milestone: **M2, MCP control plane.** The package owns the SQLite
schema (`luciazero_agentd/migrations.py`), the store operations the pull
beta uses (`luciazero_agentd/store.py`): agent registration, message send
and inbox, delivery acknowledgement, task create/claim/complete, artifact
publish, an append-only event log, and idempotent replays; and the MCP
Streamable HTTP server that exposes them as twelve tools on loopback behind
a bearer token (`luciazero_agentd/server.py`).

The daemon CLI (run from this directory, or with `PYTHONPATH=agentd` from
the repository root):

```bash
python3 -m luciazero_agentd serve           # foreground on 127.0.0.1:8765; writes endpoint.json
python3 -m luciazero_agentd status [--json] # read-only queue summary; never mints a token
python3 -m luciazero_agentd client-config   # `codex mcp add` / `claude mcp add` commands
```

State lives under `${LUCIAZERO_AGENT_BUS_HOME:-~/.luciazero/agent-bus}`
(directory `0700`, token `0600`). Tests and gates always point that variable
at a temporary directory and never touch the developer's real state.

Verify:

```bash
./test.sh --agent-bus-store        # from the repository root
./test.sh --agent-bus-mcp          # real Codex and Claude CLIs discover the server
python3 -m unittest discover -s tests -t .   # from this directory
```

The suite proves migrations are versioned and repeatable, WAL and foreign
keys are on, concurrent claimers of one task get exactly one winner, a
replayed request creates nothing twice, events cannot be updated or deleted,
a process killed at any point around a pull-beta transition leaves the
store either fully before or fully after that transition, and the HTTP
server follows the MCP 2025-06-18 session, error, and protocol-version
rules while refusing non-loopback binds without `--allow-remote`.
