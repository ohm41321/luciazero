# Luciazero Agent Bus roadmap

Status: proposed, revised 2026-09-02 after the first M0 gate run

Working name: Luciazero Agent Bus

Target: local-first coordination between Codex CLI and Claude Code CLI

## Outcome

Build a durable, vendor-neutral coordination layer where Codex and Claude
workers can discover one another, exchange structured findings, claim tasks,
publish artifacts, and resume work across process and session boundaries.

The first release is successful when this flow passes without manual message
copying:

```text
Codex architect
  -> creates a review task
  -> Claude reviewer resumes and reports a finding
  -> Codex implementer resumes and publishes a change artifact
  -> Claude reviewer verifies the artifact
  -> architect receives the final result
```

v1 ships in two steps that share one tool contract:

- **Pull beta.** The user starts each agent turn. Each agent fetches its inbox
  and claims tasks through MCP tools when it runs. The bus removes message
  copying; it does not yet remove the turn trigger.
- **Managed dispatch.** A dispatcher resumes managed worker sessions
  automatically. This removes the trigger and is layered on top of the pull
  beta without changing the tool contract.

## Boundaries

### In scope for the v1 pull beta

- One machine and one user account.
- Codex CLI and Claude Code CLI as MCP clients.
- Stable agent identities separated from provider session IDs.
- MCP tools for agents, messages, tasks, and artifacts.
- SQLite WAL storage owned by one local daemon.
- Atomic task claims, idempotency, and audit history.
- Separate Git worktrees for concurrent writers.
- Human approval gates for destructive or externally visible actions.

### Added by v1 managed dispatch

- Codex App Server and Claude print-mode adapters.
- Automatic dispatch to explicitly managed worker sessions.
- Session leases, generation fencing, and delivery retries.
- Task dependency graphs, budgets, and loop limits.

### Not in scope for v1

- Replacing Lucia Relay. Relay remains the portable, evidence-backed handoff
  protocol; the bus coordinates live work and may reference Relay artifacts.
- Resuming arbitrary interactive sessions that a person currently controls.
- Multi-user authorization or a public hosted service.
- Multi-machine scheduling, Redis, or PostgreSQL.
- Sharing complete transcripts or merging context windows.
- Letting one agent grant permissions or consent on behalf of the user.
- Exactly-once execution. The bus provides at-least-once delivery plus
  idempotent handling.

## Architecture decisions

```text
MCP clients                         Managed execution (M6+)

Codex CLI ----\                    /--> Codex App Server adapter
               \                  /
                > agentd + SQLite
               /                  \
Claude Code --/                    \--> Claude CLI adapter

                 control plane          execution plane
```

- `agentd` is the only database owner exposed to clients. MCP tools and the
  dispatcher share its service layer rather than writing SQLite independently.
- Delivery is pull-first. An agent that runs calls `message_inbox` and
  `task_claim`; the daemon never needs to reach into a session to deliver.
  Managed dispatch adds a push trigger on top of the same records.
- Codex uses App Server `thread/resume` plus `turn/start` as the primary
  adapter. `codex exec resume` is the fallback. Threads used for resume must
  not be ephemeral; see ADR 0001 for the recorded null result.
- Claude uses `claude -p --resume` for managed workers. Native Claude
  cross-session messaging remains useful between Claude sessions but is not
  the cross-vendor source of truth.
- A session lease enforces one active writer per provider session.
  Human-owned sessions are unavailable to the dispatcher; it resumes only
  managed sessions that hold a live lease.
- Messages from another agent are untrusted input. They can carry evidence and
  recommendations, but never user consent or permission approval.
- Writers use separate worktrees. Read-only agents may share a checkout only
  when their commands cannot mutate it.
- Bus and Relay are separate contracts. Relay is evidence-backed handoff of
  finished or paused work; the bus is live queue coordination. The agent-facing
  workflow ships as a separate `/lucia-bus` skill and does not extend
  `/lucia-relay`.
- Packaging and implementation language are decided in ADR 0002 before any
  schema or daemon code lands. The README promise that Luciazero is a
  discipline layer, not an agent runtime, is a constraint on that decision.

## Core state

The initial schema contains:

- `agents`: stable identity, provider, role, capabilities, and status TTL.
- `sessions`: provider session/thread ID, generation, ownership mode, cwd,
  worktree, and lifecycle state.
- `messages`: immutable envelope, sender, recipient, kind, payload,
  correlation ID, reply target, idempotency key, and hop count.
- `deliveries`: attempts and transitions from queued through completion or
  dead letter.
- `tasks`: assignment, dependencies, priority, state, result, and version.
- `runs`: one provider invocation, lease, timing, exit state, and output
  reference.
- `leases`: exclusive session and task ownership with expiry.
- `artifacts`: typed references to commits, patches, reports, logs, and Relay
  manifests; large content is not embedded in messages.
- `events`: append-only audit records for state-changing operations.

Required delivery states:

```text
queued -> claimed -> dispatched -> processing -> acknowledged -> completed
                      |                |
                      +-> retryable_failed
                                       +-> retryable_failed

retryable_failed -> queued | dead_letter
```

In the pull beta a delivery moves from `queued` to `acknowledged` when the
recipient agent reads and acks it; `dispatched` and `processing` are used only
by managed dispatch.

## Timeline and implementation checklist

Dates are deliberately milestone-based. Start the next milestone only after
the previous exit gate is green.

### M0 — Contract and feasibility spike (complete 2026-09-02)

Known state on 2026-09-02: the offline gate is green and prints
`PASS  agent bus M0 offline protocol spike`; `./test.sh --fast` is green
without running it. The live gate passed on `codex-cli 0.152.1` and
`2.1.258 (Claude Code)` with `PASS  agent bus M0 live provider round trips`:
each provider's model selected and called `spike_echo` through the
bearer-protected temporary server (the server recorded the call token), and
each resumed session echoed a fresh token. Bearer delivery is proven for both
CLIs with a 401 negative control. A third null result is recorded in ADR
0001: Codex `approvalPolicy: "never"` fails MCP tool calls outright; managed
workers must run `on-request`. M0 is complete. Two null results are recorded in ADR 0001: ephemeral
threads never persist a rollout, and non-ephemeral threads persist it only on
the first turn, so `thread/resume` before any turn is rejected either way.

Offline proves protocol and configuration surfaces only: CLI versions
resolve, a disposable thread starts under an isolated `CODEX_HOME`,
resume-before-turn fails with the distinct permanent `no rollout found`
error, and both CLIs discover the same temporary MCP endpoint. It proves
nothing about model inference, authentication, or a real resumed turn. Only
the live gate proves those, by returning each provider's correlation token
from an actual resumed turn.

- [x] Record installed Codex and Claude CLI versions in the test fixture.
- [x] Start the Codex probe thread without `ephemeral: true`; isolate through
  a temporary `CODEX_HOME` instead.
- [x] Prove a disposable Codex thread starts through App Server and that
  resume before any turn fails with a distinct, permanent error (offline).
- [x] Prove a disposable Codex thread resumes after a turn and returns
  structured output through App Server (live gate, passed 2026-09-02).
- [x] Prove a disposable Claude session can start and resume non-interactively
  (live gate, passed 2026-09-02).
- [x] Prove isolated Codex and Claude MCP clients can discover the same
  temporary HTTP server and read the same tool contract (offline).
- [x] Prove each provider's model selects and calls one bus tool through that
  server, and the call is recorded server-side (live gate, passed
  2026-09-02). Discovery proves the contract is visible; it does not prove
  the model uses it.
- [x] Prove each CLI can attach the capability bearer token to its Streamable
  HTTP MCP requests (offline, passed 2026-09-02): Claude via
  `claude mcp add ... --header "Authorization: Bearer ..."` and
  `--mcp-config` headers; Codex via `--bearer-token-env-var` and
  `mcp_servers.<name>.bearer_token_env_var`. The probe answers token-less
  requests with 401 and a negative control proves that path.
- [x] Run the spike only under `./test.sh --agent-bus-spike`. The default and
  `--fast` tiers syntax-check the spike sources and pass without `codex` or
  `claude` installed.
- [x] Exit 3 with `skip: required CLI not found: ...` when a provider binary
  is absent, so the gate is never green without evidence.
- [x] Decide the local data directory and Unix socket/HTTP binding rules.
- [x] Write an ADR for managed workers versus human-owned sessions.
- [x] Draft ADR 0002: companion package `luciazero-agentd` under `agentd/`,
  Python 3.11+ standard library, npm bin shim. Proposed, not yet accepted.
- [x] Maintainer accepted ADR 0002 on 2026-09-02.
- [x] Run the live gate once with quota approval and record versions and
  decisive output here (see Known state above).

Exit gate:

```bash
./test.sh --agent-bus-spike
./test.sh --fast
```

The first command is offline by default and proves the protocol surfaces
without using provider quota. The second must stay green on a machine without
provider binaries. ADR 0002 must be accepted. The complete gate is:

```bash
LZ_AGENT_BUS_LIVE=1 ./test.sh --agent-bus-spike
```

Live mode must fail when either provider cannot resume the disposable session
and pass when both round trips return their correlation IDs. It requires
explicit quota approval and must not run in CI.

Rollback point: remove the spike and keep Luciazero as a verification and
handoff layer only.

### M1 — Durable store and state machine (complete 2026-09-02)

Scope is the store contract the pull beta actually exercises. Session leases,
generation fencing, retries, and dead-letter handling belong to managed
dispatch and are built in M6; M1 only reserves their columns and states.

Known state on 2026-09-02: `agentd/` exists as the companion package
(`luciazero_agentd`, Python 3.10+ standard library, `private: true`). The
store gate prints `PASS  agent bus M1 store gate green` and runs inside
`--fast` and `--full` as well. The independent adversarial review returned
one major (migration race could poison a connection), three minor (fresh-file
WAL switch race, NaN accepted as JSON, `$` in the id regex accepting a
trailing newline) and six nits; all are fixed with regression tests, and a
revert probe confirmed the migration regression fails on the old code.
Idempotency keys are namespaced per actor as a result of the review.

- [x] Add versioned SQLite migrations (`PRAGMA user_version`, one
  transaction per version, newer-schema refusal).
- [x] Enable WAL, foreign keys, and a bounded busy timeout.
- [x] Implement atomic message and task claims (single conditional UPDATE,
  row count decides; 16 concurrent claimers, one winner).
- [x] Reject duplicate idempotency keys without duplicating side effects
  (replay returns the original entity; same key with a different request is
  a conflict).
- [x] Make event history append-only and messages immutable (schema
  triggers).
- [x] Reserve `leases`, `runs`, generation, and retry fields in the schema
  without enforcing them.
- [x] Test process crash and restart during the pull-beta transitions:
  `queued`, `acknowledged`, `completed` and `open`, `claimed`, `completed`,
  killed before and after COMMIT for each.
- [x] Resolve the independent adversarial review findings (10 of 10, with
  regression tests and a revert probe on the major one).

Exit gate:

```bash
./test.sh --agent-bus-store
```

The suite must prove that concurrent claimers produce one winner and that
replaying a request does not create a second task or message.

### M2 — MCP control plane (complete 2026-09-03)

Known state on 2026-09-02: `agentd/luciazero_agentd/server.py` serves the
12 tools over Streamable HTTP with bearer auth, `Mcp-Session-Id` sessions,
Origin/Host checks and a 1 MiB body cap; `python3 -m luciazero_agentd
serve|status|client-config` is the daemon CLI; `npx luciazero bus status`
is the Node client. The conformance suite (21 tests) runs inside the
`--agent-bus-store` gate and therefore in `--fast` and `--full`. The offline
M2 gate passed against the real CLIs: both negotiated `2025-06-18`, both
called `tools/list` (Codex also `resources/list`), Codex reported the same
12 tools, and the raw-client exchange ended with `delivery.completed`
after 10 events. The live gate passed on 2026-09-03 (see the checklist). The independent adversarial review returned
one major (control characters in peer-supplied `role`/`title` reached the
human's terminal through `bus status`), eight minor (non-ASCII bearer crash,
pathological JSON dropping the connection, unread bodies on keep-alive after
an early error, no socket timeout, unbounded session table, the gate not
asserting Claude's `tools/list`, `status` honouring `http_proxy`, a second
daemon erasing the first one's `endpoint.json`) and seven nits; all are
fixed with regression tests (57 in the daemon suite) and the gate against
the real CLIs still passes.

Session-start guidance is carried by the `/lucia-bus` skill description and
by `luciazero bus status`, which prints the next step when work is queued;
the always-loaded doctrine is unchanged to keep its context cost fixed.

- [x] Implement `agent_register`, `agent_list`, and `agent_heartbeat`.
- [x] Implement `message_send`, `message_inbox`, and `message_ack`.
- [x] Implement `task_create`, `task_list`, `task_claim`, and `task_complete`.
- [x] Implement `artifact_publish` and `artifact_get`.
- [x] Add correlation IDs and typed message kinds: `task`, `question`,
  `finding`, `decision`, `artifact`, and `result`.
- [x] Validate every input with explicit size and enum limits (closed JSON
  schemas per tool plus store validation; invalid arguments are `isError`
  tool results, not protocol errors).
- [x] Add pagination and stable ordering to list operations (`seq` cursors,
  `next_after`, `has_more`).
- [x] Bind locally by default and refuse non-loopback exposure without an
  explicit authenticated configuration (`--allow-remote`; token always
  required; foreign `Origin`/`Host` answered 403).
- [x] Pass a protocol-conformance suite for the shipped daemon: protocol
  version negotiation, session handling, error shapes, notifications, and
  Streamable HTTP behaviour against the MCP specification. The M0 stdlib
  prototype passing discovery is not evidence for this.
- [x] Configure disposable Codex and Claude homes in integration tests rather
  than modifying the developer's real configuration (`CODEX_HOME`,
  `CLAUDE_CONFIG_DIR`; the real `~/.luciazero` is never touched).

Agent-facing and human-facing surfaces. Without these the pull beta has no
user and the M4 decision gate cannot collect evidence.

- [x] Add the `/lucia-bus` skill: inspect inbox, claim, work, publish result
  or blocked outcome. It is a separate skill from `/lucia-relay`.
- [x] Add `luciazero bus status` so a person sees pending inbox items and
  tasks before starting an agent turn (Node client in the core package,
  `GET /status` on the daemon; proven end to end in `--fast`).
- [x] Add session-start guidance for Claude and Codex that points at the
  inbox check (skill description plus the `next:` line of `bus status`).
- [x] Extend `/done`: a claimed bus task must have a published result or
  blocked outcome before closeout.
- [x] Update `skills/catalog.txt`, installer and package assertions, and the
  skill count in `README.md` and `README.th.md` (11 to 12 everywhere
  `test.sh` asserts it).
- [x] Resolve the independent adversarial review findings (16 of 16).
- [x] Run the live M2 gate once with quota approval
  (`LZ_AGENT_BUS_LIVE=1 ./test.sh --agent-bus-mcp`). Passed 2026-09-03 on
  `codex-cli 0.152.1` and `2.1.259 (Claude Code)` with
  `PASS  agent bus M2 live cross-vendor exchange`: the Codex model called
  `message_send` with a fresh marker, the Claude model called
  `message_inbox` and `message_ack` and returned the marker, and the store
  showed the delivery acknowledged. Cost: 3 provider turns (2 Codex, 1
  Claude); the first attempt failed before Claude inference because
  `--allowedTools` is variadic and swallowed the trailing prompt, now fixed
  in the gate and recorded in ADR 0001.

Exit gate:

```bash
./test.sh --agent-bus-mcp
./test.sh --fast
```

Both clients must discover the same tool contract and exchange one structured
message through a temporary daemon. The daemon must pass the
protocol-conformance suite, and the skill must pass the existing prompt and
catalog checks in `--fast`.

### M3 — Git isolation and safety (complete 2026-09-03)

Known state on 2026-09-03 (closed after a third Codex pass returned no findings): ADR 0003 records the decisions. Schema version 2
adds `worktrees`, `approvals`, and `tasks.requires_worktree`; the tool
contract grows to 15 (`worktree_bind`, `worktree_get`, `approval_consume`)
and both real CLIs still discover it (offline M2 gate re-run: 15 tools,
`delivery.completed`). The daemon reads worktree identity with `git`
itself, re-verifies it before every claim and publish, refuses shared
toplevels, and contains artifact paths. Approvals are minted only by the
interactive `luciazero-agentd approve` command (refuses piped stdin,
exercised on a real pseudo-terminal), stored as a hash, bound to one task,
operation, and nonce, single use, and scrubbed from any payload that tries
to forward them. `luciazero_agentd.redact` scrubs payloads, titles,
results, events, tool errors, and `/status`, with the daemon token as a
literal. Two independent adversarial reviews (Codex and the `reviewer`
agent) each found a major the first fixtures missed, both proven with live
probes: `.GIT/config` published on a case-insensitive filesystem because
only an exact-case leading `.git` was refused, and an approval nonce
travelled through an artifact file name and file content, and through
dict keys and id-shaped fields (`correlation_id`, `idempotency_key`,
`agent_id`, capabilities) because only payload values were scrubbed. Fixed
by refusing any `.git` component in any case at any depth plus an inode
check against the git dir and common dir, refusing secret-shaped ids,
refs, file contents and worktree paths, scrubbing JSON keys, roles and
capabilities, and scrubbing tool results on the way out. Minor and nit
findings also fixed: rebinding elsewhere while holding claimed worktree
tasks is refused, the `key = value` heuristic now catches `access_token=`
and `AWS_SECRET_ACCESS_KEY=` but no longer damages prose or code (value
must carry a digit), URL userinfo matches any scheme case and an empty
user, every regex is bounded (a 64 KiB hyphenated payload cost 2 s before),
`commit` artifacts refuse a caller-supplied sha256, EOF at the approve
prompt declines cleanly, and ADR 0003 no longer overclaims what the TTY
check stops. A second Codex pass then proved one more major: id checks ran
against the pattern-only redactor, so the daemon's own bearer token (no
fixed shape) went into `correlation_id` and `idempotency_key` raw. Every id
check now runs through the store's redactor, with a regression across all
ten id channels and through the daemon itself. Decision on the residual
risk it raised: any value after `Authorization: Bearer` is caught, a bare
`Bearer` value needs a digit, and the all-letter bare case is an accepted,
documented false negative. The daemon suite is now 104 tests; the M3
fixtures also run on their own under `--agent-bus-security`.

- [x] Record one worktree and branch per writing worker.
- [x] Record repository identity, base OID, current HEAD, and dirty state.
- [x] Refuse task claims and artifact publishes when the recorded worktree
  identity no longer matches.
- [x] Require user approval for delete, deploy, production access, spending,
  force-push, public-contract changes, and scope expansion (fixed set
  `SENSITIVE_OPERATIONS`; the `/lucia-bus` skill ends without one as
  `blocked`).
- [x] Implement the approval provenance contract:
  - No MCP tool can create an approval.
  - An agent `decision` message is a recommendation only.
  - An approval is bound to one task, one operation, and one nonce; it cannot
    be forwarded or replayed through a message or artifact.
  - A sensitive operation returns to the controlling human session for
    consent instead of proceeding on peer input.
  - The local approval CLI is interactive, refuses non-TTY input, and uses a
    separate administrative channel, not the agent-facing MCP endpoint.
- [x] State the threat model: v1 defends against cooperative-agent mistakes.
  It does not defend against a malicious local process running as the same
  OS user, which can reach the same files and CLI. (ADR 0003.)
- [x] Redact secrets from messages, events, errors, and provider output
  (provider output: the M6 adapters must route through the same scrubber;
  recorded as an M6 item).
- [x] Refuse unsafe artifact paths, symlinks, oversized payloads, and
  credential-bearing repository URLs.
- [x] Threat-model prompt injection through messages and artifacts (ADR
  0003; mechanical guarantees plus skill guidance).
- [x] Resolve the independent adversarial review findings (Codex: 2 major,
  2 minor on ADR 0001/0002 wording; `reviewer` agent: 1 major, 3 minor,
  5 nits; all fixed with regression tests).

Exit gate:

```bash
./test.sh --agent-bus-security
./test.sh --fast
```

Security fixtures must prove cross-worktree isolation, stale-identity refusal,
approval provenance, path containment, secret redaction, and bounded input.

### M4 — Pull-beta vertical slice (complete 2026-09-03, one live gate rerun owed)

Known state on 2026-09-03: `scripts/agent_bus_e2e.py` drives the outcome
flow through the shipped daemon (subprocess on a disposable state
directory) in a disposable repository with one worktree per writer; every
turn opens a fresh MCP session and learns its work only from the inbox,
task list and artifact records. Fake provider: `./test.sh --agent-bus-e2e`
prints `PASS  agent bus M4 pull-beta vertical slice (fake provider)` with
3 tasks, 5 messages, 5 deliveries, 3 artifacts (report, commit, report),
2 worktrees, one correlation id across all messages, and two daemon pids
(restart between the finding and the fix). `--full` runs it; `--fast`
does not. Building it surfaced one gap: a pull-beta turn exists only when
the user opens that session, so the first agent could not address peers
that had never registered; `luciazero-agentd roster add` (human channel)
names the team once and the agent's own `agent_register` refreshes the
row. `luciazero-agentd cancel` is the human cancellation path; no MCP tool
cancels. Live provider turns run through the same driver (`--live`, Codex through
App Server on-request, Claude through `claude -p --mcp-config`); the one
approved live run is recorded in the last item below.

- [x] Register `codex-architect`, `claude-reviewer`, and
  `codex-implementer` as agents in user-started sessions (roster first,
  then each session's `agent_register`; fake provider, so "user-started"
  is structural until the live run below).
- [x] Run the outcome flow at the top of this document in a disposable Git
  repository, with the user starting each turn and no manual copying (fake
  provider; live providers pending approval).
- [x] Capture task, message, lease, event, and artifact records (`--json`;
  leases are empty by design until M6).
- [x] Verify daemon restart between the Claude finding and Codex fix.
- [x] Verify a new provider session can continue an open task under the same
  stable agent ID (the reviewer's second MCP session claims the verify
  task; the daemon binds nothing to provider sessions in the pull beta, so
  the live run is what proves it with a real second session).
- [x] Publish a reproducible demo that uses the shipped implementation
  (`docs/assets/agent-bus-demo.sh`, the same driver with narration).
- [x] Document setup, status inspection, cancellation, recovery, and cleanup
  (`docs/agent-bus.md`).
- [ ] Run the live slice once with quota approval
  (`LZ_AGENT_BUS_LIVE=1 scripts/agent-bus-e2e.sh --live`, six turns; the
  `test.sh` tier takes no extra arguments and stays fake-provider only).
  Ran 2026-09-03 on `codex-cli 0.152.1` and `2.1.259 (Claude Code)`, six
  real turns, ~11 minutes, correlation id
  `msg_92e94a57dd0647ac85458439840ce11b`. The flow reached the roadmap
  state: three tasks completed by their assignees, artifacts
  report/commit/report from reviewer/implementer/reviewer, the five owed
  deliveries all acknowledged and completed, one correlation id
  throughout, the daemon restarted (pid 32900 to 33935) with the queue
  surviving, both writers on their own worktrees with no
  `worktree.mismatch`, zero approvals needed. The models did the real
  work: Codex committed `0d88c4b` fixing `split_fields` on quoted
  segments, and the reviewer's second session verified it on an export
  (base red, fix `OK`). The driver still exited 1, because
  `assert_outcome` demanded exactly five messages and the live architect
  added a sixth courtesy `result` to the reviewer that no later turn
  exists to read. That assertion was the bug. It now
  matches the five-step spine as a subsequence, so chatter from any turn
  is tolerated in live mode, while fake mode still refuses every extra
  message; chatter that repeats a step of the flow is refused in both
  modes (a replayed send is not politeness), and a chatter delivery that
  failed or was dead-lettered still fails the gate. An independent
  adversarial review of that relaxation found two majors, both fixed here:
  the first version let a duplicated `result` and a dead-lettered chatter
  delivery through. `agentd/tests/test_e2e_outcome.py` covers the branch in
  nine cases, including the recorded message and delivery set of this run,
  because no fake-provider run reaches it. The item stays unchecked until a
  live run exits 0: that costs another six turns and has not been spent.
- [x] Resolve the independent adversarial review findings (`reviewer`
  agent: 3 minor, 5 nits, no major): the outcome assertion now checks who
  held each task, who produced each artifact, who sent each message and
  that the two writers hold exactly their own real worktree paths (it had
  checked states and kinds only); cancelling a task dead-letters its queued
  `task` messages so `bus status` stops asking for a dead turn, and `/done`
  plus `/lucia-bus` accept a user-cancelled task; `roster add` audits as
  `agent.rostered` under `human:<user>` and keeps recorded capabilities
  when none are given; docs say every command runs from `agentd/` and the
  cleanup honours `LUCIAZERO_AGENT_BUS_HOME`; the driver refuses a bare
  `--dry-run`, uses the tar data filter on 3.12+, and fails cleanly when the
  verify task is missing; the two "session" items above are hedged as
  structural until the live run.

Exit gate:

```bash
bash docs/assets/agent-bus-demo.sh
./test.sh --agent-bus-e2e
```

The demo must use disposable configuration and repositories, print the final
correlation ID, and leave the real Codex/Claude session stores unchanged.

This milestone can consume model quota. Run the real-provider test only after
explicit budget approval; keep a deterministic fake-provider equivalent in CI.

Decision point: the pull beta may be released as an opt-in command at this
milestone. Continue to managed dispatch only when all of the following are
recorded before M5 starts:

- At least three distinct real workflows (not the demo) completed on the pull
  beta, each with its correlation ID and record set kept.
- In at least two of them, a retro or run log names the user-started turn as
  the blocking cost, with the wait or turn count measured.
- No open M3 safety finding.

If that evidence does not exist, the release decision is "stop at the pull
beta"; "it feels used" is not a gate.

### M5 — Task orchestration and artifacts

- [ ] Unblock dependent tasks transactionally when prerequisites complete.
- [ ] Detect dependency cycles before committing a task graph.
- [ ] Enforce a maximum hop count and conversation TTL.
- [ ] Reference commits, reports, patches, logs, and Lucia Relay manifests as
  artifacts.
- [ ] Add per-task time, turn, token, and cost budgets where providers expose
  the necessary measurements.
- [ ] Stop automatic dispatch when a budget or retry limit is reached.

Exit gate:

```bash
./test.sh --agent-bus-workflow
```

A deterministic fake-provider scenario must execute a dependency graph,
reject a cycle, stop an infinite reply loop, and preserve artifact provenance.

### M6 — Dispatcher and provider adapters

- [ ] Define one adapter contract for start, resume, cancel, status, and event
  streaming.
- [ ] Codex adapter: start threads with `approvalPolicy: "on-request"` and
  answer approval requests per the user's configured policy; `"never"` fails
  MCP tool calls before they reach the bus (ADR 0001 null result 3).
- [ ] Claude adapter: pass the bus server through `--mcp-config` with
  `--strict-mcp-config` and pre-allow bus tools with `--allowedTools`; the
  user's own MCP configuration is never written.
- [ ] Implement the Codex App Server adapter.
- [ ] Add `codex exec resume` as a tested fallback.
- [ ] Implement the Claude print-mode resume adapter.
- [ ] Stream provider output into bounded run logs, routed through
  `luciazero_agentd.redact.Redactor` with the daemon token as a literal
  before anything is written (ADR 0003: provider output is in the redaction
  contract, and no adapter exists before this milestone).
- [ ] Add lease acquisition, renewal, expiry, and generation fencing on the
  columns reserved in M1.
- [ ] Renew the session lease only while the owned process is alive.
- [ ] Prevent concurrent resume of the same provider session.
- [ ] Add retry limits and dead-letter transitions.
- [ ] Distinguish retryable provider errors from permanent configuration
  failures.
- [ ] Recover orphaned `processing` deliveries after daemon restart.
- [ ] Test process crash and restart during every delivery transition,
  including `dispatched` and `processing`.

Exit gate:

```bash
./test.sh --agent-bus-dispatch
```

The suite must kill the dispatcher during a run, restart it, and show that the
message reaches one completed logical outcome without concurrent session use.
Expired leases must be recoverable and stale generations must be fenced.

### M7 — Managed-dispatch vertical slice

- [ ] Register the three agents from M4 as managed workers.
- [ ] Run the outcome flow with no user-started turns.
- [ ] Capture run records in addition to the M4 records.
- [ ] Verify daemon restart between the Claude finding and Codex fix.
- [ ] Verify a full session rotation while preserving the stable agent ID.
- [ ] Extend the M4 demo and documentation to cover managed workers.

Exit gate:

```bash
bash docs/assets/agent-bus-demo.sh --managed
./test.sh --agent-bus-e2e
```

Same disposable-configuration rules and quota approval as M4.

### M8 — Beta integration and release decision

- [ ] Run the full Luciazero verification suite.
- [ ] Perform separate security and public-contract reviews.
- [ ] Test install, update, and uninstall without touching unrelated MCP
  configuration.
- [ ] Add an opt-in CLI command; do not start a daemon during ordinary
  Luciazero installation.
- [ ] Document limitations, storage location, cleanup, and recovery.
- [ ] Measure idle resource use, dispatch latency, and duplicate-delivery rate.
- [ ] Confirm the ADR 0002 packaging decision still holds against the
  measured footprint.
- [ ] Name the feature only after the vertical slice and packaging decision.

Exit gate:

```bash
./test.sh --full
```

`--full` runs only the fake-provider bus tiers. Every live provider gate is
opt-in at every milestone through `LZ_AGENT_BUS_LIVE=1`, and CI never sets
it. Release only when the full suite exits zero, both focused reviews have no
blockers, and every v1 requirement has linked evidence.

## Suggested delivery cadence

| Window | Milestone | Deliverable |
|---|---|---|
| Week 1 | M0 | Green spike, live proof, ADR 0002 |
| Week 2 | M1 | Crash-safe SQLite store |
| Week 3 | M2 | Shared MCP control plane, `/lucia-bus`, `bus status` |
| Week 4 | M3 | Safety boundary |
| Week 5 | M4 | Pull-beta vertical slice and release decision |
| After evidence | M5–M6 | Workflow semantics and managed dispatch |
| After evidence | M7 | Managed vertical slice |
| After evidence | M8 | Opt-in beta |

This is sequencing guidance, not a deadline. A red exit gate moves the next
milestone rather than weakening the gate.

## Global acceptance checklist

Items marked (M6+) apply only once managed dispatch exists.

- [ ] No task can be claimed by two workers at the same time.
- [ ] No provider session can have two active writers. (M6+)
- [ ] Replaying any state-changing request is idempotent.
- [ ] Daemon restart does not lose acknowledged messages or completed tasks.
- [ ] A failed dispatch is retried only within its declared policy. (M6+)
- [ ] Infinite agent-to-agent loops terminate at a budget, TTL, or hop limit.
  (M5+)
- [ ] A stable agent can rotate to a new provider session without losing its
  open tasks or address.
- [ ] Concurrent writers never share a worktree.
- [ ] Agent messages cannot authorize sensitive actions, and no MCP tool can
  create an approval.
- [ ] Logs and artifacts do not expose secrets or unbounded transcripts.
- [ ] Fake-provider integration tests run offline in CI.
- [ ] Real-provider tests are opt-in and disclose quota/cost requirements.
- [ ] The default `./test.sh` passes without provider binaries, and `--full`
  never runs a live provider gate.
- [ ] A claimed bus task cannot pass `/done` without a published result or
  blocked outcome.
- [ ] The full Luciazero verification command passes at closeout.

## Open decisions

- Resolved in M0 (2026-09-02): both CLIs attach the capability bearer token
  to Streamable HTTP requests; see ADR 0001, Transports, for the exact
  configuration surface each one uses.
- Which artifact formats should be first-class beyond commits and Lucia Relay?
- When should multi-machine delivery graduate from Relay references to a
  networked bus backend?

Local transport is decided: loopback Streamable HTTP only, a Unix socket is
not the MCP endpoint (ADR 0001). Packaging and language moved to ADR 0002 and
gate M0. The remaining decisions resolve through M0 and M4 evidence. None
blocks writing the protocol and fake-provider tests first.
