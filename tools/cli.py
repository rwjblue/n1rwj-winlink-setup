"""Present expected operator errors without hiding unexpected Python failures."""

import sys


class UserError(RuntimeError):
    """An expected failure with a message suitable for the operator."""


class ConfigError(UserError, ValueError):
    """Invalid operator configuration (also a ValueError for API callers)."""


def run_cli(main):
    try:
        main()
    except UserError as error:
        print(f"Error: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
