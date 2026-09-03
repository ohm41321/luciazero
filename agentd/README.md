# luciazero-agentd

Companion package to [luciazero](../README.md): the local daemon behind the
Agent Bus. Python 3.10+ standard library only, no pip dependencies. Not
published; the release decision is milestone M8 in
[the roadmap](../docs/agent-bus-roadmap.md).

Current milestone: **M1, durable store and state machine.** The package owns
the SQLite schema (`luciazero_agentd/migrations.py`) and the store operations
the pull beta uses (`luciazero_agentd/store.py`): agent registration, message
send and inbox, delivery acknowledgement, task create/claim/complete, artifact
publish, an append-only event log, and idempotent replays.

Verify:

```bash
./test.sh --agent-bus-store        # from the repository root
python3 -m unittest discover -s tests -t .   # from this directory
```

The suite proves migrations are versioned and repeatable, WAL and foreign
keys are on, concurrent claimers of one task get exactly one winner, a
replayed request creates nothing twice, events cannot be updated or deleted,
and a process killed at any point around a pull-beta transition leaves the
store either fully before or fully after that transition.
