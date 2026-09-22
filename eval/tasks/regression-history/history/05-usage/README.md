# linewrap

Greedy word wrapping for fixed-width text: `wrap(text, width)` returns the
lines, each at most `width` characters, breaking only at whitespace.

## Command line

```
printf 'the quick brown fox jumps over the lazy dog\n' | python3 cli.py --width 13
```

## Status report

`report.render(entries, width)` prints one block per `(title, note)` pair:
the title in capitals, a rule as wide as the report, and the note wrapped
underneath.
