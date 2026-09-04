# ADR 0001: Agent Bus M0 boundaries

Status: accepted for the M0 spike, revised 2026-09-02 after the first gate run

## Context

Luciazero needs to test whether Codex CLI and Claude Code CLI can participate
in one local coordination system without reading or modifying each other's
transcripts. The spike must not turn ordinary Luciazero installation into a
daemon install, mutate the developer's MCP configuration, or spend provider
quota during CI.

Claude Code has native messaging between Claude sessions. That remains useful,
but it cannot be the source of truth for cross-vendor tasks. Codex App Server
provides explicit thread and turn lifecycle methods; Claude provides
non-interactive session resume through its CLI.

The repository CI (`.github/workflows/ci.yml`) runs `./test.sh` on a plain
`ubuntu-latest` runner. It does not install the `codex` or `claude` binaries
and must not start doing so for this spike.

## Decision

### Worker ownership

Every provider session is either `human` or `managed`.

- A human session is owned by the terminal or UI in which the user opened it.
  The dispatcher cannot resume or write to it.
- A managed session is created by `agentd`, has one active lease holder, and
  may be resumed only through its provider adapter.
- Human-owned sessions are therefore unavailable to the dispatcher; it may
  resume only managed sessions.
- Ownership cannot change while a session has an active process or lease.
- Stable agent identity is separate from provider session identity. Rotating a
  session increments its generation and fences stale workers.

M0 uses disposable, non-ephemeral sessions under temporary provider homes
(`CODEX_HOME` and `CLAUDE_CONFIG_DIR` pointed at a temporary directory).
Isolation comes from the temporary home, not from the provider's ephemeral
mode. M1 reserves the lease and generation columns; M6 must enforce this
decision with leases and generation checks before automatic dispatch exists.

Null results recorded on 2026-09-02 with `codex-cli 0.152.1`:

1. A thread started with `thread/start` and `"ephemeral": true` never
   persists a rollout, so `thread/resume` fails with
   `no rollout found for thread id ...`. Ephemeral and resumable are mutually
   exclusive in App Server.
2. A non-ephemeral thread persists its rollout on the first turn, not at
   `thread/start`. `thread/resume` before any turn fails with the same error
   and the disposable `CODEX_HOME` holds no `*.jsonl` after start.

3. Under `thread/start` `approvalPolicy: "never"`, a model-selected MCP
   tool call fails with `MCP tool call requires approval, but approval policy
   is never` and never reaches the server, even for a loopback tool. Under
   `"on-request"` the same call succeeds, and for this tool Codex sent no
   approval request at all. Managed Codex workers must therefore run
   `on-request` with the adapter answering any approval request per the
   user's configured policy.

4. Recorded 2026-09-04, and recorded because it was first misread: opening a
   database with the URI `file:<path>?mode=ro` reports a path that does not
   exist as `unable to open database file (14)`, which reads exactly like a
   permission or WAL problem. It is neither. `mode=ro` refuses to create what
   is missing, by design. Reading a live WAL database read-only, with the
   daemon attached and writing, works from both the `sqlite3` CLI and Python's
   `sqlite3.connect(..., uri=True)`. Every read-only reader here therefore
   checks the path itself first and names it in the error
   (`scripts/agent_bus_evidence.py`, `luciazero_agentd/watch.py`).

Consequently resume is provable only after an inference turn. The offline
spike proves `thread/start` and asserts that resume-before-turn is rejected
with that distinct error, which the dispatcher must classify as permanent
rather than retryable. The resume proof itself belongs to the live gate. Do
not retry either shortcut.

Live mode uses the developer's real provider homes because authentication
lives there; it isolates through uniquely named disposable sessions instead.
It leaves one rollout and one Claude session file behind per run. That is an
accepted M0 limitation; the M4 demo must clean up after itself.

### Local state

The proposed v1 state directory is:

```text
${LUCIAZERO_AGENT_BUS_HOME:-~/.luciazero/agent-bus}/
```

It will contain the database, endpoint metadata, capability token, bounded run
logs, and owned worktree records. The directory must be mode `0700`; secret or
database files must be `0600`. Tests always override the location with a
temporary directory and never use the developer's real state.

M0 does not create the persistent directory. ADR 0002 (packaging and
language) may revise this path if the decision requires platform-native
application data directories.

### Transports

- Agent-facing MCP: Streamable HTTP bound to `127.0.0.1` only.
- Default endpoint candidate: `http://127.0.0.1:8765/mcp`.
- Tests: an operating-system-assigned loopback port.
- Authentication: a random capability bearer token stored outside the
  repository. Loopback binding does not remove the authentication requirement.
- One shared token is sufficient at this scope, since v1 is bound to a single
  machine and a single user account; per-agent tokens and rotation are
  deferred to any multi-user scope, which v1 excludes.
- Verified 2026-09-02: both CLIs deliver the token. Claude through
  `claude mcp add --transport http <name> <url> --header "Authorization:
  Bearer ..."` (the variadic `--header` must come after the positionals;
  `claude -p --allowedTools a,b PROMPT` has the same trap and swallows the
  prompt, so a single-value option must sit between them) and
  through `--mcp-config` `headers`; Codex through
  `codex mcp add --url <url> --bearer-token-env-var <VAR>` and the
  equivalent `mcp_servers.<name>.bearer_token_env_var` override passed with
  `-c` to `codex app-server`, which never writes `config.toml`. The probe
  answers token-less requests with 401 and a negative control proves it.
- HTTP requests must enforce host/origin policy and bounded bodies before beta.
- Codex adapter: App Server over a private stdio child process.
- Claude adapter: `claude -p --resume` in a managed subprocess.

A Unix socket is not the MCP endpoint because the supported Codex and Claude
configuration surface accepts HTTP directly. It may later be used for a local
administrative control channel.

### Verification and quota

Offline mode proves protocol and configuration surfaces without spending
quota: CLI versions, disposable-thread start, rejection of resume before the
first turn, and shared MCP discovery. It does not prove model inference,
authentication, or a real resumed turn; only live mode does, by returning
each provider's correlation token from an actual resumed turn.

`./test.sh --agent-bus-spike` is offline by default. It records installed CLI
versions, starts a disposable Codex App Server thread under a temporary
`CODEX_HOME` without a model turn, verifies that resume-before-turn is
rejected with the distinct `no rollout found` error, and proves isolated
Codex and Claude MCP configurations discover the same temporary HTTP server.

The spike requires the provider binaries and therefore runs only under its own
tier. The default `./test.sh` and `./test.sh --fast` syntax-check the spike
sources and pass on a machine without `codex` or `claude`. When a binary is
absent, the spike prints `skip: required CLI not found: ...` and exits 3, so
the gate is never green without evidence and a caller can tell skipped from
failed.

The complete provider proof is opt-in:

```bash
LZ_AGENT_BUS_LIVE=1 ./test.sh --agent-bus-spike
```

Live mode performs start and resume inference turns for each provider and
requires explicit approval because it consumes provider quota. CI must never
set this flag. Correlation tokens in both returned turns are the pass/fail
evidence.

### Packaging decision is an M0 output

Whether the daemon ships inside `luciazero` or as a companion package, and
which implementation language it uses, is decided in ADR 0002 before M1 starts.
ADR 0002 was accepted on 2026-09-02: companion package `luciazero-agentd`,
Python standard library only, floor 3.10 (amended the same day from 3.11). The README states that Luciazero is a
discipline layer, not an agent runtime; the daemon must not enter the core
package and ordinary installation must not start one.

## Consequences

- The offline spike is deterministic on a developer machine with both CLIs
  installed. It is not part of the CI gate because CI has no provider binaries.
- A green offline spike proves protocol compatibility, not provider inference
  or authentication. The first live run on 2026-09-02 (`codex-cli 0.152.1`,
  `2.1.258 (Claude Code)`) proved start and resume for both providers but
  left two items open: model-selected tool calls and bearer-token delivery.
- The final live run the same day closed both: each model called
  `spike_echo` through the bearer-protected server and each session resumed
  with a fresh token. M0 is complete. Cost of the whole M0 live
  investigation was 15 provider turns, including one turn wasted by running
  the probe before an edit had landed.
- App Server remains the primary Codex adapter; `codex exec resume` stays a
  fallback for the dispatcher milestone.
- The daemon cannot adopt already-open interactive sessions automatically.
- Remote and multi-user operation remain outside v1.

## Rollback

Remove the spike entrypoint and this ADR. No persistent schema, user config, or
installation contract is introduced by M0.
