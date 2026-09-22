# linewrap

Greedy word wrapping for fixed-width text: `wrap(text, width, indent="")`
returns the lines, each at most `width` characters, breaking only at
whitespace. `indent` is put in front of every line and counts against the
width; a word longer than the room left is broken hard.

## Command line

```
printf 'the quick brown fox jumps over the lazy dog\n' | python3 cli.py --width 13
printf 'one two three four\n' | python3 cli.py --width 10 --indent '> '
```

## Status report

`report.render(entries, width)` prints one block per `(title, note)` pair:
the title in capitals, a rule as wide as the report, and the note wrapped
underneath.
