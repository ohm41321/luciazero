# Changelog

## Unreleased

- `wrap(..., indent=)`: a prefix for every line, counted against the width.
- Words longer than the room left are broken hard instead of overflowing.

## 1.0

- `wrap(text, width)`: greedy word wrapping.
- `cli.py`: wrap standard input.
- `report.render`: fixed-width status report.
