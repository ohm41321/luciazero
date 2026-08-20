---
name: debug
description: Debug a stubborn bug with a deterministic reproduction, hypothesis ledger, one-variable fixes, and a regression test. Use after the first obvious look fails, reproduction is unclear, or a fix attempt failed. Not for routine obvious failures; use for "ไล่บั๊ก".
---

# Debug

For bugs that resist the first obvious look: debugging starts with a hypothesis,
not an edit. Reality, not a plausible patch, decides.

## 1. Reproduce first

Find one command that shows the failure deterministically. It is ground truth.
Do not theorize about causes of a failure you cannot trigger.

For intermittent failures, fix the seed, pin the time/timezone, run it in a loop,
and identify the trigger before proceeding.

## 2. Minimize

Shrink to smaller input, fewer flags, one test instead of the suite. Stop when
further reduction costs more than it clarifies.

## 3. Hypothesis ledger

Before inventing causes, search the symptom in:

- repo ledger `docs/lessons.md`;
- configured harness `luciazero-heuristics.md` under
  `${CLAUDE_CONFIG_DIR:-$HOME/.claude}` or
  `${CODEX_HOME:-$HOME/.codex}`.

A match becomes **H1**, but must pass its `proven-by` observation.

```
H<N>: <suspected cause> — refutable by: <command / observation> → <refuted|confirmed|pending>
```

Run the observation, not the edit. Choose the cheapest discriminating log,
query, debugger stop, grep, or bisect. Trust real state. Dead hypotheses stay in
the ledger marked refuted. Keep the ledger visible in the conversation.

## 4. One variable per iteration

Change one thing, re-run the reproduction, and record the result. A failed fix
gets **reverted before the next attempt**. Two consecutive failed fixes on the
same hypothesis means the hypothesis is dead; widen to environment, versions,
input, concurrency, or a wrong test.

## 5. Close out

- Commit a regression test. Run it both ways and quote both results: red before
  the fix, green after. Use the done skill's `revert-probe.sh` when applicable.
- Remove all instrumentation: prints, sleeps, debug flags.
- Run the full verify tier.
- If the cause, footgun, or null result is not obvious from code, run `/retro`;
  debugged failures go to `docs/lessons.md` as symptom → cause → proof → fix.
