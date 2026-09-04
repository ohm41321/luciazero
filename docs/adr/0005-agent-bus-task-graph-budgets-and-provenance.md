# ADR 0005: Agent Bus task graph, budgets, and artifact provenance

Status: accepted 2026-09-04 for milestone M5

## Context

M4 proved one hand-written chain of tasks end to end and M4.5 made the daemon
able to name the agent behind a request. What the bus still cannot do is hold
a *plan*. Order between tasks lives in the models' heads: the architect
creates a verify task and hopes nobody claims it before the fix exists.
Nothing bounds a conversation, so two agents answering each other politely can
run until the user notices. Nothing bounds a task, so a worker can spend an
afternoon and a provider bill on work the user thought was ten minutes. And an
artifact record proves who published a reference but is never cited as the
evidence for a result, so "verified" is still a word in a payload.

M6 builds automatic dispatch on top of this. A dispatcher that resumes
sessions by itself needs a graph it can read, limits it must stop at, and
provenance it cannot rewrite -- otherwise the first runaway loop is paid for
in real money, and the first wrong "verified" is unfalsifiable.

## Decision

### Order lives in the daemon, not in the models

A task may name prerequisites. `task_create` accepts `depends_on` naming tasks
that already exist. `task_graph_create` creates a whole plan in one
transaction: every node carries a `key` that other nodes in the batch may
depend on, and the edges are checked before anything is written.

A task with an unfinished prerequisite is `waiting`. It cannot be claimed, and
the refusal names what it waits on. The last prerequisite's completion opens
it **in that same transaction**, so no turn can observe a graph that is half
settled. The proof is a kill between the two writes
(`tests.test_crash.CrashCase.test_completion_and_unblocking_commit_together`),
not an assertion about ordering in Python.

A prerequisite that ends any other way -- `blocked`, `cancelled`, or
`exhausted` -- blocks its dependents instead, and that blocking cascades down
the graph. A task waiting on work nobody will ever finish is not waiting; it
is stuck, and the record should say so on the same turn.

Edges are immutable. They are set at creation and there is no tool to add one
later, because an edge added afterwards could close a cycle that no
creation-time check ever saw. That is what makes the cycle check complete
rather than best-effort: within a batch, Kahn's algorithm refuses a cycle
before the first insert; across batches, a new node can only point at tasks
that already exist, so no cycle can form.

### Two new task states, which means rebuilding the table

`waiting` and `exhausted` do not fit the shipped `state` CHECK, and SQLite
cannot widen a CHECK by `ALTER`. Schema v4 rebuilds `tasks` with the
documented copy-drop-rename procedure. `Store.migrate` now runs every
migration with `foreign_keys` off and a `PRAGMA foreign_key_check` before the
commit, so a rebuild that left `artifacts.task_id` or `approvals.task_id`
dangling fails the migration instead of shipping a broken database.

Reusing the existing `blocked` state for both "a prerequisite failed" and "the
worker gave up" was rejected: `blocked` is an outcome a worker chooses, and
conflating it with a dependency state would make the two indistinguishable in
the one place a human looks.

### What the daemon measures, and what it can only be told

A task may carry a `budget`. Four dimensions, and the difference between them
is the point:

| dimension  | measured by | spent when |
| ---------- | ----------- | ---------- |
| `seconds`  | the daemon  | the wall clock passes the deadline set at creation |
| `turns`    | the daemon  | a message whose payload names the task is sent |
| `tokens`   | the provider, reported through `task_record_usage` | the claim holder reports usage |
| `cost_usd` | the provider, reported through `task_record_usage` | the claim holder reports usage |

`seconds` and `turns` cannot be under-reported: the daemon counts them itself
as a side effect of work it already performs. `tokens` and `cost_usd` exist
only inside the provider, so they are accepted from the worker under four
rules -- only the agent holding the claim may report (a peer that could credit
usage to a task it never claimed could spend another agent's budget and stop
its work, and a stop has no reopening), additive only (a report raises a total
and can never lower one), the event keeps the reporting session's `trust`, and
no budget may be enforced *solely* on a reported dimension without the user
having asked for it. An
unknown dimension is refused rather than ignored, because a typo that silently
removed a limit is the worst failure available here.

A spent budget is a stop, not a warning. The task becomes `exhausted`, its
queued messages are dead-lettered, its dependents are blocked, and the send or
claim that hit the limit is refused. The stop commits even though the caller's
request fails: refusing without recording would let the same call be retried
forever. There is no reopening -- a human creates a new task, which is a
decision with a name on it.

M6's dispatcher must treat `exhausted` as terminal. That is the whole point of
landing budgets before dispatch rather than after.

### Hops are a property of the conversation, not a claim by the sender

`hop_count` was a caller-supplied argument. It is now computed by the daemon
as the number of messages the conversation already carries, because a sender
that can set its own hop count can reset a loop to zero forever. A reply
inherits the conversation of the message it answers: review found that
counting per caller-supplied `correlation_id` left the cap escapable by
threading with `reply_to` alone -- 96 replies passed without one refusal --
so `reply_to` now seeds the conversation, and a `correlation_id` that
contradicts the parent is refused instead of honoured. Past
`MAX_HOPS` (32), or once the conversation is older than
`CONVERSATION_TTL_SECONDS` (24 hours), the send is refused and recorded as
`conversation.hop_limit` or `conversation.expired`.

Counting messages rather than `reply_to` depth is deliberate: it bounds a loop
whether or not the models thread their replies, which is exactly the case
where a limit matters.

### Provenance is a record, not a story

`artifacts` gains a `trust` column filled from the publishing session, so an
artifact says how much its producer's identity was worth without walking the
event log. `task_complete` takes `artifacts`: the ids the result rests on,
each of which must already exist, so a result cannot cite work nobody
published. Citing never rewrites production -- the commit the implementer
published still names the implementer after a reviewer cites it as evidence,
which is the assertion the M5 gate makes.

A stopped task (`cancelled`, `exhausted`) accepts no new artifacts. A finished
one still does, because a late verification report about somebody else's
completed task is legitimate evidence.

## Consequences

- The tool contract grows from 16 to 20 tools: `task_get`, `task_graph_create`,
  `task_record_usage`, `artifact_list`. `task_create` gains `depends_on` and
  `budget`; `task_complete` gains `artifacts`.
- `Store.send_message` no longer accepts `hop_count`. Any caller that passed
  one now fails loudly rather than being quietly ignored.
- Schema v4 rebuilds `tasks`; existing rows keep their seq, state, and result,
  and the AUTOINCREMENT high-water mark is carried across explicitly so a seq
  standing above the surviving rows is never handed out twice.
- `bus status` gains a per-state task count and a line per stopped task, in
  both the Node and Python printers: a task nothing will resume must not
  vanish from the only view a human reads.
- The exit gate is `./test.sh --agent-bus-workflow`, which runs the whole
  scenario through the shipped daemon with a fake provider.

## Threat model

Unchanged from ADR 0003 and ADR 0004: cooperative agents that are confused,
stale, or fed hostile text, on one machine and one user account. What this ADR
adds is that a *mistaken* agent cannot spend without bound. It does not defend
against a worker that deliberately under-reports its own token usage; that is
why no daemon-enforced guarantee rests on a reported dimension, and why
`seconds` and `turns` are the dimensions the daemon measures for itself.

A task graph is also an amplifier: one refused edge check is the difference
between a plan that finishes and a set of tasks that wait on each other
forever. The cycle refusal is therefore a validation error before the first
insert, not a repair afterwards.

## Alternatives considered

- **Keep the graph in payloads and let models honour it.** Free, and exactly
  the situation M5 exists to end: a task's order would be advice.
- **A sweeper that opens waiting tasks periodically.** Simpler to write, but
  it puts a window between "prerequisite done" and "dependent claimable" in
  which the bus lies to whoever looks. The transactional unblock has no window.
- **Enforce budgets only on provider-reported numbers.** Rejected: those are
  the numbers a confused worker is least able to report correctly, and a limit
  nobody can verify is not a limit.
- **Let any agent report usage for any task.** Rejected during review, which
  found it live: usage is credited only by the claim holder, because the stop
  it can trigger is irreversible and would otherwise be reachable by a peer in
  one call.
- **Let a budget be raised on a running task.** Rejected for now: it would
  make the stop negotiable by the party that hit it. A human creating a new
  task is a decision with an author.
- **Reuse `blocked` for budget stops.** Rejected: a human reading the status
  view could not tell "the worker gave up" from "the daemon stopped this".

## Rollback

Budgets are opt-in per task: a task without a `budget` behaves exactly as it
did in M4. Dependencies are opt-in per task: without `depends_on`, tasks are
created `open` as before. The hop cap and conversation TTL are not opt-in --
they are the loop stoppers -- but both are constants in `store.py`, and the
schema change is additive apart from the two new states, so a rollback is a
code revert with the v4 database still readable by the reverted code for every
task that never used a new state.
