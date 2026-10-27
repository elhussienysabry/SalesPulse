"""Allow ``python -m salespulse`` as a shorthand for the CLI."""

from salespulse.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
