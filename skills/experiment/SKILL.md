---
name: experiment
description: Measured-change protocol for performance and tuning work. Use when the task is "make it faster", "optimize", "reduce memory", "ทดลอง", when comparing two approaches, or whenever a claim like "this should be faster" is about to be made without a number. Not for correctness bugs — that is /debug.
---

# Experiment — no claim without a measurement

An optimization without a baseline is a guess with confidence. The protocol is the same loop as always — but *verify* here means **measure**, and the doctrine's "never re-derive a dead end twice" means null results get recorded with the same weight as wins.

## 1. Define the metric before touching code

- One command that prints the number: runtime, RSS, p95 latency, binary size, query count. If no such command exists, building it is step zero (the measurement twin of "no verify command is the first bug").
- Decide **now** what improvement would count — "worth it if ≥10% faster" — so the verdict is not negotiated after the numbers exist.

## 2. Baseline

- Run the measurement **at least 3 times**; record all values, not just the mean — the spread is what separates signal from noise.
- Pin what you can: fixed seed, same input data, warm/cold state chosen deliberately, machine as quiet as you can get it. Note what you could not pin.
- Correctness verify must be green before and after — a fast wrong answer is not an optimization.

## 3. One variable per experiment

Change one thing. Two changes in one measurement produce a number that explains neither. (Same discipline as `/debug`; same reason.)

## 4. Measure again

- Same command, same repetitions, same conditions.
- The difference counts only if it clearly beats the baseline spread. Inside the noise = **null result**, not "slightly faster".

## 5. Verdict and record

Append to `docs/experiments.md` (create it if absent; follow the repo's existing log if one exists):

```
## <date> — <hypothesis, one line>
change: <what was changed, file/approach>
baseline: <values> | result: <values>
verdict: WIN <n%> | NULL (inside noise) | LOSS
decision: <kept / reverted> — <one-line reason>
```

- **Losers and nulls are reverted immediately** — the log keeps the knowledge, the tree keeps only wins.
- A null result is a finding: "tried X, no measurable gain — do not retry without new evidence" saves the next session the same hour. If it is load-bearing, surface it via `/retro` into the project notes too.
- Never delete a previous entry; if a new experiment overturns an old one, add the new entry and cross-reference.
