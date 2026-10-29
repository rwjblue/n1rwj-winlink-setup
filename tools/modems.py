"""The mutually exclusive station modem choices and Pat transport names."""

import json

from cli import ConfigError
from station_config import ROOT

MODEMS = {
    "vara": {
        "transport": "varahf",
        "process": "kestrel",
        "port": 8300,
        "ready": "Kestrel ready",
    },
    "ardop": {
        "transport": "ardop",
        "process": "ardop",
        "port": 8515,
        "ready": "ARDOP ready",
    },
}


def active_modem(root=None):
    state = (root or ROOT) / ".local/station.json"
    name = (
        json.loads(state.read_text()).get("modem", "vara") if state.exists() else "vara"
    )
    if name not in MODEMS:
        raise ConfigError(f"Unknown active station modem: {name}")
    return name


def validate_pat_configuration(pat, cfg, modem):
    selected = MODEMS[modem]
    transport = selected["transport"]
    expected = {"addr": f"127.0.0.1:{selected['port']}", "rig": "qk4", "ptt_ctrl": True}
    if modem == "ardop":
        expected["beacon_interval"] = 0
    rig = {"network": "tcp", "address": f"127.0.0.1:{cfg['rigctld_port']}", "VFO": ""}
    if (
        any(pat.get(transport, {}).get(k) != v for k, v in expected.items())
        or pat.get("hamlib_rigs", {}).get("qk4") != rig
        or pat.get("schedule")
        or pat.get("listen") != [transport]
    ):
        raise ConfigError(
            "Pat configuration bypasses the supervised path or enables other listeners/jobs; "
            "inspect .local/pat/config.json"
        )
