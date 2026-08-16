---
name: done
description: Run the closeout ritual before handing back non-trivial work: full verification, revert-probe honesty, independent review, and scope reporting. Use before declaring completion, opening a PR, wrapping up a change, or "ปิดงาน".
---

# Done — prove it before you say it

The doctrine says: *done is proven by a command, not by my judgment.* This is the ritual that turns that rule into a checklist. Run every step; skipping one is how "done" ships broken.

## 1. Full verify

Run the **full** tier (`verify-full` if the repo has two tiers, else the verify command). Quote the shortest decisive line of real output.

- Red → you are not here yet. Go back to the loop; do not continue this ritual.
- No verify command exists → that is the first bug (`/ready`). Say so instead of declaring done.
- The command must actually have run **now**, in this session — a green from an hour ago proves the past, not the present.

## 2. Skeptic diff pass

Re-read the final diff as a hostile reviewer. Tests prove what they cover; hunt what they do not:

- **Edge cases** — empty, zero, negative, unicode, first/last, concurrent
- **Error paths** — the call fails, the file is missing, the network drops; are errors swallowed?
- **Changed contracts** — public API shape, serialized formats, schema, config keys: who consumes the old shape?
- **Accidental content** — files touched by mistake, debug prints, commented-out code, leftover instrumentation, loosened dependency pins, secrets
- **Test honesty** — would the new/changed tests fail if the change were reverted? The mechanical form: `<this-skill-dir>/scripts/revert-probe.sh "<verify-cmd>"` answers it in one command. Weakened or deleted checks are findings, not cleanup.

Fix what you find, re-run step 1, then continue.

## 3. Risk-routed independent review

Classify the diff before requesting an adversarial second opinion:

- `security` — auth, permissions, external input, paths, command construction, secrets, or public endpoints
- `contract` — public API, CLI, serialized data, schema, config keys, migrations, or downstream consumers
- `general` — money, concurrency, resource ownership, a wide unfamiliar diff, or any hunk whose safety you cannot explain in one sentence

Use the harness's built-in review command (Claude Code: `/code-review`) or the single `reviewer` agent with the selected `focus`. If both `security` and `contract` apply, request two independent focused passes; do not blend two threat models into one shallow prompt. The reviewer must read callers and consumers, not only changed lines.

A `blocker` or `major` finding must be fixed and re-verified, or explicitly waived by the user with the remaining risk named. A `minor` may be deferred only when the report names it. For a small, well-understood diff with no routed risk, step 2 suffices.

## 4. Scope check

Re-read the original request. For each part: delivered, or named as left out with the reason. Silently dropped scope is the failure mode this step exists to catch. Anything left out gets said **plainly** in the report, not buried.

## 5. Lessons

If the session hit a dead end, a footgun, or disproved a tempting approach — run `/retro` now, while the evidence is fresh. If unfinished work remains for a future session or another agent, `/lucia-relay` instead.

## 6. Report

```
Done: <what changed, one line>
Proof: <verify command> → <decisive output line>
Not covered: <what verify does not prove>
Left out: <scope not delivered + why, or "nothing">
```

No hedging in the report: if all steps passed, state it plainly; if one did not, the task is not done and the report says what remains instead.

When the report feeds a machine — a CI job, a PR comment, a dashboard — mirror it as JSON: same facts, no extra claims. A blocked closeout reports `"status": "blocked"` with the failing line as `decisive_line`.

```json
{
  "status": "done",
  "verify": {"command": "./test.sh", "exit_code": 0, "decisive_line": "PASS  all checks green"},
  "not_covered": "<what verify does not prove>",
  "left_out": "nothing"
}
```
