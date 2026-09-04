# ADR 0002: Agent Bus packaging and implementation language

Status: accepted by the maintainer on 2026-09-02, before M1; Python floor
amended to 3.10 the same day (see Amendments)

## Context

The Luciazero README states that Luciazero is a discipline layer, not an agent
runtime. `npx luciazero` writes skills, hooks, and doctrine into the user's
`~/.claude` and Codex configuration and must never start a daemon as a side
effect. The npm package is Node and Bash with `engines.node >= 18`, and its
`files` list is asserted by `./test.sh`.

The Agent Bus needs a long-running local daemon that owns SQLite, serves MCP
over loopback HTTP, and later supervises provider subprocesses. The M0 spike
(`scripts/agent_bus_spike.py`) already implements a Streamable HTTP MCP
responder, a JSON-RPC stdio client for Codex App Server, and subprocess control
for Claude using only the Python standard library.

`python3` is already a development dependency of `./test.sh` (Relay tests,
prompt budget checks, the spike) but is not a runtime dependency of the
published package.

## Options considered

### Packaging

1. Ship the daemon inside the `luciazero` npm package.
   - Breaks the README promise and grows `files`, install surface, and
     `./test.sh --full` time for every user, including those who never use
     the bus.
2. Companion package `luciazero-agentd` in this repository under `agentd/`,
   excluded from the core package `files`, with its own manifest and its own
   test tiers. Split into a separate repository only if release cadence
   diverges.
3. Separate repository from the start.
   - Cleanest boundary, but the protocol, skill, and daemon change together
     through M4; two repositories double the review and release work while
     the contract is still moving.

### Language

1. Node. Native SQLite needs either `better-sqlite3` (native build on
   install) or `node:sqlite` (Node 22.5+), which raises the engine floor above
   the core package.
2. Python 3.10+ standard library only: `sqlite3`, `http.server`,
   `subprocess`, `json`. No pip dependencies. FastMCP is not required; the
   spike already speaks the MCP JSON-RPC surface directly.
3. Python with FastMCP. Adds a pip dependency and a second install path for
   a small gain in ergonomics.

## Decision

- Packaging: option 2. The daemon lives in `agentd/` in this repository as the
  companion package `luciazero-agentd`. The core `luciazero` package gains only
  the `/lucia-bus` skill and a thin `luciazero bus status` client that talks to
  the daemon over loopback HTTP with the capability token; neither requires the
  daemon to be installed to keep the core package working.
- Language: option 2. `agentd` is Python 3.10+ with no third-party runtime
  dependencies. Distribution follows the existing `npx` pattern: an npm bin
  shim checks for `python3 >= 3.10` and execs the daemon, so users get one
  install mechanism for both packages.
- The daemon and its runtime never enter the core `luciazero` package, and
  ordinary `npx luciazero` installation never starts a daemon or writes bus
  state. The core package does change in M2: it gains the `/lucia-bus` skill,
  the status client, catalog and installer assertions, and the README skill
  count. Its `engines` floor stays at Node 18.
- Platform support for v1: macOS, Linux, and WSL2, matching the Bash-based
  core package. Native Windows is not supported in v1. The bin shim locates
  the interpreter by trying `python3`, then `python`, then the Windows
  launcher `py -3` (WSL and future native support), and accepts the first one
  reporting 3.10 or newer; otherwise it exits with a message naming the
  requirement and the interpreters it tried, without touching any state.

## Consequences

- `./test.sh` gains fake-provider tiers for `agentd` that need only `python3`,
  which CI already has; live provider gates stay opt-in.
- The M0 spike code is the seed of `agentd/`; its stdlib MCP responder and
  App Server client move there in M1/M2 instead of being rewritten in Node.
- M0 proves that the standard library is enough for a prototype that both
  CLIs discover. It does not prove MCP specification conformance for
  production use: session handling, protocol version negotiation, error
  shapes, notifications, and Streamable HTTP details. M2 carries a
  protocol-conformance gate for the shipped daemon; passing discovery in M0
  is not evidence for it.
- Users without Python 3.10 cannot run the bus. This is acceptable for an
  opt-in beta and is documented in M8.
- Rollback: delete `agentd/`, the skill, the status client, and their
  catalog, installer, and README entries. No daemon, state directory, or MCP
  configuration remains on a user's machine after `luciazero` alone is
  installed.

## Amendments

- 2026-09-02, Python floor 3.10 instead of 3.11. The maintainer's machine
  runs Python 3.10.20 and `./test.sh` invokes `python3`, so a 3.11 floor
  would have made the M1 gate unrunnable where it is developed. Nothing in
  the design needs a 3.11-only feature; the daemon targets 3.10+ and the bin
  shim accepts the first interpreter reporting 3.10 or newer. The package
  enforces this in `luciazero_agentd/__init__.py`.

- 2026-09-04, the bin shim exists and `install.sh` installs it. `npx
  luciazero` never had a daemon to run, so the shim shipped in the npm payload
  would have been a command with no package behind it; instead `install.sh`
  writes `bin/luciazero-agentd` into `~/.claude/bin` (or `LUCIAZERO_BIN_DIR`)
  from a checkout, and records the package location in
  `~/.claude/.luciazero-agentd-home`. The shim resolves its own path through
  symlinks and never uses the caller's working directory, which the daemon
  records; the interpreter order in the Decision above is what it implements.
  An executable it does not own is refused, never replaced.
- 2026-09-04, `luciazero-agentd service install|status|uninstall` writes a
  launchd LaunchAgent on macOS and a systemd `--user` unit on Linux and WSL2 —
  the same platform scope as this ADR, per-user rather than system-wide, and
  refused by name on Windows. It is the packaging decision applied to running
  the daemon: still no pip, still no root, still nothing outside the user.

## Decision record

Both option-2 choices were accepted on 2026-09-02. This unblocks M1. Reopening
the language choice later would reopen the M0 spike, which would then need a
Node port.
