# ADR 0007: Agent Bus managed vertical slice: chaining, resume, recovery

Status: proposed 2026-09-04, recorded 2026-09-05, for the roadmap milestone
"M7 — Managed-dispatch vertical slice". Amended 2026-10-08 and still
proposed: the M4 decision gate is resolved, and one root allowance per
managed flow replaces the inherited remainder.

Not M7a through M7f. Those were written and shipped between this ADR's
proposal and its recording, under the same number and about a different
subject: making the bus usable without somebody minding it — watching a
conversation, identity without `run`, a dialog instead of a copied code, a
public command, a daemon that outlives its window, and a session that gets
knocked on when a delivery arrives. None of them touches managed dispatch, and
nothing in this ADR was implemented by them. What is designed here is still
entirely ahead.

## Context

M6 proved one managed turn per provider: the dispatcher started a real Codex
turn and a real Claude turn, each did the whole bus procedure with its own
bound session, and the crash matrix showed that a killed dispatcher settles to
exactly one outcome. That is one delivery, one worker, one turn.

M7 is the flow: three agents, six turns, and no user starting any of them. The
outcome flow at the top of the roadmap runs to the end while the person who
asked for it is not in the loop. Three properties that were free at one turn
stop being free across a flow.

- **The trigger.** In the pull beta and in M6 the next turn happens because
  something already exists to dispatch. Across a flow, the next turn has to be
  created by the previous one, and today the only thing that creates it is a
  model choosing to call `message_send`. A turn that does its work correctly
  and forgets the message leaves a flow that is stalled with every record
  green.
- **The memory.** A worker's turn is a fresh model context. What it knows is
  what it reads from the bus. Provider session resume (`thread/resume`,
  `claude --resume`) carries some of the previous turn's context, which is
  useful and must never be load-bearing: a session that rotates mid-flow must
  cost efficiency, not correctness.
- **The failure surface.** M6 recovers a turn. A flow can also fail between
  turns — after the work is done and before it is reported, after the report
  and before the next task is queued — and it can fail by never ending: a
  machine that starts turns can keep starting them.

There is also a precondition that is not technical. The decision log
(`docs/agent-bus-decision-log.md`) records that the M4 decision gate was passed
by rather than met: M5 and M6 shipped before its evidence existed, and until
one of its three ways out was recorded, M7 had no baseline. The evidence was
recorded later -- seven workflows by 2026-09-07 and the second qualifying
retro on 2026-09-09 -- and on 2026-10-08 the user accepted it as M7's
baseline and amended the gate's "before M5 starts" condition rather than
counting it as met. This ADR designs M7; it does not authorise starting it.
The section "What must be true before the live slice runs" states the order.

## Decision

### A ready task queues its own delivery

Completing a task already opens the tasks waiting on it (`_settle_dependents`,
`task.unblocked`). Nothing else happens: the dispatcher scans deliveries
(`dispatchable_deliveries`), so a task that became ready through the graph is
invisible to it. Under managed dispatch the M5 task graph is therefore inert —
the graph knows the flow's shape and the dispatcher cannot see it.

The fix is one rule: **when a task becomes claimable and its assignee is an
enabled managed worker, the daemon queues a `task` delivery to that assignee,
in the same transaction that made it claimable.** That covers both entries into
claimable — a dependent unblocked by `_settle_dependents`, and a task created
already `open` with an assignee.

- The delivery is the daemon's own: sender is the daemon, `trust` is `system`
  (ADR 0006), and the payload carries the task id and nothing else. It is not
  a message from a peer and must not read as one.
- It is idempotent on the task and the readiness that produced it, so replaying
  the transition — a retried batch, a recovery pass — queues one delivery, not
  two.
- It is scoped to enabled managed workers on purpose. An agent nobody enrolled
  sees no change at all, so the pull beta's records are byte-identical and the
  M4 gate's message and delivery counts still hold. The narrower rule is also
  the honest one: queuing work at an agent that only exists when a human opens
  a terminal is not delivery, it is a note.

What this buys: the flow advances because the graph says it is ready, not
because a model remembered its manners. A `message_send` between agents stays
exactly what it was — evidence, findings, and context for the next turn — and
stops being the mechanism. When both exist for one task the worker sees two
inbox items for one piece of work, which is the re-entrancy case below and is
handled there.

### A stalled flow is a state the records can name

Because no component owns "the flow", nothing detects that it stopped. The
detector is a query, not a process: a task graph with an unfinished root, no
task in `claimed`, no dispatchable delivery, and no live run is stalled. It is
reported by `bus status` and asserted on by the exit gate, which must end with
that set empty.

This is deliberately a read, not a repair. Restarting a stalled flow means
starting model turns on a judgement call about why it stopped, which is a
human decision — `luciazero-agentd cancel` and re-queuing stay the human
channel, as they were in M4.

### The records are the worker's memory; the provider session is a cache

A managed turn's prompt is built from bus records only: the delivery, the task,
the artifacts it references, and the worktree binding. It never contains a
summary of a previous turn written by the dispatcher, because a dispatcher that
summarised would be putting words in a worker's mouth — the same rule that
stops it acknowledging a delivery on a worker's behalf.

`sessions.provider_session_id` stays what it is: an optimisation that saves the
model re-reading its own context. The exit gate proves it is not load-bearing
by closing the session mid-flow — a full rotation, new provider thread, same
stable agent id, same open task — and requiring the flow to finish anyway.

### Every step of a managed turn is idempotent, keyed by the delivery

A retried turn is not a fresh turn. It may find its own half-finished work:
a task it already claimed, a commit it already made, an artifact it already
published. M6's guarantee is that the delivery reaches one outcome; M7 needs
the worker's side of that, or a retry duplicates side effects.

The rule for the `/lucia-bus` procedure and for every managed worker:

- Each side-effecting call carries `idempotency_key = <delivery_id>:<step>`,
  so `create_task`, `task_graph_create`, `artifact_publish` and `message_send`
  replay to the same record instead of a second one. The keys already exist;
  M7 makes using them mandatory on a dispatched turn rather than optional.
- Re-claiming a task the caller already holds is success, not a conflict, and
  the turn learns what it already did by reading — `task_get` for the claim
  and the result, `artifact_list` for what it published — never by remembering.
- Work outside the bus is made re-runnable the same way: the check is re-run
  rather than assumed, and a commit is recognised by looking at the worktree
  before making a second one.

This is a contract on workers, and the offline gate is what enforces it: the
rehearsal workers are killed part-way and re-dispatched at every step of their
own procedure, and the flow must still produce one artifact per step and one
message per step.

### The dispatcher counts the turn it starts against the task's budget

Today `spent.turns` is incremented inside `send_message`, when the payload
names a task. That was right for the pull beta, where a turn that sends nothing
is a turn a human paid for and stopped. Under managed dispatch it is a hole:
the machine starts a turn, the turn runs a model, and if it sends no message
the task's budget records nothing. The one budget dimension that could stop a
runaway machine loop is the one blind to the machine.

**`begin_turn` counts the turn**, in the transaction that already counts the
attempt and records the run. `send_message` keeps counting only for a turn no
dispatcher started, so `spent.turns` means "turns spent on this task" in both
worlds and never counts one turn twice. A dispatched turn that exceeds the
budget exhausts the task exactly as M5 says, and ADR 0006's rule already
refuses to dispatch a delivery whose task is exhausted.

### One root allowance per managed flow

A worker may create tasks. A machine-started chain that creates tasks with no
budget therefore mints itself a fresh allowance at every hop, and the 32-hop
cap is the only thing left standing.

Until 2026-10-08 this ADR answered that by letting a task created inside a
dispatched turn inherit the unspent remainder of its creator's budget. That
copies the remainder instead of dividing it: a task with five turns left could
create two children holding five each, and a worker that wrote an explicit,
larger budget was outside the rule altogether. The amendment replaces it with
one allowance per flow.

- **A managed flow has one budget root, and it is finite.** Each flow enrolled
  in chaining gets a root assigned by the host, with an explicit turn
  allowance; a flow without one is not chained. Pull-beta and M6 behaviour
  outside this opt-in is unchanged.
- **Every descendant keeps that root.** Worker-created tasks with explicit
  budgets, tasks in new conversations, graph fan-out and retries all draw on
  the same root. The host derives the association from the authenticated
  managed run, never from a caller's payload, so a worker cannot open a fresh
  root.
- **A task's own budget can only tighten.** It may stop a descendant before
  the root would; it cannot enlarge the root. Extending a root is a separate
  human act with its approval recorded. A number in a worker's message is not
  approval.
- **An attempt is charged before it launches.** `begin_turn` charges one
  provider-start attempt to the root in the transaction that records the run,
  its attempt id, the task's own accounting and dispatch ownership. Replaying
  that transaction charges once; a genuinely new retry is a new charge.
  Concurrent dispatchers see the same remainder, and once the root's allowance
  is spent no further attempt starts, whichever descendant or conversation
  names it. With an allowance of six a seventh attempt is refused; six is the
  slice's allowance, not a global limit. Creating a task spends nothing.
- **An unknown outcome is not refunded.** A charge permits one launch; it is
  not a token to launch again. Recovery never relaunches an unknown attempt on
  its old charge: it recovers the identified live process if there is one, and
  otherwise settles that attempt and admits any retry as a new charge. A crash
  between charging and a provable launch can therefore spend allowance without
  a turn, and a flow can stop after fewer completed turns than its allowance.
  That is the conservative direction, chosen on purpose.
- **Deadlines are absolute.** A child may shorten the root's deadline, never
  restart its clock. Task and root limits are checked in the same admission
  decision, and a refusal settles leases and credentials through the existing
  failure and recovery paths.
- **The two ledgers stay apart.** A task's own `spent` totals keep meaning
  that task; they are not relabelled as the flow's. The root's id, its charged
  attempts and its remaining allowance are new, additive fields, specified
  before implementation. Message-based accounting for undispatched turns stays
  scoped to the pull flow.

This bounds admitted provider attempts. It is not a monetary cap: tokens and
cost are reported after a provider has done the work, so they can stop the
next admission but not a turn already running. A hard dollar cap would need a
separately reviewed bound that the provider enforces; without one, spend is
reported, with a stop on later admissions.

### The exit gate is offline by construction, and live is one approved run

The offline gate runs the whole slice against rehearsal workers — real bus
clients with no model, one per role, extending `scripts/agent_bus_worker.py` —
so every assertion about chaining, recovery, rotation and budget is provable
with no quota and in CI. The live gate is the same driver with real providers
behind `--spend-quota`, and it exists to prove exactly one thing the fakes
cannot: that real models, reading only the records, carry a six-turn flow to
the end.

This is M6's `--rehearse` discipline applied a milestone earlier: a gate that
costs money proves its own assertions for free first. M6 paid a Codex turn to
learn that lesson from an assertion that could never have passed.

### What must be true before the live slice runs

In order, and none of them is a technical step:

1. The M4 decision gate is resolved in `docs/agent-bus-decision-log.md` — met,
   amended with a date and a reason, or stopped at the pull beta. M7's live run
   is the most expensive thing the bus does; running it on evidence the
   project's own gate does not accept is the failure mode the gate exists to
   prevent.

   Resolved 2026-10-08. When this ADR was recorded the ledger read 1 of 3
   workflows and 0 of 2 retros. It reached 7 workflows by 2026-09-07 and 2
   qualifying retros on 2026-09-09, with no open M3 finding, but only after M5
   and M6 had shipped. The user accepted that evidence as M7's baseline and
   amended the "before M5 starts" condition, with the date and the reason, in
   the decision log. The gate's ordering was missed and the log still says
   so; no replacement workflows were run, and the demo is not counted.
2. The offline gate is green on native Windows, macOS and Linux. Against
   model-free rehearsal workers it shows that:
   - three agents carry the six-turn flow to the end from bus records alone,
     and a fresh provider session midway costs efficiency, not correctness;
   - a task that becomes claimable for an enabled managed worker queues one
     system delivery in the same transaction, and a replay or recovery pass
     queues no second one;
   - each side-effecting worker step, killed and retried, leaves no duplicate
     artifact, message or commit, and the dispatcher acknowledges nothing on a
     worker's behalf;
   - concurrent children cannot each spend the root's remainder; explicit
     worker budgets, new conversations and new tasks cannot escape the root;
     and a spent root starts nothing;
   - a crash before or after charging, and before or after launch, leaves one
     charge per attempt, an unknown outcome admits nothing extra, and each
     real retry carries its own charge;
   - past the absolute deadline no provider starts, a child cannot reset the
     clock, and a task's own limit can stop it before the root does;
   - a stalled, human-blocked, cancelled, exhausted or failed flow is shown as
     what it is, stall detection starts no repair turn, and a human cancel
     stops the admitted provider tree through the platform's existing
     mechanism.
3. Quota approval is a human act with a number attached: at most six provider
   attempts across the two providers, the providers and billing mode written
   down, the root's allowance and deadline set before the run, no automatic
   refill and no invisible retry, and the run stopped by that allowance, with
   the stop recorded, rather than by a person watching it.

## Consequences

- New behaviour in the store: a claimable task assigned to an enabled managed
  worker queues a `task` delivery in the transaction that made it claimable,
  once per readiness.
- Turn accounting moves: `begin_turn` counts a dispatched turn; `send_message`
  counts only an undispatched one. Existing per-task budgets change meaning for
  managed work — they now bound turns actually run — and the M5 tests that
  count turns through `send_message` need the dispatched case added beside them.
- A managed flow carries one root allowance. `begin_turn` charges each
  attempt to it, every descendant task keeps the root, and reads gain the
  root's id, charged attempts and remaining allowance beside each task's own
  totals, not in place of them.
- `bus status` gains stalled flows. No new command: restarting a flow stays a
  human act through the existing cancel and re-queue path.
- A new gate tier `./test.sh --agent-bus-managed`, offline, in `--full`, run on
  native Windows, macOS and Linux, to be added by this work: `test.sh` today
  offers `--agent-bus-spike|store|mcp|security|e2e|workflow|dispatch|chat|live`
  and nothing named `managed`. The M4 tier and its assertions are untouched,
  which is the point of scoping the new delivery to enrolled workers.
- `docs/agent-bus.md` and the demo grow a managed section; `/lucia-bus` gains
  the idempotency and re-entrancy rules, since they bind every worker and not
  only the rehearsal ones. That last one is not free: the skill sits at its
  prompt budget exactly (607/607 words in `scripts/check-skill-prompts.py`
  after M7f gave it the duty to read the inbox unprompted and print what
  crosses the bus), so new rules there cost either words cut from what is
  written now or a budget raised on purpose.

## Threat model

Unchanged in kind from ADR 0006 — cooperative agents, one machine, one user —
with the addition that the machine now starts turns in sequence, so a mistake
propagates without a human between two of them. The mitigations are the ones
already built (worktree isolation, approval provenance, the hop cap, per-task
budgets, `max_attempts`, the lease) plus the two this ADR adds: a turn is
counted against the budget whether or not it speaks, and every task in a
managed flow draws on one root allowance that no worker can enlarge or
restart.

What is explicitly not claimed:

- The bus bounds provider attempts, not money. Usage is reported after a turn
  has run, so a turn in flight can cost more than any estimate. Chaining
  refuses a flow with no root allowance; outside chaining, an unbudgeted task
  is bounded only by the hop cap, `max_attempts` and a human `cancel`.
- A chain of correct-looking turns that is collectively wrong is not detected.
  The bus proves who did what, not that it was worth doing.
- Approval is unchanged and unchangeable: a managed turn that needs a nonce
  ends `blocked` and waits for a human. Chaining does not accumulate consent,
  and a peer's message still authorises nothing.

## Alternatives considered

- **Leave the chain message-driven, as M4 has it.** No schema change, and the
  M4 flow already works this way. Rejected: it makes the flow depend on a model
  remembering to send a message, and its failure mode is the worst one
  available — a stalled flow where every record is green.
- **Queue a delivery for every claimable task, enrolled worker or not.** More
  uniform, and it would give pull-beta agents their assignments in the inbox
  instead of making them poll `task_list`. Rejected for M7: it changes the
  message and delivery counts the M4 gate asserts, so it would mix a
  behavioural change into the milestone that is supposed to prove chaining. It
  is the better long-run shape and belongs in its own change.
- **Give the dispatcher a flow object to drive.** An orchestrator that knows
  the steps could detect a stall directly and restart it. Rejected: it puts the
  flow's truth in the dispatcher rather than in the records, and M6's recovery
  works precisely because the dispatcher is stateless about what it is
  starting. A stall stays a query over the graph.
- **Let the dispatcher summarise the previous turn into the next prompt.**
  Cheaper for the model. Rejected for the same reason the dispatcher may not
  acknowledge a delivery: it would be the dispatcher's account of a worker's
  work, presented to the next worker as fact.
- **Count turns by asking the provider.** Providers do report usage, and
  `record_usage` already takes tokens and cost from them additively. Rejected
  as the mechanism for the `turns` dimension: the daemon can measure a turn it
  started itself, and a limit that stops a runaway loop must not depend on the
  runaway process reporting honestly.
- **Copy the creator's remaining budget into each new task.** What this ADR
  proposed until 2026-10-08. Rejected: it copies an allowance instead of
  dividing it, so two children of a task with five turns left hold ten
  between them, and an explicit budget written by a worker sidesteps it.
- **Rely on the 32-hop cap for loop safety.** It is a real bound and it stays.
  Rejected as sufficient: it counts messages in one conversation, so a chain
  that creates tasks and starts fresh conversations walks past it, and 32
  machine-started turns is a large bill to call a safety limit.

## Rollback

Every piece is inert without enrolled workers. With none, no delivery is
queued by the new rule, `begin_turn` never runs, no root allowance is charged,
and the bus behaves exactly as it does in M6 and M5. Rolling back M7 is
removing the workers; rolling back the store change is reverting one
transaction's extra insert, which the M4 tier — untouched by design — will
show is safe.
