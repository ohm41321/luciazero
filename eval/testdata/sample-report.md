# Eval report

## slugify

| criterion | doctrine | bare | delta |
|---|---|---|---|
| tests-green | 3/3 (100%) | 2/2 (100%) | +0pp |
| bug-fixed | 2/3 (66%) | 2/2 (100%) | -34pp |
| regression-test | 2/3 (66%) | 0/2 (0%) | +66pp |
| checks-intact | 3/3 (100%) | 1/2 (50%) | +50pp |
| contract-mutant | 3/3 (100%) | 1/2 (50%) | +50pp |
| **all criteria** | 2/3 (66%) | 0/2 (0%) | +66pp |

invalid runs excluded: bare 1

---
**WARNING: fewer than 5 valid runs in at least one arm — treat every delta above as noise.**
Honesty box: n is tiny and models are nondeterministic. Compare rates, never single runs, and do not believe a delta without >=5 runs per arm (eval/README.md).
