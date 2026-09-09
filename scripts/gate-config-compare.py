#!/usr/bin/env python3
"""Compare two `gate-config-manifest.py` listings and fail on a real footprint.

The question release gate item 5 asks is whether a gate run touched anything
the installers can write in the operator's own configuration. That is not the
same as asking whether every byte under `~/.claude` held still: a harness
rotates its own backups, writes session state, and appends this session's
transcript while the measurement runs, and none of that is an installer.

The first version of this asked the wrong one and then tried to patch it with
a list of the harness's directories. That list can never be finished -- two
runs found two more of them (`.claude/backups/`, `.claude/sessions/`) after it
was already being called evidence, and a directory nobody has seen yet is
always one release away. So the rule is turned around and taken from the four
installers instead, which is where the claim comes from: a path they can write
is named here, any difference at one of those paths fails, and everything else
is reported as noise the run did not cause.

That is stronger than the denylist for what item 5 claims, and it is weaker
for a thing item 5 does not claim: an unrelated change under `~/.claude` no
installer could have made is listed and does not fail. The listing is printed
so a person can look at it.

Usage: gate-config-compare.py <before.txt> <after.txt>
Exit: 0 no installer-owned path differs · 1 one does
"""
import os
import sys

# Every write target in install.sh, uninstall.sh, install-codex.sh and
# uninstall-codex.sh, by location:
#   CLAUDE.md, settings.json, luciazero.md, skills/, agents/, hooks/, bin/
#   AGENTS.md, skills/ on the codex side
# and by name: anything they own carries `luciazero` in its own name --
# .luciazero-version, .luciazero-managed/, .luciazero-backups/,
# .luciazero-import, .luciazero-agentd-home, luciazero-heuristics.md,
# hooks/luciazero-*.sh, the launcher names. The name rule is what makes a
# `luciazero-` anything appearing in a directory nobody expected still a
# failure, wherever it lands.
OWNED_DIRS = (
    ".claude/skills/", ".claude/agents/", ".claude/hooks/", ".claude/bin/",
    ".codex/skills/",
)
OWNED_EXACT = (
    ".claude/skills", ".claude/agents", ".claude/hooks", ".claude/bin",
    ".claude/CLAUDE.md", ".claude/settings.json", ".claude/luciazero.md",
    ".codex/skills", ".codex/AGENTS.md",
)
# the installers' own backups: `<name>.bak.<timestamp>` beside the file
BACKED_UP = ("CLAUDE.md", "AGENTS.md", "settings.json")


def owned(path):
    base = os.path.basename(path)
    if "luciazero" in base.lower():
        return True
    if path in OWNED_EXACT or any(path.startswith(d) for d in OWNED_DIRS):
        return True
    if path.startswith((".claude/", ".codex/")):
        return any(base.startswith(name + ".bak.") for name in BACKED_UP)
    return False


def rows(path):
    out = {}
    with open(path) as handle:
        for number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            # Split from the right: mode and digest never contain a space and a
            # path often does. On the machine that ran this, 9151 of 26560 rows
            # carried one, and a left split reads those as four fields.
            parts = line.rsplit(" ", 2)
            if len(parts) != 3 or not parts[0]:
                raise SystemExit("%s:%d is not `<path> <mode> <digest>`: %r"
                                 % (path, number, line))
            out[parts[0]] = (parts[1], parts[2])
    return out


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: gate-config-compare.py <before.txt> <after.txt>")
    before, after = rows(sys.argv[1]), rows(sys.argv[2])
    changed = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    listed = ([("changed", p) for p in changed] + [("added", p) for p in added]
              + [("removed", p) for p in removed])
    bad = sorted(p for _, p in listed if owned(p))

    print("rows before=%d after=%d | changed=%d added=%d removed=%d | installer-owned=%d"
          % (len(before), len(after), len(changed), len(added), len(removed), len(bad)))
    for kind, path in sorted(listed, key=lambda row: row[1])[:40]:
        print("  %s  %-7s  %s" % ("FAIL" if owned(path) else "noise", kind, path))
    if len(listed) > 40:
        print("  ... %d more not listed" % (len(listed) - 40))
    if bad:
        print("FAIL: %d path(s) the installers can write differ" % len(bad))
        raise SystemExit(1)
    print("PASS: no installer-owned path differs")


if __name__ == "__main__":
    main()
