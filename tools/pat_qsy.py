"""Finish a Pat QSY with verified DATA-A and receive bandwidth; never key."""

import sys

from cli import run_cli
from qk4_cat import prepare_data_a


def main():
    selected = prepare_data_a(int(sys.argv[1]))
    print(
        f"Pat QSY ready: {int(selected['FA'])} Hz, DATA-A normal, "
        f"RX {int(selected['BW']) * 10} Hz",
        flush=True,
    )


if __name__ == "__main__":
    run_cli(main)
