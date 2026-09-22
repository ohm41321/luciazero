"""Wrap standard input: python3 cli.py [--width N] [--indent TEXT]

The default width can also come from the WRAP_WIDTH environment variable.
"""
import argparse
import os
import sys

from linewrap import wrap


def main(argv=None):
    parser = argparse.ArgumentParser(description="wrap standard input to a width")
    parser.add_argument("--width", type=int, default=int(os.environ.get("WRAP_WIDTH", "40")))
    parser.add_argument("--indent", default="", help="prefix for every line, counted against the width")
    args = parser.parse_args(argv)
    for line in wrap(sys.stdin.read(), args.width, indent=args.indent):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
