"""Wrap standard input: python3 cli.py [--width N]"""
import argparse
import sys

from linewrap import wrap


def main(argv=None):
    parser = argparse.ArgumentParser(description="wrap standard input to a width")
    parser.add_argument("--width", type=int, default=40)
    args = parser.parse_args(argv)
    for line in wrap(sys.stdin.read(), args.width):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
