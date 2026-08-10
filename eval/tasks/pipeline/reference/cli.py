import sys

from parse import parse
from render import render
from transform import transform


def main(argv):
    if len(argv) != 2:
        print("usage: cli.py <ledger-file>", file=sys.stderr)
        return 2
    with open(argv[1]) as fh:
        text = fh.read()
    print(render(transform(parse(text))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
