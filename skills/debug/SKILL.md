---
name: debug
description: Debug a stubborn bug with a deterministic reproduction, hypothesis ledger, one-variable fixes, and a regression test. Use after the first obvious look fails, reproduction is unclear, or a fix attempt failed. Not for routine obvious failures; use for "ไล่บั๊ก".
---

# Debug — hypothesis before edit

The doctrine says: *debugging starts with a hypothesis, not an edit.* Mutating code until the test goes green is not debugging — it is how plausible-but-wrong fixes ship. This is the procedure for bugs that resist the first obvious look.

## 1. Reproduce first

One command that shows the failure deterministically. This command is the ground truth for the whole session — every hypothesis is judged against it.

- If it cannot be reproduced yet, that is the entire current task. Do not theorize about causes of a failure you cannot trigger.
- If it is intermittent, make it deterministic before proceeding: fix the seed, pin the time/timezone, run it in a loop (`for i in $(seq 20)`) until the trigger condition is understood. An intermittent repro means the hypothesis space still contains "timing/state you have not seen".

## 2. Minimize

Shrink the reproduction — smaller input, fewer flags, one test instead of the suite — until the failure is small enough to reason about. Every element removed eliminates a family of hypotheses for free. Stop minimizing when shrinking stops being cheap.

## 3. Hypothesis ledger

**Seed it from recorded experience first.** Before inventing hypotheses, grep the symptom's keywords (error strings, subsystem names) against two files, if they exist:

- the repo's lesson ledger `docs/lessons.md` — this project's previously debugged failures;
- the global heuristics file `luciazero-heuristics.md` in the configured harness directory (`${CLAUDE_CONFIG_DIR:-$HOME/.claude}` or `${CODEX_HOME:-$HOME/.codex}`) — cross-repo lessons. Use the configured path instead of assuming `~/.claude` or `~/.codex`.

A match becomes **H1** — still verify it with its `proven-by` command; a ledger match is a hypothesis with a head start, not a conclusion. No match, or no files: proceed normally.

Keep a visible ledger in the conversation. Each entry:

```
H<N>: <suspected cause> — refutable by: <command / observation> → <result: refuted | confirmed | pending>
```

- **Run the observation, not the edit.** Choose the cheapest command whose output discriminates between this hypothesis and the alternatives — a log line, a targeted print, a debugger break, one `grep`, `git bisect run <verify-cmd>` when a known-good commit exists.
- Prefer reading real state over reasoning about imagined state. The bug exists precisely because the mental model and reality differ — trust output.
- Dead hypotheses stay in the ledger marked refuted, so they are not silently retried an hour later.

## 4. One variable per iteration

- Change one thing, re-run the reproduction, record the result in the ledger.
- A fix attempt that failed gets **reverted before the next attempt** — stacked failed fixes create a second bug on top of the first.
- Two consecutive failed fixes on the same hypothesis means the hypothesis is dead, not unlucky. Widen the search: environment, dependency versions, input data, concurrency, or the test itself being wrong.

## 5. Close out

- The reproduction becomes a committed regression test: **red before the fix, green after** — run it both ways and quote both results. This proves the fix touched the actual cause. The mechanical form lives in the done skill's `scripts/` dir — locate that installed skill and run `<this-skill-dir>/scripts/revert-probe.sh "<verify-cmd>"`.
- Remove all instrumentation (prints, sleeps, debug flags) — check the diff for it explicitly.
- Run the full verify tier, not just the one test.
- If the session surfaced something reading the code cannot teach (a footgun, an environment quirk, a disproven approach), run `/retro` so the next session does not pay for this one's dead ends — for a debugged failure specifically, `/retro` records it in `docs/lessons.md` (symptom → cause → proven-by → fix), which is exactly what step 3 reads next time.
