#!/usr/bin/env python3
"""Compare two `gate-config-manifest.py` listings and fail on a real change.

The gate's claim is not that every byte under `~/.claude` held still. A
harness that records the session doing the measuring writes to its own store
while the measurement runs, so a whole-tree digest reports a difference on a
run where nothing the installers can write was touched. The claim is that no
row changed outside the harness's own stores, and that no path appeared or
disappeared anywhere at all -- including inside those stores, where the
allowance covers a row that moved and nothing else.

Rows are split from the right. Mode and digest never contain a space and a
path often does: on the run that closed item 5, a third of the rows carried a
space in the path, so a left split reads them as four fields and stops at the
first one. A parser that skipped those rows instead would have gone blind to a
third of the evidence while still printing a verdict.

Usage: gate-config-compare.py <before.txt> <after.txt>
Exit: 0 nothing changed outside the harness stores · 1 something did
"""
import sys

# Stores the harness owns and writes to on its own schedule. No installer
# names any of them: `grep -rn projects install.sh uninstall.sh
# install-codex.sh uninstall-codex.sh scripts/gate-linux-container.sh` is
# empty, and every write target in those scripts is a named leaf under the
# config directory.
HARNESS = (
    ".claude/projects/",
    ".claude/todos/",
    ".claude/shell-snapshots/",
    ".claude/statsig/",
    ".claude/history.jsonl",
    ".claude/logs/",
    ".claude/file-history/",
    ".claude/plugins/cache/",
)


def rows(path):
    out = {}
    with open(path) as handle:
        for number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.rsplit(" ", 2)
            if len(parts) != 3 or not parts[0]:
                raise SystemExit("%s:%d is not `<path> <mode> <digest>`: %r"
                                 % (path, number, line))
            out[parts[0]] = (parts[1], parts[2])
    return out


def harness(path):
    return any(path == entry or path.startswith(entry) for entry in HARNESS)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: gate-config-compare.py <before.txt> <after.txt>")
    before, after = rows(sys.argv[1]), rows(sys.argv[2])
    changed = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    # The allowance is narrow on purpose, and it is only for `changed`: a
    # harness rewrites its own stores while the measurement runs, so a row that
    # moved inside one of them says nothing. An appearing or disappearing path
    # is a footprint wherever it is. A new transcript file is ordinary and a new
    # `luciazero-` anything under the same directory is not, and nothing here
    # can tell those two apart -- so both fail, and a human reads the name.
    bad = sorted([p for p in changed if not harness(p)] + added + removed)
    print("rows before=%d after=%d | changed=%d added=%d removed=%d"
          % (len(before), len(after), len(changed), len(added), len(removed)))
    kinds = [("changed", changed), ("added", added), ("removed", removed)]
    listed = [(kind, path) for kind, paths in kinds for path in paths]
    for kind, path in sorted(listed, key=lambda row: row[1])[:20]:
        print("  %s  %-7s  %s" % ("FAIL" if path in bad else "ok  ", kind, path))
    if bad:
        print("FAIL: %d path(s) changed that the installers could have written,"
              " or appeared, or disappeared" % len(bad))
        raise SystemExit(1)
    print("PASS: nothing changed outside the harness's own stores")


if __name__ == "__main__":
    main()
