import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def config():
    values = tomllib.loads((ROOT / "config/station.toml").read_text())
    local = ROOT / "config/station.local.toml"
    if local.exists():
        overrides = tomllib.loads(local.read_text())
        if overrides.keys() - values.keys():
            raise ValueError("Unknown station configuration keys")
        values.update(overrides)
    return values
