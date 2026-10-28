"""Run upstream Pat with this repository's configuration and local state."""

import os
import sys

from pat_config import pat_args, pat_environment


def main():
    os.umask(0o077)
    if any(arg in {"init", "configure"} for arg in sys.argv[1:2]):
        raise SystemExit(
            "This station is already configured. Edit config/station.toml or config/pat.json, "
            "then restart the station. Use mise run config to inspect the generated paths."
        )
    args = pat_args()
    os.execve(args[0], [*args, *sys.argv[1:]], pat_environment())


if __name__ == "__main__":
    main()
