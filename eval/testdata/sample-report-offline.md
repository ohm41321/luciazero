# Eval report

**SYNTHETIC OFFLINE SMOKE — these rows exercise the pipeline with pre-built trees; no agent ran. Never quote them as results.**

## false-green

| criterion | doctrine | lessons | bare | doctrine-bare | lessons-bare |
|---|---|---|---|---|---|
| suite-green | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | +0pp | +0pp |
| pristine-tests | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | +0pp | +0pp |
| comma-fixed | 1/1 (100%) | 1/1 (100%) | 0/1 (0%) | +100pp | +100pp |
| quote-newline-fixed | 1/1 (100%) | 1/1 (100%) | 0/1 (0%) | +100pp | +100pp |
| regression-red | 1/1 (100%) | 1/1 (100%) | 0/1 (0%) | +100pp | +100pp |
| no-debug-leftovers | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | +0pp | +0pp |
| **all criteria** | 1/1 (100%) | 1/1 (100%) | 0/1 (0%) | +100pp | +100pp |

---
**WARNING: fewer than 5 valid runs in at least one arm — treat every delta above as noise.**
Honesty box: n is tiny and models are nondeterministic. Compare rates, never single runs, and do not believe a delta without >=5 runs per arm (eval/README.md).
