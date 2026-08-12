# Benchmark evidence

This directory contains immutable raw behavioral campaigns. `campaigns.json`
is the registry: it records each file's SHA-256, publication status, expected
schema and task/arm/run identities, row and invalid counts, model-identity
coverage, and historical limitations.

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
