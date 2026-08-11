# Lessons — debugged failures (ledger)

## CSV columns shift in the spreadsheet when a field contains a comma
cause: export path joins raw str(field) values without RFC 4180 quoting | proven-by: `python3 -c 'from csv_export import export_rows; print(export_rows([["a,b", 1]]))'` | fix: wrap fields containing a comma, quote, or newline in double quotes and double embedded quotes | date: 2026-07-02
