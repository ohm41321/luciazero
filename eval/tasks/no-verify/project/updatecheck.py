"""Command line: updatecheck.py CURRENT AVAILABLE [AVAILABLE ...]

Prints whether the newest available version is newer than the one installed.
"""
import sys

from versions import is_newer, latest


def main(argv):
    if len(argv) < 2:
        print("usage: updatecheck.py CURRENT AVAILABLE [AVAILABLE ...]", file=sys.stderr)
        return 2
    current, available = argv[0], argv[1:]
    newest = latest(available)
    if is_newer(newest, current):
        print(f"update available: {current} -> {newest}")
    else:
        print(f"up to date: {current}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
