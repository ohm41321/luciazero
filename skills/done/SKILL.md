---
name: done
description: Closeout ritual before declaring any non-trivial task complete. Use when about to say "done", "finished", "it works now", before opening a PR, when the user asks "is it done?", "wrap it up", "ปิดงาน" — or whenever a change is about to be handed back as complete. Not for trivial single-line answers with no code change.
---

# Done — prove it before you say it

The doctrine says: *done is proven by a command, not by my judgment.* This is the ritual that turns that rule into a checklist. Run every step; skipping one is how "done" ships broken.

## 1. Full verify

Run the **full** tier (`verify-full` if the repo has two tiers, else the verify command). Quote the shortest decisive line of real output.

- Red → you are not here yet. Go back to the loop; do not continue this ritual.
- No verify command exists → that is the first bug (`/luciazero-bootstrap`). Say so instead of declaring done.
- The command must actually have run **now**, in this session — a green from an hour ago proves the past, not the present.

## 2. Skeptic diff pass

Re-read the final diff as a hostile reviewer. Tests prove what they cover; hunt what they do not:

- **Edge cases** — empty, zero, negative, unicode, first/last, concurrent
- **Error paths** — the call fails, the file is missing, the network drops; are errors swallowed?
- **Changed contracts** — public API shape, serialized formats, schema, config keys: who consumes the old shape?
- **Accidental content** — files touched by mistake, debug prints, commented-out code, leftover instrumentation, loosened dependency pins, secrets
- **Test honesty** — would the new/changed tests fail if the change were reverted? The mechanical form: `scripts/revert-probe.sh "<verify-cmd>"` answers it in one command. Weakened or deleted checks are findings, not cleanup.

Fix what you find, re-run step 1, then continue.

## 3. Independent review, if the diff earns it

Get an adversarial second opinion — the harness's built-in review command (Claude Code: `/code-review`) or the `reviewer` agent — when **any** of these hold:

- Touches a public API, data migration, auth, money, or concurrency
- Wide diff (many files, or a subsystem you did not previously know)
- You cannot explain in one sentence why each hunk is safe

Findings go back through step 1. For small well-understood diffs, step 2 suffices — do not add ceremony the diff does not need.

## 4. Scope check

Re-read the original request. For each part: delivered, or named as left out with the reason. Silently dropped scope is the failure mode this step exists to catch. Anything left out gets said **plainly** in the report, not buried.

## 5. Lessons

If the session hit a dead end, a footgun, or disproved a tempting approach — run `/retro` now, while the evidence is fresh. If unfinished work remains for a future session, `/handoff` instead.

## 6. Report

```
Done: <what changed, one line>
Proof: <verify command> → <decisive output line>
Not covered: <what verify does not prove>
Left out: <scope not delivered + why, or "nothing">
```

No hedging in the report: if all steps passed, state it plainly; if one did not, the task is not done and the report says what remains instead.
