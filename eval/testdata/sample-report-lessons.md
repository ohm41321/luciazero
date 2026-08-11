# Eval report

## false-green

| criterion | doctrine | lessons | bare | doctrine-bare | lessons-bare |
|---|---|---|---|---|---|
| suite-green | 2/2 (100%) | 2/2 (100%) | 1/1 (100%) | +0pp | +0pp |
| comma-fixed | 2/2 (100%) | 2/2 (100%) | 0/1 (0%) | +100pp | +100pp |
| regression-red | 1/2 (50%) | 2/2 (100%) | 0/1 (0%) | +50pp | +100pp |
| **all criteria** | 1/2 (50%) | 2/2 (100%) | 0/1 (0%) | +50pp | +100pp |

invalid runs excluded: bare 1

means over valid runs: doctrine 76s / 3.9k out-tok / $0.29; lessons 60s / 2.9k out-tok / $0.21; bare 41s / 1.9k out-tok / $0.12

---
**WARNING: fewer than 5 valid runs in at least one arm — treat every delta above as noise.**
Honesty box: n is tiny and models are nondeterministic. Compare rates, never single runs, and do not believe a delta without >=5 runs per arm (eval/README.md).
