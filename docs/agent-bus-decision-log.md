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
| Distinct real workflows on the pull beta, not the demo | 3 | 0 | **not met** |
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
| _(none yet)_ | | | | | | |

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

### Offline gates standing green (2026-09-04)

`./test.sh` — 280 daemon tests, the M1–M6 daemon gate, the M4 pull-beta slice
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
- **Nothing measures the wait automatically.** The gate's second criterion asks
  for a measured wait or turn count on a user-started turn. The records carry
  the timestamps to compute it (message `created_at` against its delivery's
  `acknowledged` event), but no tool reports it yet, so a retro has to state it
  by hand.

## Carry-over, not claimed as done

- **Kill-at-commit matrix for the new delivery transitions (M6).** The dispatch
  gate kills the dispatcher mid-turn and recovers, but not at every commit
  point in `dispatched` and `processing`.
- **The three workflows and two retros above.** Open by definition until the
  ledger has rows.

## Next decision

The user decides between the three options above. M7 (the managed-dispatch
vertical slice: several agents, several turns, recovery in the middle) should
start from whichever of them is recorded here, and this log is its baseline.
