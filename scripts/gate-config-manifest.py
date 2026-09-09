#!/usr/bin/env python3
"""Record the state of a machine's real Luciazero configuration, one row per path.

Release gate item 5 claims that a gate run leaves the operator's own
configuration alone. Proving that needs a before and an after of the two
directories the installers can reach -- `~/.claude` and `~/.codex` -- taken
with the same code both times.

A row is `<path relative to home> <octal st_mode> <digest>`. The digest is the
sha256 of the file's bytes for a regular file, the sha256 of the target string
for a symlink, and empty for anything else -- a directory, a socket, a fifo.
`lstat` is used throughout and symlinks are never followed: a symlink to a
file outside the tree is not that file's content, and a symlink retargeted in
place keeps its path and its mode, so recording the target is the only way the
change shows up at all.

The digest of the whole listing is deliberately not printed here. On a machine
where the measurement runs inside a harness that keeps a session transcript
under `~/.claude`, a single digest answers "did every byte hold still", which
is not the question -- the harness writes to its own store by existing.
`gate-config-compare.py` asks the question that is: did anything change that
the installers can write.

Usage: gate-config-manifest.py <home> > rows.txt
"""
import hashlib
import os
import sys


def digest(path):
    out = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            out.update(chunk)
    return out.hexdigest()


def rows(home):
    seen = []
    for root in (os.path.join(home, ".claude"), os.path.join(home, ".codex")):
        if not os.path.lexists(root):
            seen.append("%s absent " % os.path.relpath(root, home))
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames.sort()
            here = [dirpath] + [os.path.join(dirpath, n) for n in sorted(filenames + dirnames)]
            for path in here:
                rel = os.path.relpath(path, home)
                # A row is a line, so a path that carries a newline would split
                # into two rows and read as two paths. Refusing is the only
                # honest answer: silently dropping it would hide exactly the
                # kind of path somebody chose on purpose.
                if "\n" in rel or "\r" in rel:
                    raise SystemExit("path contains a newline and cannot be recorded: %r" % rel)
                stat = os.lstat(path)
                content = ""
                if os.path.islink(path):
                    # Where it points is its content. Without this a symlink
                    # aimed somewhere else keeps the row it had, and the
                    # comparison calls the tree unchanged.
                    content = hashlib.sha256(
                        os.readlink(path).encode("utf-8", "surrogateescape")).hexdigest()
                elif os.path.isfile(path):
                    content = digest(path)
                seen.append("%s %o %s" % (rel, stat.st_mode, content))
    return sorted(set(seen))


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: gate-config-manifest.py <home> > rows.txt")
    for row in rows(sys.argv[1]):
        print(row)


if __name__ == "__main__":
    main()
