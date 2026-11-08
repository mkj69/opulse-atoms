"""Compatibility entry point for machine runs; use harness.run --track machine."""

import sys

from atoms_mul.harness.run import main as harness_main
from atoms_mul.harness.run import run as harness_run


def run(**kwargs):
    return harness_run(track="machine", **kwargs)


def main(argv=None):
    return harness_main(["--track", "machine", *(argv if argv is not None else sys.argv[1:])])


if __name__ == "__main__":
    main()
