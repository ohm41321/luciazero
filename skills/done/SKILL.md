---
name: done
description: Run the closeout ritual before handing back non-trivial work; full verification, revert-probe honesty, independent review, and scope reporting. Use before declaring completion, opening a PR, wrapping up a change, or "ปิดงาน".
---

# Done

## 1. Full verify

The **full** tier — `verify-full` when present, otherwise verify — must be
green after the last code edit. Run it only when no such result exists; an
older green does not count. Quote the shortest decisive line.

- Red → you are not here yet. Return to the loop.
- No verify command exists → use `/ready`; do not claim done.

## 2. Skeptic diff pass

Re-read the final diff as a hostile reviewer. Check:

- **Edge cases**: empty, zero, unicode, boundaries, concurrency.
- **Error paths**: failures, missing files, dropped network, cleanup.
- **Changed contracts**: APIs, formats, schema, config, old consumers.
- **Accidental content**: unrelated files, debug code, secrets, loose pins.
- **Test honesty**: would changed tests fail if implementation is reverted?

Only when the diff adds or changes tests, run
`<this-skill-dir>/scripts/revert-probe.sh "<verify-cmd>"` aimed at those tests.
Exit 2 is UNASSESSABLE: report it as no proof, not
as a pass. Weakened checks are findings. Fix findings and repeat full verify.

## 3. Risk-routed independent review

Choose focus:

- `security`: auth, permissions, input, paths, commands, secrets, endpoints.
- `contract`: public API/CLI, schema, config, migration, consumers.
- `general`: money, concurrency, resources, or a wide uncertain diff.

A small, well-understood diff with no routed risk stops after the skeptic
pass: no review is the default, not an exception. Otherwise run **one** pass —
the harness's built-in review command when it exists, else one reviewer agent
— scoped to the diff and its direct callers, naming both `security` and
`contract` when both apply; never two.

Fix and re-verify every `blocker` or `major`, unless the user explicitly
accepts the named risk. A `minor` may be deferred only when reported.

## 4. Scope check

Re-read the original request. Every item is delivered, or named as left out with
a reason. Never drop scope silently. A bus task you claimed through
`/lucia-bus` must be `completed` or `blocked`, with its result published,
unless the user cancelled it.

## 5. Lessons

For a dead end, footgun, or disproved approach, run `/retro`. If unfinished
state must transfer, use `/lucia-relay` instead.

## 6. Report

```
Done: <what changed, one line>
Proof: <verify command> → <decisive line>
Not covered: <verification gap>
Left out: <scope omitted + reason, or nothing>
```

No hedging: report done only after every step passes. Machine output mirrors the
same facts; blocked output uses `"status": "blocked"` and its failing line.

```json
{
  "status": "done",
  "verify": {"command": "./test.sh", "exit_code": 0, "decisive_line": "PASS  all checks green"},
  "not_covered": "<verification gap>",
  "left_out": "nothing"
}
```
