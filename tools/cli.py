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


def log_error(message, path, offset=0):
    """Include recent process output, restricted to this launch when possible."""
    try:
        with path.open("rb") as log:
            log.seek(0, 2)
            start = max(offset, log.tell() - 8192)
            log.seek(start)
            output = log.read().decode("utf-8", errors="replace").strip()
    except OSError:
        output = ""
    if output:
        return UserError(f"{message}\n{output}")
    return UserError(f"{message}\nNo process output available in {path}.")
