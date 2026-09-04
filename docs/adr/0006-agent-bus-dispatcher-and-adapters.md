# ADR 0006: Agent Bus dispatcher, leases, and provider adapters

Status: accepted 2026-09-04 for milestone M6 (the dispatcher core; the Codex
and Claude adapters land under it)

## Context

Through M5 the bus removes message copying but not the trigger: a task only
moves when the user starts a session and that session runs `/lucia-bus`. The
pull beta's own decision gate names this as the blocking cost. M6 adds the
dispatcher that starts those turns, which means the bus stops being a queue
somebody reads and becomes a thing that runs models on its own.

That is a different risk class. Everything the previous milestones built --
one worktree per writer (M3), a proven identity per session (M4.5), a budget
that stops a task (M5) -- exists so that an agent making a mistake cannot do
unbounded damage. A dispatcher that resumed sessions outside those rules would
undo all of it in one step, so the constraint on this milestone is stated
before the design: **managed dispatch adds no path around terminal binding,
identity, or approval provenance, and treats a stopped task as stopped.**

## Decision

### The dispatcher is a separate process, not a thread in `serve`

`luciazero-agentd dispatch` opens the store directly, the way the human CLI
already does, and spawns provider processes. It is not part of the MCP daemon:
the exit gate kills the dispatcher mid-run and restarts it, and a crash in the
thing that spawns models must not take down the bus that everything else is
talking to. Two dispatchers cannot double-run a worker because dispatch
requires a lease, not because only one process is expected to exist.

### A managed worker is a bound session, minted the same way `run` mints one

The dispatcher does not get a new identity path. For each turn it mints a
binding with `ownership = "managed"` and hands the credential to the child
exactly as `luciazero-agentd run` does -- a `0600` config file for Claude, the
environment for Codex, never argv -- and revokes it when the run ends, however
it ends. Consequences, which are the point:

- a managed worker's tool calls carry its own credential, so the daemon fills
  and enforces its actor fields; it cannot act as a peer;
- a managed worker cannot spend an approval it was not handed, because
  `approval_consume` still requires a binding *and* a nonce, and a nonce still
  comes only from the user's own terminal. The dispatcher never holds, mints,
  or forwards one. A run that needs approval ends `blocked` and waits for a
  human, which is the same answer the pull beta gives;
- the shared daemon token is never given to a worker.

Human-owned sessions stay out of reach: an agent with a live `human` binding
is skipped, per ADR 0001's ownership rule. Ownership is not a flag the
dispatcher can flip.

### The dispatcher gets its own trust label

ADR 0004 gave every event a `trust` of `bound`, `human`, or `asserted`. The
dispatcher's own bookkeeping -- delivery transitions, run records, lease rows
-- is none of those. Borrowing `human` would be exactly the lie M4.5 exists to
prevent, so a fourth label is added: `system`, meaning the daemon's own
machinery acting on its own records. The invariant is unchanged and now reads:
`bound` for a credentialed session, `human` for the user's own commands,
`system` for the daemon's machinery, `asserted` for anything unproven. No
label ever means "we believe the caller".

### The worker finishes its own work; the dispatcher only records the run

The dispatcher moves a delivery `queued -> dispatched -> processing` and
records a run. It never acknowledges or completes a delivery, and never
completes a task, on a worker's behalf: those are the worker's own claims and
must carry the worker's own identity. When a provider turn ends, the
dispatcher looks at what the worker actually did:

- the worker moved the delivery on -- the run is `completed`;
- the delivery is untouched -- the attempt failed, and the run says so.

This is what keeps a dispatched turn from manufacturing a result nobody
produced.

### Leases and generation fencing

A turn needs a lease on the worker's session (`leases`, `kind = 'session'`,
`resource_id` the agent id, unique per resource). Acquiring one bumps
`sessions.generation`, and every write a run makes carries the generation it
acquired; a stale generation is refused (`GenerationFenced`) -- including the
run's own settlement, so a turn whose lease was reclaimed cannot settle a
delivery somebody else is now working. A lease is renewed only while the owned
process is alive -- the same fail-closed liveness test M4.5 uses, so a dead
provider cannot hold a worker hostage -- and an expired lease can be taken by
the next attempt, which fences the old one.

The lease a turn takes outlives the turn: its TTL is the worker's own turn
timeout plus a margin. Review found the fixed five-minute TTL, which any
legitimately longer turn outlived, letting a second dispatcher reclaim the
session and start a concurrent turn against it. A long TTL costs nothing
because a lease whose holder process is gone is reclaimed at once regardless of
how long it had left.

This is what makes "no concurrent resume of the same provider session" a
property of the records rather than of the dispatcher's own care.

### Retryable failures, permanent failures, and dead letters

- **Retryable**: the provider exited non-zero, timed out, or the transport
  broke. The delivery returns to `queued` as `retryable_failed`, `attempts`
  grows, and the next attempt may run. Past `max_attempts` it is dead-lettered.
- **Permanent**: the provider binary is missing, the worker is not on the
  roster or is disabled, the binding was refused, or the work is moot -- the
  task is `completed`, `cancelled`, or `exhausted`. These dead-letter at once,
  because retrying a configuration error is a loop with a bill attached.

M5's stop is honoured here: a delivery whose task is `exhausted` is
dead-lettered, never run. That is the concrete form of "the dispatcher must
respect a stopped task".

### Recovering a killed dispatcher

Counting the attempt and recording the run that covers it happen in one
transaction (`begin_turn`). Review found the two-call version: a kill between
them -- or a lease that expired in the window -- left the delivery
`dispatched` with no run, invisible to recovery (which scans runs) and to
dispatch (which scans queued work), with one attempt silently spent.

Recovery runs every pass, not only at startup, and settles both shapes of loss:
runs whose lease is dead (`recover_runs`), and deliveries left mid-turn that no
live run covers (`recover_deliveries`). The attempt is counted, and the delivery
returns to `queued` or dead-letters. A kill at any point leaves at most one
attempt to account for, and the delivery reaches exactly one logical outcome.

A dispatcher that is asked to stop cleans up after itself: `SIGTERM` stops the
provider it started and unwinds the turn, because without that a `kill <pid>`
leaves an orphaned provider holding a live credential -- the same defect the
M4.5 review found in `run`.

### Run logs are bounded and redacted before they are written

Provider output is streamed into `runs/<run_id>.log` in the state directory,
`0600`, capped in size (head and tail kept, the middle dropped with a marker),
and every chunk passes through `luciazero_agentd.redact.Redactor` with the
daemon token and the run's own credential as literals. ADR 0003 put provider
output inside the redaction contract before any adapter existed; this is where
that promise is paid.

### One adapter contract, two implementations

An adapter is `start`, `resume`, `cancel`, `status`, and an output stream,
over one dataclass of run parameters. The daemon ships:

- **Codex**: App Server over a private stdio child (`thread/start` with
  `approvalPolicy: "on-request"`, then `turn/start`; `thread/resume` for a
  later turn). `"never"` is not used: ADR 0001's null result 3 records that it
  fails a model-selected MCP tool call before it reaches the bus. `codex exec
  resume` stays the tested fallback.
- **Claude**: `claude -p --resume <session>` with the bus passed through
  `--mcp-config` and `--strict-mcp-config`; the user's own MCP configuration
  is never written.

A `FakeAdapter` implements the same contract deterministically and is what the
offline gate runs, so the dispatcher's own logic is provable without quota.

## Consequences

- New schema: `workers` (which agents may be dispatched, with their command
  and limits) and a rebuilt `runs` (it was reserved and empty). `leases` and
  `sessions.generation`, reserved since M1, come into use.
- New commands: `roster worker` to enrol a managed worker, and `dispatch`
  (`--once` / `--watch`).
- `trust` gains `system`; the M4/M5 gates that refuse `asserted` writes are
  unaffected.
- The exit gate is `./test.sh --agent-bus-dispatch`, offline, with the fake
  adapter: kill the dispatcher during a run, restart, and show one completed
  logical outcome, an expired lease recovered, and a stale generation fenced.
- Real provider turns stay out of CI, as in M4: the live proof of managed
  dispatch is M7's slice.

## Threat model

Unchanged in kind from ADR 0003 and ADR 0004 -- cooperative agents, one
machine, one user -- with one addition that matters: until now a mistaken
agent burned a turn the user had started, and now the machine starts the
turns. The mitigations are the ones already built (per-task budgets, the hop
cap, worktree isolation, approval provenance) plus `max_attempts` and the
lease. What is explicitly *not* claimed: the dispatcher does not make a
malicious provider safe, and it does not bound spend on a task that carries no
budget. Enrolling a managed worker is a human act, and so is minting the
approval that lets one do something sensitive.

## Alternatives considered

- **Run the dispatcher inside `serve`.** Fewer moving parts, but a model-
  spawning loop crashing would take the control plane with it, and the exit
  gate's "kill the dispatcher, keep the bus" would be untestable.
- **Let the dispatcher complete deliveries and tasks for a worker.** Simpler
  bookkeeping, and it would let a turn that did nothing look like a turn that
  worked. Rejected: the result would carry the dispatcher's word for it.
- **Give workers the shared daemon token.** Rejected outright by M4.5: it is
  precisely the state where the daemon cannot tell which terminal a request
  came from.
- **Skip leases and rely on one dispatcher existing.** Rejected: "there is
  only one" is an assumption, not a record, and a stale process is exactly the
  case where it is false.
- **Reuse the `human` trust label for dispatcher writes.** Rejected: it would
  make the audit log say a person did something a machine did.
- **Scrub run-log output chunk by chunk as it arrives.** It was the first
  implementation and review broke it in one line: a provider that prints a
  secret across two lines defeats it, because neither half matches. Redaction
  now runs over each whole buffer at close and again tolerating whitespace
  inside a secret, and the cap drops a margin either side of the gap so a
  secret split by the drop loses a half outright.

## Rollback

Nothing dispatches until a worker is enrolled and `dispatch` is run, so a
bus with no managed workers behaves exactly as it does in M5. Rolling back is
removing the workers, which returns every agent to the pull beta.
