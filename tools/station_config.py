import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def config(root=None):
    root = root or ROOT
    values = tomllib.loads((root / "config/station.toml").read_text())
    local = root / "config/station.local.toml"
    if local.exists():
        overrides = tomllib.loads(local.read_text())
        if overrides.keys() - values.keys():
            raise ValueError("Unknown station configuration keys")
        values.update(overrides)
    for key in ("qk4_rx_volume", "qk4_mic_gain"):
        if type(values[key]) is not int or not 0 <= values[key] <= 100:
            raise ValueError(f"{key} must be an integer from 0 to 100")
    for key in ("amplitude", "ptt_lead_seconds", "tx_tail_seconds", "max_key_seconds"):
        value = values[key]
        upper = {
            "amplitude": 1,
            "ptt_lead_seconds": 2,
            "tx_tail_seconds": 2,
            "max_key_seconds": 30,
        }[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= upper
        ):
            raise ValueError(f"{key} must be a number from 0 to {upper}")
    if values["max_key_seconds"] <= 0:
        raise ValueError("max_key_seconds must be positive")
    return values
