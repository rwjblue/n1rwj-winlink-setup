"""Fetch frozen upstream source without touching any existing user checkout."""

import json
import pathlib
import subprocess

root = pathlib.Path(__file__).resolve().parents[1]
for name, item in json.loads((root / "upstream.lock.json").read_text()).items():
    dest = root / ".cache/upstream" / name
    created = not dest.exists()
    if created:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                "--no-checkout",
                item["url"],
                str(dest),
            ],
            check=True,
        )
    revision = subprocess.check_output(
        ["git", "-C", str(dest), "rev-parse", "HEAD"], text=True
    ).strip()
    if not created:
        dirty = subprocess.check_output(
            ["git", "-C", str(dest), "status", "--porcelain"], text=True
        )
        if dirty:
            raise SystemExit(f"Refusing to overwrite changes in {dest}")
    if created or revision != item["commit"]:
        present = (
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(dest),
                    "cat-file",
                    "-e",
                    item["commit"] + "^{commit}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
        if not present:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(dest),
                    "fetch",
                    "--depth=1",
                    "origin",
                    item["commit"],
                ],
                check=True,
            )
        subprocess.run(
            ["git", "-C", str(dest), "checkout", "--detach", item["commit"]], check=True
        )
    print(f"{name}: {item['commit']}")
