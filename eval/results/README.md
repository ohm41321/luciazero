# Benchmark evidence

This directory contains immutable raw behavioral campaigns. `campaigns.json`
is the registry: it records each file's SHA-256, publication status, expected
schema and task/arm/run identities, row and invalid counts, model-identity
coverage, and historical limitations.

A campaign that ran an arm set other than `doctrine,bare` names it in the
registry (`"arms": ["doctrine", "noskills"]`, each of `doctrine`, `noskills`,
`bare` at most once); the row checks, the `expected_invalid` cells and the
generated tables follow that set. A campaign with both `doctrine` and
`noskills` renders the skills-ablation table, with the skill-use count read
from the rows' trace evidence; one without `bare` stays out of the
doctrine-versus-bare tables.

Do not edit a published JSONL file. Add a new campaign instead. Then run:

```bash
python3 eval/evidence.py --write
./test.sh
```

`eval/evidence.py --check` verifies every registered digest, validates every
row through the report schema, checks the registered task/arm/count/model
expectations, and proves that the generated Evidence blocks in both READMEs and
`docs/benchmark.md` match the raw rows. This prevents malformed data or a
hand-edited table from becoming a public claim.

The historical Claude files predate the current reproducibility schema. Their
missing metadata is recorded explicitly rather than reconstructed. In
particular, only 70/140 Haiku rows encode model identity; the other 70 have only
campaign-level attribution and cannot be verified per row. The canonical
Sonnet file is preliminary: eight replacement rows
mentioned by commit `b24f6a2` could not be recovered, so the old `+37pp` claim
is retired unless those exact raw rows are found.
