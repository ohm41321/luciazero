# Agent Bus decision log

The M4 decision point, and the evidence for and against it, in one place.

The roadmap states the gate before the work, so that "it feels used" can never
become the reason to keep building:

> Continue to managed dispatch only when all of the following are recorded
> before M5 starts:
>
> - At least three distinct real workflows (not the demo) completed on the pull
>   beta, each with its correlation ID and record set kept.
> - In at least two of them, a retro or run log names the user-started turn as
>   the blocking cost, with the wait or turn count measured.
> - No open M3 safety finding.
>
> If that evidence does not exist, the release decision is "stop at the pull
> beta"; "it feels used" is not a gate.

## Where the gate stands (2026-09-04)

| Criterion | Required | Recorded | Verdict |
| --- | --- | --- | --- |
| Distinct real workflows on the pull beta, not the demo | 3 | 1 | **not met** |
| Of those, ones whose retro or run log names the user-started turn as the blocking cost, with a measured wait or turn count | 2 | 0 | **not met** |
| Open M3 safety findings | 0 | 0 | met |

## The gate was passed by, not passed

M5 (task graph, budgets, provenance) and M6 (dispatcher, adapters, live smoke
gate) are both complete and their gates are green, and neither waited for the
evidence above. The roadmap's own condition was "recorded before M5 starts", so
the honest description of what happened is that the decision point was skipped
rather than met.

Nothing here is an argument that the work is bad — the machinery demonstrably
runs, and the section below lists what it has actually done — but the gate did
not ask whether the machinery runs. It asked whether anyone was using the pull
beta for real work, on the theory that a coordination layer nobody reaches for
should not grow a dispatcher. That question is still unanswered.

Three ways out, and this is the user's decision:

1. **Meet it now.** Do the next three pieces of real work in this repository on
   the bus, export each record set into the ledger below, and write the retros.
   Costs three real workflows' worth of friction, and answers the question the
   gate asked.
2. **Amend it deliberately.** Decide that the machinery evidence below is what
   the gate should have asked for, write that decision down here with the date
   and the reason, and change the roadmap so a later reader sees an amendment
   rather than an unmet condition.
3. **Stop at the pull beta**, as the roadmap says, and leave managed dispatch
   unreleased behind its opt-in.

Until one of those is recorded, M7 has no baseline: it would extend managed
dispatch on evidence that the decision gate does not accept.

## Ledger: real workflows on the pull beta

Empty. A row is added by doing real work on the bus and exporting its records:

```bash
./scripts/agent-bus-evidence.sh --state-dir ~/.luciazero --list
./scripts/agent-bus-evidence.sh --state-dir ~/.luciazero \
    --correlation <id> --label "what the work was" --out docs/assets/evidence/<id>.json
```

The exporter opens the database read-only, never migrates it, runs the
redaction contract over what it writes, and prints the ledger row filled in.

| Workflow | Correlation ID | Started | Agents | Records | Turns | Record set |
| --- | --- | --- | --- | --- | --- | --- |
| M7 vertical-slice design | `msg_a68fc39c3f284278a5cd45563e4b9fcb` | 2026-09-04T10:42:22.924320+00:00 | claude-implementer, codex-architect | 1 task(s) completed, 2 message(s), 2 artifact(s) | user-started, 1 turn(s) waited, longest 2m (<=107s unattributed) | `docs/assets/evidence/msg_a68fc39c3f284278a5cd45563e4b9fcb.json` |

The first row, and what it does not say. The work was real -- the M7 section of
the roadmap and ADR 0007 were written by the implementer on the bus, from its
own worktree, against a task the architect created there -- and the task
reached `completed` with two artifacts. What it does not show is a closed
loop: the implementer's `result` message is still `queued`, because the
architect's session was closed before anyone opened it.

The 120.334s is measured, and it is **not** a measurement of a human wait. The
records split it at the recipient's first bus call:

| From | To | Seconds | What it is |
| --- | --- | --- | --- |
| `message.sent` 10:42:22.924 | `agent.registered` 10:44:10.363 | 107.440 | no call from that session at all |
| `agent.registered` 10:44:10.363 | `delivery.acknowledged` 10:44:23.258 | 12.894 | the agent working: register, bind worktree, acknowledge |

The second half is settled by the timestamps. The first is not: 107s with no
bus call covers both the time before a person gave the session its turn and
the time a model spent before its first tool call, and nothing distinguishes
them, because a pull-beta turn has no `turn_started_at` -- there is no record
of the moment a person started one. Both terminals were already bound at
10:40:30 and 10:40:41, so it is not the cost of opening a window.

`agent-bus-evidence.sh` now reports the split (`silent_seconds`,
`agent_seconds`) and the ledger carries the unattributed part as a **ceiling**,
so no row can be read as a wait somebody measured. Attributing that 107s needs
the user to say what actually happened, and a retro that claims the records did
it would be false. This workflow therefore counts as 1 of 3, and as 0 of the 2
retros.

**Asked and closed as unattributable (2026-09-04).** The user was asked whether
the 107s was mostly the delay before they gave the implementer its turn, and
answered that they cannot confirm it: nothing they saw records when the prompt
was typed. It stays unattributed permanently for this workflow. Do not
re-derive it -- there is no record that would settle it after the fact.

That is worth stating as a finding rather than a footnote, because it is about
the question the gate is asking. **The pull beta cannot measure its own
central cost.** The gate wants to know whether the user-started turn hurts
enough to justify a dispatcher, and a user-started turn leaves no record of
when it started: the first observable moment is the session's first bus call,
by which time the person and the model have already spent an unknown amount of
time between them. A dispatched turn does have that timestamp -- `runs`
carries `started_at`, which is why the autonomous chat above could report 58s
of dispatcher latency exactly. So the evidence the gate asks for can only ever
be approximate on the side it is asking about, and any future retro has to say
"the user attributed this", never "the records show it".

**Counts as a real workflow**: work the user would have done anyway, done
through the bus, with more than one agent taking part.

**Does not count**: `scripts/agent_bus_e2e.py` and the demo it drives (the
roadmap excludes it by name), the M6 live smoke gate, the offline rehearsal,
and any run whose purpose was to test the bus rather than to get something
done.

## Evidence that does exist: the machinery works

This is not the gate's evidence. It is what can be said today.

### M4 — pull beta, live providers (2026-09-03)

Two approved live runs of the outcome flow through the shipped daemon, six real
provider turns each, Codex through the App Server and Claude through
`claude -p --mcp-config`:

| Run | Correlation ID | Result |
| --- | --- | --- |
| First | `msg_92e94a57dd0647ac85458439840ce11b` | The flow completed — three tasks completed by their assignees, artifacts report/commit/report, five owed deliveries acknowledged and completed, daemon restarted mid-flow (pid 32900 to 33935) with the queue surviving, both writers on their own worktrees, zero approvals needed, commit `0d88c4b` verified from an export. The driver still exited 1: its assertion demanded exactly five messages and the live architect sent a sixth courtesy message. The assertion was the bug. |
| Second | `msg_4e38f88304e04e8ea57855348f5902c4` | Green: `PASS agent bus M4 pull-beta vertical slice (live providers)`, daemon pids 69984 to 71139, commit `b913d23` verified from an export. Its chatter fell in the middle of the flow, which a positional prefix check would have failed — so the subsequence rule was vindicated rather than merely repeated. |

Twelve provider turns, two runs, two different chatter shapes. Record sets were
not exported at the time; what survives is the summary in the roadmap.

### M6 — managed dispatch, live providers (2026-09-04)

`./test.sh --agent-bus-live --spend-quota`, one managed turn per provider:

| Provider | Result |
| --- | --- |
| Codex | `PASS agent bus M6 live smoke gate (codex)` — turn completed in one attempt. The App Server handshake, the bus calls, and a reply to the architect. An earlier run of the same turn cost quota for nothing: the gate failed on an assertion of its own that could never have passed (it filtered events on `actor_agent_id`, a column the events table does not have) while the turn itself had done the whole procedure. |
| Claude | `PASS agent bus M6 live smoke gate (claude)` — exit 0 in one attempt. |

In both, the worker itself wrote `delivery.acknowledged`, `task.claimed`,
`task.completed` and `message.sent` under its own bound session, and no
credential, lease, or turn directory outlived the turn.

Their record sets were not kept: the gate's state directory is disposable and
was removed. The gate now prints the correlation id of the turn it ran, and
`--keep` leaves the state directory for the exporter, so a later run is
auditable. `--rehearse` runs the identical gate against the offline worker for
no quota, which is what proves the gate's own assertions before money is spent.

### M7b — two agents answering each other, live (2026-09-04)

`./scripts/agent-bus-chat.sh --spend-quota --turns 4 --keep`, approved by the
user beforehand: `PASS agent bus autonomous chat (4 turn(s), 4 agent
message(s))`, correlation `msg_297bdf0309d745168c990b8912609e16`, record set
kept in `docs/assets/evidence/`. Four dispatched turns, four completed, no
failed turn, the dispatcher stopping at its own cap. Claude and Codex agreed a
split of work between themselves — implementation on one side, review from a
published artifact on the other — and each verified the task queue
independently rather than taking the other's word for it.

It is not a ledger row. The gate asks for work the user would have done
anyway; this was a demonstration of the mechanism, and the roadmap excludes
demos by name. What it does prove is that the first record set in this
repository whose waits are not a human's exists: `4 dispatched`, longest 58s,
which is dispatcher latency rather than somebody being away from the keyboard.

### Offline gates standing green (2026-09-04)

`./test.sh` — 367 daemon tests, the M1–M6 daemon gate, the M4 pull-beta slice
with a fake provider, the M5 workflow gate, the M6 dispatch gate (dispatcher
killed mid-turn and recovered), and the M3/M4.5 safety fixtures.

## Safety findings (criterion 3)

M3 closed on 2026-09-03 after a third Codex pass returned no findings. Every
milestone since has been reviewed adversarially and every finding fixed with a
regression, several proven red before the fix: M4 (Codex 2 major, 2 minor;
`reviewer` 1 major, 3 minor, 5 nits), M4.5 (5 distinct majors, 1 minor), M5,
M6 dispatcher core (2 blockers, 3 majors, 1 minor) and M6 adapters (3 majors,
3 minors). No safety finding is open.

## Limitations recorded with the evidence

- **Provider transcripts are not disposable.** The bus state directory, the
  worker's working directory and every record in a live gate run are temporary,
  but `~/.codex` and `~/.claude` are not redirected: a real turn needs the
  user's real credentials, and each CLI writes its own session transcript where
  it always does. Nothing in a live run is private from the provider stores.
- **Live gate records vanish by default.** Without `--keep` the state directory
  is removed when the run ends, which is why the first Codex and Claude smoke
  turns have no exported record set.
- **The wait is measured from the records, not from memory.** The gate's second
  criterion asks for a measured wait or turn count on a user-started turn.
  Nothing acknowledges a delivery until a human opens that agent's session, so
  the gap between the send and the acknowledgement is that cost exactly:
  `agent-bus-evidence.sh` reports it per delivery, with the count of turns
  waited on and the longest wait, and puts both in the ledger row. It also
  splits that wait at the recipient's first bus call: after it, the agent was
  demonstrably working; before it, nothing distinguishes a person who has not
  started the turn from a model that has not yet made its first call, because
  the pull beta records no `turn_started_at`. The ledger carries that half as
  a ceiling, and attributing it is a retro's job, not the exporter's.

## Carry-over, not claimed as done

- ~~Kill-at-commit matrix for the new delivery transitions (M6).~~ Closed
  2026-09-04: `agentd/tests/test_crash.py` kills the process at every commit
  point of the dispatch transitions, including each of the three inside
  recovery, and proves the next pass still reaches exactly one outcome with the
  attempt counted once and no credential or lease left live. Made red first by
  removing the credential revocation from recovery.
- **The three workflows and two retros above.** 1 of 3 workflows recorded; 0
  of 2 retros, and the first workflow can never supply one (see the
  attribution note above). The remaining two workflows must have their waits
  attributed while they are happening, by whoever starts the turn, or the
  second criterion stays unmeetable.
- **The M7-design workflow's open loop.** Its `result` delivery is still
  `queued`: closing it needs the architect's own terminal, not this log.

## Next decision

The user decides between the three options above. M7 (the managed-dispatch
vertical slice: several agents, several turns, recovery in the middle) should
start from whichever of them is recorded here, and this log is its baseline.
