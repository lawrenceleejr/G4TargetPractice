"""Deprecated: `python -m g4tp` -> `gdmltp` CLI (see g4tp/__init__.py)."""
import sys

from gdmltp.cli import main

if __name__ == "__main__":
    sys.exit(main())
