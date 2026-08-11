# Lessons — debugged failures (ledger)

## Report renders one entry short; grand total off by the last line's worth
cause: parse() only flushes a pending record on the blank-line separator, so input without a trailing separator drops the final record | proven-by: `python3 -c 'from parse import parse; print(len(parse("item: a\nqty: 1\nprice: 2")))'` | fix: flush the pending record at end of input in parse.py | date: 2026-06-18
