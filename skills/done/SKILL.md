---
name: done
description: Run the closeout ritual before handing back non-trivial work: full verification, revert-probe honesty, independent review, and scope reporting. Use before declaring completion, opening a PR, wrapping up a change, or "ปิดงาน".
---

# Done

## 1. Full verify

Run the **full** tier now: `verify-full` when present, otherwise verify. Quote
the shortest decisive line.

- Red → you are not here yet. Return to the loop.
- No verify command exists → use `/ready`; do not claim done.
- It must actually have run **now**, not earlier in the session.

## 2. Skeptic diff pass

Re-read the final diff as a hostile reviewer. Check:

- **Edge cases**: empty, zero, unicode, boundaries, concurrency.
- **Error paths**: failures, missing files, dropped network, cleanup.
- **Changed contracts**: APIs, formats, schema, config, old consumers.
- **Accidental content**: unrelated files, debug code, secrets, loose pins.
- **Test honesty**: would changed tests fail if implementation is reverted?

When applicable run
`<this-skill-dir>/scripts/revert-probe.sh "<verify-cmd>"`. Weakened checks are
findings. Fix findings and repeat full verify.

## 3. Risk-routed independent review

Choose focus:

- `security`: auth, permissions, input, paths, commands, secrets, endpoints.
- `contract`: public API/CLI, schema, config, migration, consumers.
- `general`: money, concurrency, resources, or a wide uncertain diff.

Prefer the harness's built-in review command; otherwise use one reviewer agent.
If security and contract both apply, request two independent focused passes.
The reviewer reads callers and consumers.

Fix and re-verify every `blocker` or `major`, unless the user explicitly
accepts the named risk. A `minor` may be deferred only when reported. A small,
well-understood diff with no routed risk may stop after the skeptic pass.

## 4. Scope check

Re-read the original request. Every item is delivered, or named as left out with
a reason. Never drop scope silently.

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
