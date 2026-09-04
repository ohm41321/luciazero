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
- Order between tasks, per-task budgets, and artifact provenance are decided
  in ADR 0005: the daemon owns the graph and the limits, measures what it can
  measure itself, and only ever records what a provider tells it.
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

### M4 — Pull-beta vertical slice (complete 2026-09-03)

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
App Server on-request, Claude through `claude -p --mcp-config`); the two
approved live runs are recorded in the live item below, the second one
green.

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
- [x] Run the live slice once with quota approval
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
  nine cases, including the recorded message and delivery set of that run,
  because no fake-provider run reaches it. A second approved live run then
  exited 0 the same day (six more turns, correlation id
  `msg_4e38f88304e04e8ea57855348f5902c4`, daemon pids 69984 to 71139,
  commit `b913d23` verified green from an export): `PASS  agent bus M4
  pull-beta vertical slice (live providers)`. It vindicated the
  subsequence rule rather than merely repeating the first run, because
  this time the chatter fell in the MIDDLE of the flow — the implementer
  sent its own `result` to the architect before the reviewer's, and its
  delivery was completed, not queued. A positional prefix would have
  failed it. Live chatter is therefore a standing property of live runs,
  not a one-off: 12 provider turns, two runs, two different chatter
  shapes.
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

Where that stands is `docs/agent-bus-decision-log.md`, which is also the
ledger the workflows are recorded in. As of 2026-09-04 the gate is not met:
no real workflow has been recorded, and M5 and M6 shipped without waiting for
one. The log names the three ways out and leaves the choice to the user.

### M4.5 — Terminal binding and session credentials (complete 2026-09-04)

The last identity the model still asserts is its own: the user tells it "you
are `claude-reviewer`" and every tool call repeats that string. ADR 0004
proposes moving that decision into the human channel -- the user picks a
terminal with `luciazero-agentd terminal list` and binds it with `attach` or
`run` -- and makes the binding enforceable by giving each session its own
credential, because the daemon serves one shared token over HTTP and
otherwise cannot tell which terminal a request came from. Worktree binding
stays as the fallback for writers, so nothing in M4 has to change.

- [x] Accept ADR 0004 (accepted 2026-09-03 after two review rounds: four
  contract gaps closed, then the actor matrix, the legacy mode, invalidation,
  the wire format, attach ambiguity and the binding lifecycle confirmed).
- [x] `luciazero-agentd terminal list`: provider processes with tty, pid,
  start time, cwd, and the agent bound to each (read-only). New module
  `procinfo.py`: `ps` everywhere, `lsof -d cwd` on macOS and `/proc` on
  Linux. It keeps the top-level provider process per terminal by walking the
  whole ancestor chain, because `codex` spawns a code-mode host which spawns
  further `codex` processes on the same tty -- one level of parent was not
  enough and showed one window four times.
- [x] `attach` and `run` (spawn with the binding in place; `run` is reused by
  the M6 dispatcher), plus `detach`, `whoami`, and `sessions`. `attach`
  prints a credential so it refuses a pipe, as `approve` does; `run` never
  prints one, which is why automation uses it. Note for anyone extending
  `run`: its command is an `argparse.REMAINDER`, so every flag must precede
  the `--` and the separator itself has to be stripped.
- [x] Schema v3: session credentials (`lzsc_<32hex>`, sha256 at rest) bound
  to one `binding_id` and one `agent_id`, presented in `Authorization:
  Bearer` in place of the daemon token, resolved at MCP `initialize` and
  re-read on every request. Bindings live in their own table: SQLite cannot
  widen the `state` CHECK of the reserved `sessions` table by ALTER, and that
  table keeps its M5/M6 job of naming provider sessions for resume. Partial
  unique indexes give one live binding per agent and one per terminal.
- [x] Enforce the actor-field matrix of ADR 0004: the daemon fills and checks
  `agent_id`, `sender`, `created_by` and `produced_by`, leaves `recipient`,
  `assigned_to` and read-only queries alone (`worktree_get` on a peer must
  keep working), and refuses a contradiction with `IdentityMismatch` plus a
  `session.identity_refused` event; the `lzsc_` shape joined the strict
  redaction tier. `tools/list` drops the actor field from `required` on a
  verified session, so a bound model is not asked for what the daemon
  supplies.
- [x] Binding lifecycle: `detach`, revoked and stale states, invalidation of
  the pinned `Mcp-Session-Id`, reaping by pid plus start time on every
  resolve and human command, absolute credential expiry. A credential that
  was revoked, expired, rebound or swapped for another one gets 401 on the
  next request, not at the next initialize.
- [x] `--allow-unattributed`: without a credential a session is `unverified`,
  every event records `trust` (`bound`, `human` or `asserted`, never absent),
  and both status printers say so on the agent's own line.
  `test_the_flag_changes_what_is_permitted_not_what_is_claimed` asserts the
  invariant on both settings.
- [x] Read-only `agent_whoami` tool (16 tools now) and a `/lucia-bus` step
  that asks the daemon who it is instead of being told. On an unverified
  session it answers `verified: false` with the reason and the command that
  fixes it, and never guesses -- not from the worktree, not from the process
  table, not from the only registered agent.
- [x] Document the reconnect limit: a session already running on the shared
  token cannot be remapped in place (`docs/agent-bus.md`, the attach output
  itself, and ADR 0004).
- [x] Independent adversarial review of the implementation (two `reviewer`
  agents, security and contract routes; 5 distinct majors, 1 minor, all
  fixed): `status()` called an agent verified from a binding row alone, so a
  dead or expired terminal stayed "verified" until some other path happened
  to reap it -- `binding_of` now applies the same expiry and liveness test as
  the wire, and reports without writing so a read-only status view stays
  read-only; the claude branch of `run` put the credential in the child's
  argv, readable through `ps` by any local user for the life of a session, so
  it now writes a `0600` config file and removes it on exit; a provider that
  failed to spawn left a live credential for its whole TTL; a `SIGTERM` to
  `run` skipped cleanup entirely and orphaned the child with a working
  credential (both now revoke, and the child is terminated then killed); the
  liveness check shelled out to `ps` on every authenticated request and a
  missing or slow `ps` raised through the auth path instead of refusing, so
  it now fails closed and caches the start time for five seconds. The ADR's
  event names (`session.stale`) did not match the code (`binding.stale`); the
  ADR follows the code. Four regressions added, suite 152 -> 156 tests.
- [x] The user's decision on whether a binding is required by default: yes,
  taken 2026-09-04, before M5, because dispatch is built on identity and the
  base cannot be a bus where agents may wear each other's names. The daemon
  now refuses acting calls from unverified sessions, `serve
  --allow-unattributed` is the human opt-in for the old behaviour, and
  spending an approval needs a binding whatever that flag says (M6's managed
  dispatch joins it there). The M4 slice runs on the new default: the driver
  binds all three agents and its outcome assertion now fails if any write
  carries `trust: asserted`, if fewer than three terminals were bound, or if
  any session was refused for naming a peer. Suites that exercise the
  protocol rather than identity opt into the legacy mode explicitly. Sessions
  already connected with the shared token must reconnect or restart.

Exit gate:

```bash
./test.sh --agent-bus-store       # 161 tests, includes the identity suite
./test.sh --agent-bus-security    # M3 + M4.5 fixtures on their own
```

Two sessions on one machine must not be able to act as each other, and a
model that names a peer's id must be refused with the event recorded. The
invariant that outranks the rest: `--allow-unattributed` decides only whether
an unattributed request is permitted, never how it is labelled, so an
unverified session must never be reported as having a proven identity.

### M5 — Task orchestration and artifacts (complete 2026-09-04)

Order between tasks lived in the models' heads until here: the architect
created a verify task and hoped nobody claimed it before the fix existed.
Nothing bounded a conversation or a task, and an artifact was never cited as
the evidence for a result. ADR 0005 records the contract; M6 builds automatic
dispatch on top of it, which is why the limits land before the dispatcher and
not after.

- [x] Unblock dependent tasks transactionally when prerequisites complete.
  Completing the last prerequisite opens the dependent inside the same
  transaction, proved by a kill between the two writes
  (`test_completion_and_unblocking_commit_together`) rather than by an
  assertion about ordering. A prerequisite that ends `blocked`, `cancelled`
  or `exhausted` blocks its dependents instead, cascading down the graph: a
  task waiting on work nobody will finish is stuck, not waiting.
- [x] Detect dependency cycles before committing a task graph.
  `task_graph_create` builds a whole plan in one transaction and refuses a
  batch containing a cycle before the first insert (Kahn, with the cycle path
  in the message). Edges are immutable and a single `task_create` may only
  depend on tasks that already exist, which is what makes the check complete
  instead of best-effort.
- [x] Enforce a maximum hop count and conversation TTL. `hop_count` is now
  measured by the daemon -- how many messages the `correlation_id` already
  carries -- because a sender that sets its own could reset a loop to zero
  forever; counting messages rather than `reply_to` depth bounds a loop whether
  or not the models thread their replies. Past 32 hops, or 24 hours, the send
  is refused and recorded as `conversation.hop_limit` / `conversation.expired`.
  A reply inherits its parent's conversation, and a `correlation_id` that
  contradicts the parent is refused: review found the cap escapable by
  threading with `reply_to` alone (96 replies, no refusal) while the ADR
  claimed the stopper was not opt-in.
- [x] Reference commits, reports, patches, logs, and Lucia Relay manifests as
  artifacts. Kinds shipped in M3; M5 adds the provenance that makes them
  evidence: a `trust` column filled from the publishing session, `artifact_list`
  by task or producer, and `task_complete(artifacts=[...])` citing ids that must
  already exist. Citing never rewrites production, and a stopped task takes no
  new artifacts while a finished one still accepts a late report.
- [x] Add per-task time, turn, token, and cost budgets where providers expose
  the necessary measurements. `seconds` and `turns` are measured by the daemon
  and cannot be under-reported; `tokens` and `cost_usd` can only come from the
  provider, so `task_record_usage` is additive-only, accepted only from the
  agent holding the claim, and every report keeps the reporting session's
  trust. An unknown dimension is refused rather than
  ignored.
- [x] Stop automatic dispatch when a budget or retry limit is reached. A spent
  budget is a stop: the task becomes `exhausted`, its queued messages are
  dead-lettered, its dependents are blocked, and the send or claim that hit the
  limit is refused -- with the stop committed even though the call fails, so a
  retry cannot spend it again. M6's dispatcher must treat `exhausted` as
  terminal. Delivery-level retry limits (`deliveries.attempts`,
  `max_attempts`) stay reserved for M6: nothing retries by itself in the pull
  beta, so a retry limit here would be a number nothing could reach.
- [x] Schema v4 rebuilds `tasks` for the two new states (`waiting`,
  `exhausted`), which SQLite cannot add to a shipped CHECK by ALTER, and adds
  the `task_deps` edge table plus `artifacts.trust`. `Store.migrate` now runs
  every migration with `foreign_keys` off and a `foreign_key_check` before the
  commit, so a rebuild that left `artifacts.task_id` or `approvals.task_id`
  dangling fails the migration instead of shipping.
- [x] The tool contract grows from 16 to 20 tools (`task_get`,
  `task_graph_create`, `task_record_usage`, `artifact_list`), `/lucia-bus`
  learns that a `waiting` task cannot be claimed and that a budget stop is
  final, and both status printers gain a per-state count and a line per
  stopped task -- a task nothing will resume must not vanish from the only
  view a human reads.

Exit gate:

```bash
./test.sh --agent-bus-workflow   # green 2026-09-04
./test.sh --agent-bus-store      # 193 tests, includes the workflow suite
```

A deterministic fake-provider scenario must execute a dependency graph,
reject a cycle, stop an infinite reply loop, and preserve artifact provenance.
The gate run does all four through the shipped daemon: the cycle is refused
with nothing written, `fix -> verify -> report` executes in order with each
task opening exactly when its own prerequisites complete, a reply loop stops
at the hop cap, a spent turn budget stops a task and blocks its dependent, and
the commit the implementer published still names the implementer after the
reviewer cites it. It also fails if any write in the run carries
`trust: asserted`, so M4.5's invariant keeps holding here.

### M6 — Dispatcher and provider adapters (complete 2026-09-04)

The bus stops being a queue somebody reads and becomes a thing that runs
models. ADR 0006 states the constraint before the design: managed dispatch
adds no path around terminal binding, identity, or approval provenance, and a
task M5 stopped stays stopped. The dispatcher core, its records, the offline
gate, both provider adapters, the live smoke gate, and the kill-at-commit
matrix are done: on 2026-09-04 a real `codex` turn and a real `claude` turn
were started by the dispatcher and each did the whole bus procedure with its
own bound session.

- [x] Define one adapter contract for start, resume, cancel, status, and event
  streaming (`adapters.py`: `TurnRequest`, `TurnResult`, `Adapter`, and
  `ProcessAdapter`, which runs any command and is what the offline gate uses).
  An adapter never touches the database, so it cannot invent progress.
- [x] Codex adapter: threads start with `approvalPolicy: "on-request"` and the
  adapter answers approval requests per the policy the user chose when they
  enrolled the worker -- `deny` (the default, refuse and let the turn report),
  `workspace`, or `accept`. `"never"` is not used: ADR 0001 null result 3
  recorded that it fails a model-selected MCP tool call before it reaches the
  bus. Every answer is written to the run log with the policy that produced it.
- [x] Claude adapter: the bus goes through `--mcp-config` with
  `--strict-mcp-config`, so the user's own MCP configuration is never read or
  written, and `--allowedTools` pre-allows the bus and nothing else. The
  credential is in that config file at `0600` and is deleted when the turn
  ends, however it ends; it is never on the command line, because argv is
  world-readable through `ps`. Both `--allowedTools` and `--mcp-config` are
  variadic, so each is followed by a single-value option and the prompt comes
  last -- ADR 0001 recorded the swallowed prompt.
- [x] Implement the Codex App Server adapter (`appserver.py`: JSON-RPC on a
  private stdio child, every step bounded by the turn's own timeout, the child
  and its children stopped as a process group).
- [x] Add `codex exec resume` as a tested fallback, selected by naming `exec`
  in the worker's command. It cannot answer an approval request, and says so.
- [x] Implement the Claude print-mode resume adapter: `--output-format json`
  names the session the turn ran in, and that is what the next turn resumes.
- [x] Stream provider output into bounded run logs (`runlog.py`), routed
  through `luciazero_agentd.redact.Redactor` with the daemon token and the
  run's own credential as literals before anything is written, `0600`, head
  and tail kept with the dropped byte count named.
- [x] Add lease acquisition, renewal, expiry, and generation fencing on the
  columns reserved in M1. Taking a session lease bumps the session's
  generation; a write from a stale generation is refused with
  `GenerationFenced`.
- [x] Renew the session lease only while the owned process is alive, with the
  same fail-closed liveness test M4.5 uses. A lease also dies when the process
  holding it is gone, which is what makes a killed dispatcher recoverable in
  seconds instead of at the end of a TTL.
- [x] Prevent concurrent resume of the same provider session: the lease is the
  record, not the dispatcher's care, and a second holder is refused.
- [x] Add retry limits and dead-letter transitions: `attempts` is counted
  before the provider starts, so a killed dispatcher costs one attempt rather
  than none, and the delivery reaches exactly one outcome.
- [x] Distinguish retryable provider errors from permanent configuration
  failures: a missing binary, an unusable command, or a provider with no
  adapter dead-letters at once; a non-zero exit or a timeout retries.
- [x] Recover orphaned `dispatched`/`processing` deliveries after a restart,
  and revoke the credential the orphaned provider still holds -- a killed
  dispatcher skips its own cleanup, which is the same defect the M4.5 review
  found in `run`.
- [x] Managed turns are bound sessions: the dispatcher mints a `managed`
  binding per turn and revokes it when the turn ends, and `bind_terminal`
  refuses a managed binding on an agent a human terminal holds, so ADR 0001's
  ownership rule is a property of the records.
- [x] The dispatcher never acknowledges a delivery or completes a task for a
  worker. A turn that exits cleanly without touching the bus is a failed
  attempt, which is what stops a dispatched turn from manufacturing a result
  nobody produced.
- [x] `trust` gains `system` for the dispatcher's own bookkeeping: borrowing
  `human` would make the log say a person did what a machine did.
- [x] Human commands: `worker add|list|pause|resume|remove` and `dispatch`
  (`--once`/`--watch`), plus worker and running-turn lines on both status
  printers. Enrolling a worker is the decision to let a machine start turns,
  so no bus tool can make it.
- [x] A worker command may not carry the flags the dispatcher sets for it, and
  may not end in an option still waiting for a value. Both CLIs let a repeated
  flag win or accumulate, so `--dangerously-skip-permissions` in a command
  would have overridden the policy chosen at enrolment, and `claude --model`
  would have swallowed the `--mcp-config` that follows it -- ADR 0001's
  swallowed-prompt trap. Refused at enrolment, and again before a turn starts.
- [x] `workspace` is a narrower policy than `accept`, in the answer (nothing
  that asks to leave the sandbox, nothing naming a path outside the turn's own
  directory) and in the sandbox the thread runs in (`read-only` for `deny`,
  because a write inside the workspace raises no approval at all).
- [x] The policy a turn ran under is recorded on the run, so re-enrolling the
  worker later cannot rewrite what governed a turn that already ended.
- [x] One live smoke gate, green for both providers on 2026-09-04: a real
  Codex turn and a real Claude turn started by the dispatcher, each reaching
  one completed logical outcome in one attempt, with the worker itself
  acknowledging the delivery, claiming and completing the task, and messaging
  the architect back -- and no credential, lease, or turn directory outliving
  the turn. `./test.sh --agent-bus-live --spend-quota` refuses to run without
  that flag and is never part of `--full`; `--rehearse` runs the identical gate
  against the offline worker and spends nothing.

  The first Codex run cost a turn for nothing: the gate failed on an assertion
  of its own that could never have passed -- it filtered events on
  `actor_agent_id`, a column the events table does not have -- while the turn
  itself had completed the whole procedure. `--rehearse` exists because of
  that: a gate that costs money proves its own assertions first.
- [x] Test process crash and restart during every delivery transition,
  including `dispatched` and `processing`. `tests/test_crash.py` now kills the
  process at each commit point of the dispatch transitions the way M1 did for
  the pull beta: `begin_turn` (nothing before, the attempt and the run together
  after), `finish_run`, `record_run_process`, `record_provider_session`,
  `acquire_lease`, `release_lease`, `dead_letter_delivery`, and -- the one that
  matters most -- every point inside recovery, which is three transactions
  (release the lease, revoke the credential, settle the run) and so can be
  interrupted half way. After a kill at any of those six points the next
  recovery finishes the job: exactly one outcome, the attempt counted once, no
  credential and no lease outliving the dispatcher, and running recovery again
  changes nothing. The attempt limit still holds across crashes: a killed turn
  costs one attempt, and the second one dead-letters. Made red first by
  removing the credential revocation from recovery, which fails four of the six
  points with `'active' != 'revoked'`.
- [x] Independent adversarial review of the dispatcher core (two `reviewer`
  agents, semantics and security routes; 2 blockers, 3 majors, 1 minor, all
  fixed with regressions): counting the attempt and recording the run were two
  transactions, so a kill between them stranded the delivery in `dispatched`
  where neither recovery nor dispatch could see it, with an attempt spent --
  they are now one transaction, and a sweep settles any delivery left mid-turn
  with no live run; the lease TTL was a fixed five minutes while a turn may run
  for up to two hours, so a second dispatcher could reclaim the session
  mid-turn and run a concurrent one -- the lease now outlives the turn it
  covers and settlement is fenced on it; a `SIGTERM` to `dispatch` skipped
  every cleanup and left an orphaned provider holding a live credential, the
  same defect M4.5 fixed in `run`; an exception anywhere in a turn took the
  whole loop down and left the run `running`; run-log redaction was applied per
  chunk, so a secret printed across two lines survived in the clear. The minor:
  `hasattr(args, "command")` is always true because argparse's own subcommand
  dest is `command`, so the provider-command override was scoped by accident
  rather than by design.

Exit gate:

```bash
./test.sh --agent-bus-dispatch   # green 2026-09-04 (dispatcher core, fake provider)
./test.sh --agent-bus-store      # 322 tests, includes the dispatch, adapter and watcher suites
./test.sh --agent-bus-live --rehearse       # the same gate, offline worker, no quota
./test.sh --agent-bus-live --spend-quota   # green 2026-09-04 (codex and claude, real turns)
```

The suite must kill the dispatcher during a run, restart it, and show that the
message reaches one completed logical outcome without concurrent session use.
Expired leases must be recoverable and stale generations must be fenced. The
gate run does all of it: a turn is killed with `SIGKILL` while its provider is
running, a second dispatcher is refused the lease while the turn is in flight,
the next dispatcher abandons the run and revokes the orphan's credential, the
work completes on the retry at exactly two attempts, a turn that exits cleanly
without touching the bus is recorded as a failed attempt, a stale generation is
fenced, and a lease whose holder is gone is reclaimed rather than waited out.
It also fails if any write carries `trust: asserted`, if the worker's writes
are not `bound`, or if a lease or managed credential outlives its turn.

Slice B added `./test.sh --agent-bus-store` coverage for the adapters
themselves (`tests/test_adapters.py`, 26 cases): the exact command each
provider gets and the variadic-option traps in it, the credential never
reaching argv or the environment where it is not needed, the config file gone
after success, failure, timeout and spawn failure, a provider's own children
dying with the turn, the exit-to-outcome mapping, session ids recorded for
resume, the App Server handshake and approval policy against a scripted
server, and a turn's private directory removed when it ends and swept on
recovery. Every fake CLI is a script the test writes: no test starts a real
`codex` or `claude`, so the suite spends no quota and touches no provider
state.

Independent adversarial review of the adapters (one `reviewer` agent, security
and contract routes; 3 majors, 3 minors, all fixed with regressions proven red
first): `workspace` and `accept` answered every execution approval identically,
which made the middle tier decoration -- and the sandbox was `workspace-write`
for every policy, so even a `deny` worker could edit freely, because a write
inside the sandbox raises no approval; recovery signalled the one recorded pid
rather than the orphan's process group, leaving exactly the children
`start_new_session=True` exists to reach; and a denylist of dangerous flags
could not stop a worker command ending in an unpaired option from swallowing
the flags appended after it. The minors: a structural App Server protocol
mismatch retried until the attempts ran out instead of failing at once, the
App Server path dropped the worker's own arguments without saying so, and a
`prepare` that failed in a way other than `OSError` would have skipped the
credential cleanup.

The live proof of one managed turn per provider is the smoke gate above, green
on 2026-09-04. The multi-turn, multi-agent proof belongs to M7.

### M7a — Watching the conversation (done 2026-09-04)

Built before the vertical slice because the slice cannot be observed without
it: in the pull beta there is no third place where an exchange between two
agents can be seen, which is also why the wait a user-started turn costs was
being reconstructed from memory instead of watched.

- [x] `luciazero-agentd watch` follows messages and delivery transitions live,
  opening the database `mode=ro` and acknowledging nothing.
- [x] `luciazero-agentd chat` picks the pair and prints the command for each
  terminal, skipping bindings whose terminal has already been closed.
- [x] `--auto` prints the managed-dispatch version instead, and
  `dispatch --max-turns N` caps the spend in turns rather than in passes.
- [x] Regressions (32): the read-only handle refuses to write, a full watch
  cycle leaves every row of `messages`, `deliveries` and `events` byte-identical,
  a restarted follower repeats rather than skips, a poll that fails reconnects,
  the follower keeps reading across a writer restart of a live WAL database,
  and peer text cannot repaint the pane. Proven red first by opening `mode=rw`
  and by disabling the priming pass.

The watcher shows traffic; it cannot wake a session. That limitation is the
reason M7 exists.

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
- [x] Infinite agent-to-agent loops terminate at a budget, TTL, or hop limit.
  (M5, 2026-09-04: 32-hop cap, 24-hour conversation TTL, per-task budgets.)
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
