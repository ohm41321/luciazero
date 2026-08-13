# Parser task state

Original goal: make `split_fields` preserve semicolons inside quoted fields
while retaining Python 3.8 compatibility.

Completed:

- Reproduced the quoted-separator failure.
- Added a regression test for the failing ASCII input.

In progress: the parser implementation is intentionally untouched.

Next action: edit `parser.py` to parse the record with `csv.reader` using a
semicolon delimiter, then run `./verify.sh`.

Verification: `./verify.sh` exits 1 with the decisive line
`FAIL quoted separator: expected ['alpha', 'bravo;charlie', 'delta']`.

Hypothesis H1, “input encoding corrupts the separator,” is refuted: the ASCII
fixture fails too.

Landmine: keep Python 3.8 compatibility; do not introduce newer syntax.

Read `docs/lessons.md` before editing.
