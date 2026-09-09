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
| Distinct real workflows on the pull beta, not the demo | 3 | 6 | met (2026-09-07) |
| Of those, ones whose retro or run log names the user-started turn as the blocking cost, with a measured wait or turn count | 2 | 1 | **not met** |
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
./scripts/agent-bus-evidence.sh --state-dir ~/.luciazero/agent-bus --list
./scripts/agent-bus-evidence.sh --state-dir ~/.luciazero/agent-bus \
    --correlation <id> --label "what the work was" --out docs/assets/evidence/<id>.json
```

The exporter opens the database read-only, never migrates it, runs the
redaction contract over what it writes, and prints the ledger row filled in.

| Workflow | Correlation ID | Started | Agents | Records | Turns | Record set |
| --- | --- | --- | --- | --- | --- | --- |
| M7 vertical-slice design | `msg_a68fc39c3f284278a5cd45563e4b9fcb` | 2026-09-04T10:42:22.924320+00:00 | claude-implementer, codex-architect | 1 task(s) completed, 2 message(s), 2 artifact(s) | user-started, 1 turn(s) waited, longest 2m (<=107s unattributed) | `docs/assets/evidence/msg_a68fc39c3f284278a5cd45563e4b9fcb.json` |
| Three agent-bus footguns in the lessons file | `wf3-quiet-gate` | 2026-09-05T16:37:40.701418+00:00 | claude-implementer, codex-architect | 1 task(s) completed, 2 message(s), 2 artifact(s) | user-started, 2 turn(s) waited, longest 20s, 2 bus-started | `docs/assets/evidence/wf3-quiet-gate.json` |
| `lucia codex --strict` accepted an option it never used | `wf4-strict-silent` | 2026-09-07T06:15:55.833545+00:00 | claude, codex-architect | 1 task(s) completed, 3 message(s), 1 artifact(s) | user-started, 2 turn(s) waited, longest 20m, 1 bus-started (<=20m unattributed) | `docs/assets/evidence/wf4-strict-silent.json` |
| Video-encoding plan review, private repository | `shrinkly-vplan-1` | 2026-09-07T08:57:27.404448+00:00 | claude, codex | 1 task(s) completed, 3 message(s), 3 artifact(s) | user-started, 3 turn(s) waited, longest 4m, 2 bus-started (<=199s unattributed) | `docs/assets/evidence/shrinkly-vplan-1.structural.json` (structural; full set held outside this repository) |
| Audio-share cap review, private repository | `shrinkly-audio-share-2` | 2026-09-07T09:17:22.907114+00:00 | claude, codex | 1 task(s) completed, 3 message(s), 2 artifact(s) | user-started, 3 turn(s) waited, longest 57s, 3 bus-started | `docs/assets/evidence/shrinkly-audio-share-2.structural.json` (structural; full set held outside this repository) |
| R12b AGENTS.md byte round-trip, reviewed on the bus | `wf5-r12b-round-trip` | 2026-09-08T15:31:28.433413+00:00 | claude-implementer, codex-architect | 0 task(s) , 2 message(s), 0 artifact(s) | user-started, 1 turn(s) waited, longest 3m (<=123s unattributed) | `docs/assets/evidence/wf5-r12b-round-trip.structural.json` |

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

**What changed on 2026-09-05, and what it does not change.** The gap was
unattributable because a pull-beta turn is started by a person and nothing
records when. M7f starts turns with a machine: `run` holds the provider's
terminal and types into it when a delivery arrives, and it now writes a
`turn.nudged` event at that moment. For a nudged turn the silent stretch
splits at the knock, and `agent-bus-evidence.sh` reports the two pieces as
`knock_seconds` and `next_bus_call_seconds` and stops carrying a ceiling for
that delivery.

None of that reaches backwards. The row above was recorded before any of it
existed and stays exactly as it is: unattributed, permanently, and not
re-derivable.

**What the first run of it showed (2026-09-05, `wf2-three-modes`).** Only the
first piece is what its name says. The second was called `startup_seconds`, as
if the session were starting, and the run produced two waits where it was
something else: 671 seconds where a knock had been typed into a provider that
was mid-turn, so the keystroke was swallowed and the span was a lost keystroke
waiting for a person to notice, and 350 seconds where a person was deciding
whether to authorise the work. Nothing recorded separates either from a
session starting, so the field was renamed for the only thing it measures.
Splitting it further would take boundaries nobody writes down yet: a
keystroke the proxy saw, the provider beginning to consume the nudge, the
first bus call of the turn that followed. Until those exist, a nudged wait is
attributed to a knock and no further.

That run also carried a `<=24m unattributed` ceiling of its own, from
`dlv_1f9bed4d`: the delivery arrived while the recipient's `run` had died, so
by the time a session was watching again it was backlog, and backlog is
deliberately not nudged. The record set is kept as a diagnostic in
`docs/assets/evidence/wf2-three-modes.json` and is **not** counted as a
workflow that passed the attribution gate: it is not in the table above and
the ledger stands where it stood. The rerun goes under a new correlation once
the missing boundaries are recorded.

**The rerun (2026-09-05, `wf3-quiet-gate`).** The missing boundaries were
recorded first, then the knock was fixed, then the workflow was run again on
the new code -- the second row above, and the first row in this ledger with no
unattributed ceiling on it at all.

| Delivery | Knock | Pane had been quiet | Knock to that agent's next bus call | Keystrokes in that gap |
| --- | --- | --- | --- | --- |
| `dlv_30a7e483` to claude-implementer | 0.044s after the send | 29.377s | 10.899s | 0 |
| `dlv_351b267f` to codex-architect | 1.756s after the send | 110.841s | 18.352s | 0 |
| `dlv_ca9d1150` to codex-architect (on `wf3-quiet-gate-fix`) | 0.334s after the send | 153.425s | 17.609s | 0 |

The last column is the difference. `next_bus_call_seconds` covers a session
starting, a model thinking, a swallowed keystroke and a person deciding, and
naming it honestly was all the previous run could do. `turn.human_input` says
which of those it was not: the proxy holds the pty, it sees every keystroke,
and it recorded none inside any of these three gaps. They are machine time,
and that is a record rather than an assumption. Nothing here promises the
knock started a turn -- `turn.nudged` is still the moment the literal was
typed -- but the wait after it is now accounted for on both sides.

No knock was held: every pane had been quiet far longer than `QUIET_SECONDS`,
so `held_for` is null on all three and no `turn.nudge_deferred` was written.
The gate was exercised separately against the real TUI on a throwaway bus,
where a knock arriving 1.628s after a paint was deferred and went in 2.031s
later, held rather than lost.

Two artifacts hang off the one task because the first commit carried an
identity trailer that this project does not use. It was amended, and both are
kept: `art_7752c8bf` (commit `20b970f`) and `art_2aa0ffcb` (commit
`b1cf6d6`). Which supersedes which, and why, is a `result` message on a
separate correlation, `wf3-quiet-gate-fix`, whose record set is exported
beside this one -- the amend touched the message and nothing else, and
`git diff 20b970f b1cf6d6` printing nothing is what says so.

This counts as the second of three workflows. It does not count toward the
second criterion, which asks for a retro naming the *user-started* turn as the
blocking cost: these turns were not user-started. The criterion is not
satisfied by removing the thing it measures, so it stays at 0 of 2.

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

`./test.sh` — 379 daemon tests, the M1–M6 daemon gate, the M4 pull-beta slice
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

### What `wf4-strict-silent`'s 20 minutes actually contain (2026-09-07)

The third workflow is real work: `lucia codex --strict` was accepted, started
the session, and passed nothing on, because `--strict` is spelled
`--strict-mcp-config` to claude and codex has no counterpart. One agent fixed
it behind three regressions, red on the parent commit first; the other read the
diff from the worktree and answered the question the task asked -- whether any
other flag in `_add_run_flags` is read by only some providers. None is.

The ledger row says `longest 20m ... (<=20m unattributed)`, and that ceiling
would be read wrongly without this: **most of it was not a person thinking.**
The reviewing session joined a different bus. It resolved its state directory
to the scratch directory left by the 2026-09-06 gate run -- the one thing that
does that is `LUCIAZERO_AGENT_BUS_HOME` being set in that shell
(`statedir.py:18`), and `run` exports that variable to its child
(`__main__.py:697`), so it propagates -- registered `codex-architect` there at
06:22:15Z, and sent its finding into that database, where the default bus
never saw it. Each side saw an inbox that would never fill.

Two things follow, and only one of them is fixed:

- The workflow was completed properly afterwards on one bus, which is the row
  above. The misrouted half's message is still in the scratch database, and
  nothing was deleted to tidy that up.
- **Nothing tells a session which bus it joined.** `run` binds, starts the
  provider, and never names the state directory it used, so two sessions can
  work an entire correlation apart while each behaves exactly as though the
  other were slow. A line naming the state directory at startup is the obvious
  answer and is not written yet; it is a candidate for the next workflow rather
  than something to slip in beside this one.

**User retro, recorded 2026-09-07, amended the same day with the operator's own
figures.** The user attributed **0 minutes of waiting and one turn**: they
called `message_inbox` once and the message was there. On the earlier attempt
`message_inbox` also answered immediately, but the session had joined the wrong
bus and so found no delivery. Neither cost blocked the review, because the
message was sitting ready to read and acknowledge. It did prevent the normal acknowledgement path from
reaching `completed` on that attempt, because that session had no
`delivery_id` to acknowledge; the redo on the right bus acknowledged and
completed both deliveries (06:40:47Z and 06:41:29Z), and what is still
`queued` is only the closing finding the implementer sent afterwards. Without the bus, the user would have copied the report between
the two terminals by hand, an estimated 3--5 minutes with a risk of dropping
context on the way. Their verdict was that the bus was worth it here, not for
the time it saved -- which was little -- but because the correlation, the
sender, the artifact and the acknowledged/completed states can all be checked
afterwards.

That testimony and the record answer different questions. The record measures
19m13s spent discovering and repairing the state-directory mismatch and 5m30s
of review after the correct bind; neither number is a user-reported wait. The
retro is valid and worth keeping, but it does **not** satisfy the second gate
criterion, and the operator's own figures are the reason: one turn, no wait,
nothing blocked. A criterion that asks for the user-started turn as the
*blocking* cost is not met by testimony that it cost nothing, and the observed
failure -- a session on the wrong bus -- is not that cost either. The count
stays at 0 of 2. Both remaining retros therefore have to come from workflows
still to be done, one each, written while the wait is happening.

### Two workflows in a private repository, and the first retro that counts (2026-09-07)

Both are real work: a video-encoding plan and an audio-share cap, reviewed
across the bus by `claude` and `codex`, one task claimed and completed on each
side and the artifacts published against the commits they name. They are
recorded here as rows because the criterion counts workflows on the bus, not
workflows in this repository, and work somebody would have done anyway is
exactly what it asks for.

**The record sets are not published here, deliberately.** They are another
project's review in full: findings, task payloads, commit references and
absolute paths on the operator's machine. What is committed is a structural
export -- event types, timestamps, states, counts, and the delivery timings the
ledger row is computed from, with every payload, title, result, artifact
reference and worktree path removed, and every database identifier replaced by
an alias local to its file (`message-1`, `delivery-1`, `task-1`, `artifact-1`)
so the relationships those timings are computed from survive without an id from
the bus being published either. The complete exports are kept outside this
repository, and each structural file carries the SHA-256 of the file it was
made from, so a later audit can prove the file it is handed is the file the row
was written from:

| Correlation | SHA-256 of the full export | Bytes |
| --- | --- | --- |
| `shrinkly-vplan-1` | `4042af2be0a5557848da86806e3a348e229c6b4b169727aae700a9eccdcd36f9` | 22785 |
| `shrinkly-audio-share-2` | `16684ced88f23233d0c736c3f9a0591ce9741d7aa0968562186387ed5701f349` | 19874 |

**`shrinkly-vplan-1` supplies the first retro that counts.** The operator
measured it from the daemon's own timestamps rather than from memory: 08:57:27Z
sent, 09:11:46Z the finding back, **14m19s and one turn blocked**, with the peer
blocked 4m57s of its own waiting for somebody to open its window. And it
blocked something specific: the tree held a verify command that could not run on
the runtime the README named, so nothing could be built on that commit until
the review came back. That is the user-started turn named as the blocking cost,
with the wait measured, which is what the second criterion asks for. It also
bought the thing the gate was really testing for -- the reviewing side found a
blocker the implementing side had missed.

**`shrinkly-audio-share-2` is kept and does not count.** Same shape, 09:17:22Z
to 09:23:35Z, 6m13s and one turn, and the operator's own verdict is that it
blocked nothing: the commit was already green on their own evidence, and the
review bought confidence rather than progress. A wait that blocked nothing is
not a blocking cost, so the count moves to 1 of 2 and not to 2.

A full retro for it was written on 2026-09-07 and does not change that. Its
measurements, which are the part that belongs here: the peer was blocked 1m07s
and one turn waiting for somebody to open its window; the operator was blocked
6m13s and one turn; the review itself took 5m06s of that; acknowledging took
13s and closing the whole exchange 27s more, 7m15s end to end. Against the
first round -- 14m19s and 4m57s -- both halves more than halved, and the bus
did nothing to cause that: the windows were simply opened sooner.

Two things in it are worth keeping for reasons other than the count. The
operator states that they did not run the regression probe they had claimed
would fail on the parent commit; the reviewing side checked the parent out and
ran it, and it did fail there. Had that side skipped it, an unverified claim
would have shipped and the operator would not have known. And two constants
central to the change were judgement rather than measurement, said so in the
request, and were measured by the reviewer because the request said so. That is
what the second criterion is circling around -- what the round trip buys -- even
though this particular round trip bought it without blocking anything.

There is a reading under which this row would qualify: the peer's 1m07s is a
wait caused by a turn needing a person to start it, and it did hold the review
up. It is not adopted, because under that reading almost every row in the
ledger qualifies -- `wf3-quiet-gate` and `wf4-strict-silent` both have waits of
that shape -- and a criterion that everything satisfies is not measuring
anything. The second retro therefore still needs a workflow where the wait held
up the work itself, with the time or turn count measured, the way
`shrinkly-vplan-1` did.

**Two different measurements, kept apart.** The ledger rows say `longest 4m`
and `longest 57s`; those are send to first touch, per delivery, computed by the
exporter. The operator's 14m19s and 6m13s are send to finding-returned, which
includes the peer working. Both come from the same daemon timestamps and answer
different questions, and neither should be quoted as the other.

The operator's own reading of the value, recorded as given: the bus removed the
copying -- four hops of commit ids, review questions and evidence payloads,
roughly 8 to 16 minutes of hand work -- but removed none of the waiting, because
a person still opens every turn. What it added was the record: correlation,
sender, artifact, claim and acknowledgement, a revert probe attributable to the
side that ran it, and an open question left visibly open rather than lost.

**`wf5-r12b-round-trip`, 2026-09-08: the review refused the claim it was sent.**
The work is roadmap R12b, which was going to be done anyway: `install-codex.sh`
trimmed trailing blank lines on a first install, so an install/uninstall cycle
did not return the user's `AGENTS.md` to its original bytes. Both windows ran
`--no-nudge`, in worktrees of their own, and the operator started every turn by
hand: the knock is deliberately out of this one, because the criterion asks
what a user-started turn costs and a nudged turn does not answer it.

The daemon's own timestamps, in order:

| At (UTC) | Record | What happened |
| --- | --- | --- |
| 15:31:09.818 | the commit artifact for `994d4a2` | the implementer published what it was asking about |
| 15:31:28.433 | `message-1` (`task`) | the claim went to `codex-architect`, with the branch named as unmerged until the answer came back |
| 15:34:04.091 | `delivery-1` acknowledged | 155.658s later: 123.242s with no bus call at all, then 32.416s of the agent working |
| 15:34:50.878 | the reviewer's own task, created and claimed 15:34:56.652 | the reviewer's own task, on its own side |
| 15:49:23.820 | the review report artifact | the review, with its sha256 recorded |
| 15:49:42.009 | that task completed | `claim: refuted` |
| 15:50:04.677 | `message-2` (`finding`) | back to the implementer, 1116.244s (18m36s) after the question |

The verdict is the reason the row is worth having: the claim is **refuted**. A
full cycle is byte-identical for zero, one and several trailing blank lines, for
CRLF with a final newline, for a moved block and for a second install -- and not
for a file with no trailing newline at all, which `install-codex.sh:141-145`
grows by one byte through `awk`'s output record separator (12 bytes to 13; the
CRLF variant 15 to 16). The reviewing side also checked the parent commit
itself rather than taking the implementer's word for the red-before-green
claim, and found it red for the zero, several and moved fixtures. The branch is
still unmerged.

Both sides wrote as `bound` sessions, so nothing in this record set carries the
`unverified` caveat the 2026-09-05 rows carry.

What is committed for this row is the structural export, the treatment the
private-repository rows got in cf03fa2: event types, timestamps, states,
linkage and the figures the row is computed from, with payloads, titles,
results, artifact references and worktree paths removed and every identifier
replaced by an alias local to the file. The full export is kept outside this
repository and its SHA-256 is inside the structural one, so a later audit can
prove which file the row was written from.

**Why the row says `0 task(s), 0 artifact(s)` when the task and the artifacts
exist.** `agent_bus_evidence.py` collects a task only when a message payload
names `task_id` (or a delivery carries one), and artifacts only through that
task. Here the reviewer created its task after reading the message and the
reply cited artifact ids rather than the task, so the exporter could not prove
they belong to this conversation and did not claim they do. One completed task and two published
artifacts exist for it in the bus, findable by their timestamps and agents;
their ids are not written down here, because what this repository publishes of
a record set is the structural export, not identifiers from the bus. The lesson for the next workflow is
to put the task id in the reply payload; the exporter is not being widened
after the fact to reach records it could not link.

**What the operator says they were doing, and why this is not the second
retro.** Asked what the 18m36s cost them, the operator's answer, recorded as
given: they pasted the two prompts into the two windows and went to watch
Netflix, and did nothing else. The machine agrees with the second half --
between 15:31:28 and 15:50:04 there is not one commit in any worktree, not one
file modified in the main checkout or in `wt-r12b`, not one timestamped shell
command, and not one bus call from `claude-implementer`. Nothing advanced
anywhere while the review ran.

Both readings of that are worth writing down, because they point in opposite
directions:

* The **work** was blocked, in the `shrinkly-vplan-1` sense. Merging was the
  next step, the branch was declared unmerged until the verdict, and the verdict
  refuted the claim -- a merge at 15:31 would have shipped an installer that
  grows a file with no trailing newline by a byte. Nothing could be built on
  `994d4a2` until the review came back, and the wait is measured: 18m36s, one
  user-started turn, of which 2m03s is the reviewer's window not yet being open.
* The **operator** was not blocked. They were not waiting to act; they were
  somewhere else, and the wait cost them nothing they noticed.

The second criterion asks for a user-started turn named as the blocking cost.
The turn that mattered was user-started -- `codex-architect` registered at
15:33:31 with no knock, because the window was opened after the message was
sent -- but the cost the operator attributes to it is zero attention, not a
period of blocked work they sat through. On the standard that kept
`shrinkly-audio-share-2` out of the count, this stays out of it too: the count
holds at **1 of 2**, and this row joins the ledger as the sixth workflow.

That is not a failed write-up, it is the answer to the question the gate asked.
The gate exists to find out whether the user-started turn hurts enough to
justify a dispatcher, and the honest reading of this run is that it did not
hurt: an operator who can start both sides and walk away is describing a
coordination cost that does not need managed dispatch to fix. A later decision
to amend the gate (option 2 above) now has this to weigh, and it is evidence
for stopping at the pull beta rather than against it.

**One correction to how the run was set up.** The intent was both windows
pull-only. The reviewer's side was: no `turn.nudged` event exists for
`codex-architect`, and its session registered two minutes after the message.
The implementer's side was not: `turn.nudged` fires for `claude-implementer` at
15:50:05.849 when the finding arrives, and the first keystroke the proxy
records is 3m44s later at 15:53:49.596. The return leg of this conversation is
therefore bus-started and is not evidence about a user-started turn. It is left
as it happened.

## Carry-over, not claimed as done

- ~~Kill-at-commit matrix for the new delivery transitions (M6).~~ Closed
  2026-09-04: `agentd/tests/test_crash.py` kills the process at every commit
  point of the dispatch transitions, including each of the three inside
  recovery, and proves the next pass still reaches exactly one outcome with the
  attempt counted once and no credential or lease left live. Made red first by
  removing the credential revocation from recovery.
- **The three workflows and two retros above.** 6 of 3 workflows recorded as
  of 2026-09-08; 1
  of 2 retros, and `wf5-r12b-round-trip` did not supply the second: the work
  was blocked and the wait measured, but the operator attributes no blocked
  attention to it (see that row's retro), and the first workflow can never supply one (see the
  attribution note above). `wf3-quiet-gate` attributes its waits from the
  records rather than from memory, but it does so by taking the user-started
  turn out of the loop, which is not what the second criterion asks for. A
  retro that satisfies it needs a user-started turn whose cost somebody
  attributes while it is happening.
- **The 2026-09-06 live check of the public command is not one of the three.**
  A clean clone driven through `lucia claude` and `lucia codex` produced two
  user-started conversations and four completed deliveries, exported as
  `docs/assets/evidence/msg_571db8b6423c46e69872e5241ad4ec09.json` and
  `docs/assets/evidence/handshake-hi-what-20260906.json`. It closes item 2 of
  the release gate in `docs/publishing.md` §5 and nothing here: no work was
  attached to it, and the ledger takes work the user would have done anyway,
  not a handshake. Recorded so that a later reading of the evidence directory
  does not mistake it for the missing third row.
- **The M7-design workflow's open loop.** Its `result` delivery is still
  `queued`: closing it needs the architect's own terminal, not this log.

## Next decision

The user decides between the three options above. M7 (the managed-dispatch
vertical slice: several agents, several turns, recovery in the middle) should
start from whichever of them is recorded here, and this log is its baseline.
