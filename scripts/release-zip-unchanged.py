#!/usr/bin/env python3
"""Exit 0 when two release ZIPs hold the same entries with the same bytes and
modes; exit 1 naming the first entry that differs.

The release workflow runs this before it touches the asset of a tag that
already has a GitHub Release. npm skips a version that is already live, so a
rerun after the tag moved to another commit would otherwise leave the ZIP
and the npm package built from different trees.
"""
from __future__ import annotations

import hashlib
import sys
import zipfile


def entries(path: str) -> dict[str, tuple[int, str]]:
    with zipfile.ZipFile(path) as bundle:
        return {info.filename: (info.external_attr, hashlib.sha256(bundle.read(info)).hexdigest())
                for info in bundle.infolist()}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: release-zip-unchanged.py PUBLISHED.zip BUILT.zip", file=sys.stderr)
        return 2
    published, built = entries(argv[1]), entries(argv[2])
    for name in sorted(set(published) | set(built)):
        if published.get(name) != built.get(name):
            print(f"{name}: the published ZIP and this build differ, so the tag moved after its release "
                  "was published; publish a new version instead", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
