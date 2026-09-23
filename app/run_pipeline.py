"""Convenience entry point for the same pipeline used by the scheduler."""

import sys

from app.scheduler import main

if __name__ == "__main__":
    raise SystemExit(main(["run-now", *sys.argv[1:]]))
