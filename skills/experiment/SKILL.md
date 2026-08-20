---
name: experiment
description: Measure performance or tuning changes with a baseline, controlled comparison, correctness check, and recorded verdict. Use for speed, memory, latency, size, "ทดลอง", or any claim that one approach is better. Not for correctness bugs.
---

# Experiment — no claim without a measurement

Optimization needs numbers; null results get recorded too.

## 1. Define the metric before touching code

Choose one command that prints the number: runtime, RSS, latency, size, or count.
Decide **now** what improvement would count, before seeing results. If no metric
command exists, build it first.

## 2. Baseline

Run at least 3 times and record all values, not only the mean. Pin what you can:
seed, input, cache state, and environment; state what remains uncontrolled.
Correctness verify must be green before and after.

## 3. One variable per experiment

Change one thing. Multiple changes make the result uninterpretable.

## 4. Measure again

Use the Same command, same repetitions, same conditions. A result must beat the
baseline spread; Inside the noise = **null result**.

## 5. Verdict and record

Follow the repository's existing experiment log; otherwise create and append to
`docs/experiments.md`:

```
## <date> — <hypothesis>
change: <one variable>
baseline: <all values> | result: <all values>
verdict: WIN <n%> | NULL (inside noise) | LOSS
decision: <kept or reverted + reason>
```

Losers and nulls are reverted immediately; the log preserves the finding, not
the bad diff. A null result is a finding—record it so it is not retried without
new evidence. Never delete a previous entry; append a correction when later
evidence overturns it. Route load-bearing nulls through `/retro`.
