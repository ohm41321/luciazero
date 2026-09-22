# Eval report

## false-green

| criterion | doctrine | noskills | doctrine-noskills |
|---|---|---|---|
| suite-green | 2/2 (100%) | 2/2 (100%) | +0pp |
| comma-fixed | 2/2 (100%) | 1/2 (50%) | +50pp |
| regression-red | 1/2 (50%) | 0/2 (0%) | +50pp |
| **all criteria** | 1/2 (50%) | 0/2 (0%) | +50pp |

skill use (trace evidence, valid runs): doctrine observed 1/2 (done x1), not observed 1/2; noskills observed 1/2 (debug x1*), not observed 1/2
(* no evidence tied to the sandbox install: a built-in skill of the same name, or an unresolved source)

means over valid runs: doctrine 76s / 3.9k out-tok / $0.29; noskills 52s / 2.3k out-tok / $0.17

## pipeline

| criterion | doctrine | noskills | doctrine-noskills |
|---|---|---|---|
| suite-green | 1/1 (100%) | 1/1 (100%) | +0pp |
| root-cause | 1/1 (100%) | 0/1 (0%) | +100pp |
| **all criteria** | 1/1 (100%) | 0/1 (0%) | +100pp |

invalid runs excluded: noskills 1

skill use (trace evidence, valid runs): doctrine observed 1/1 (debug x1, done x1*); noskills unknown 1/1 — result-only log (no tool events)
(* no evidence tied to the sandbox install: a built-in skill of the same name, or an unresolved source)

means over valid runs: doctrine 90s / 5.0k out-tok / $0.40; noskills 50s / 2.0k out-tok / $0.14

---
**WARNING: fewer than 5 valid runs in at least one arm — treat every delta above as noise.**
Honesty box: n is tiny and models are nondeterministic. Compare rates, never single runs, and do not believe a delta without >=5 runs per arm (eval/README.md).
