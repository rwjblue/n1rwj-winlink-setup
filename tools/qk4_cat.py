"""Read native K4 state and request receive without changing RF power."""

import re
import socket
import subprocess
import time

from cli import UserError
from station_config import config

DATA_A_MODE = "PKTUSB"  # Hamlib: native K4 MD6;DT0; (normal, upper sideband).
DATA_A_BANDWIDTH = 2800


def rig(*args):
    return (
        subprocess.check_output(
            ["rigctl", "-m", "2", "-r", f"127.0.0.1:{config()['rigctld_port']}", *args],
            text=True,
            timeout=8,
        )
        .strip()
        .splitlines()
    )


def is_data_a(state):
    return state.get("MD") == "6" and state.get("DT") == "0"


def _wait_mode(expected, timeout=5):
    deadline = time.monotonic() + timeout
    matching_since = None
    while time.monotonic() < deadline:
        state = operating_state()
        now = time.monotonic()
        if state["TQ"] != "0":
            raise UserError("Radio keyed during mode change")
        if all(state[key] == value for key, value in expected.items()):
            if matching_since is None:
                matching_since = now
            if now - matching_since >= 1:
                return state
        else:
            matching_since = None
        time.sleep(0.1)
    raise UserError(f"Radio mode did not settle at {expected}; got {state}")


def select_data_a():
    """Select normal DATA-A through guarded Hamlib; never tunes or keys."""
    before = operating_state()
    if before["TQ"] != "0":
        raise UserError("Radio transmitting; DATA-A selection refused")
    bandwidth = max(DATA_A_BANDWIDTH, int(before["BW"]) * 10)
    expected = {"MD": "6", "DT": "0", "BW": f"{bandwidth // 10:04d}"}
    # After QSY, QK4 can briefly serve the previous band's DATA-A cache before
    # the K4 recalls USB/RTTY. Send the mode even when that first read matches.
    rig("M", DATA_A_MODE, str(bandwidth))
    _wait_mode({"MD": "6"})
    # The new band's DATA profile can recall FSK-D after Hamlib already sent
    # DT0. Select the submode again after DATA itself has settled, then BW last.
    cfg = config()
    with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2) as cat:
        cat.sendall(b"DT0;")
        selected = _wait_mode({"MD": "6", "DT": "0"})
        if int(selected["BW"]) * 10 >= bandwidth:
            return selected
        cat.sendall(f"BW{expected['BW']};".encode())
        return _wait_mode(expected)


def restore_mode(state):
    """Restore exact native mode/submode/filter after receive is confirmed."""
    expected = {key: state[key] for key in ("MD", "BW")}
    if not re.fullmatch(r"[12345679]", expected["MD"]) or not re.fullmatch(
        r"\d{4}", expected["BW"]
    ):
        raise ValueError("Invalid saved K4 mode/filter")
    if expected["MD"] in ("6", "9"):
        if not re.fullmatch(r"[0-3]", state["DT"]):
            raise ValueError("Invalid saved K4 data submode")
        expected["DT"] = state["DT"]
    wait_for_receive()
    cfg = config()
    with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2) as cat:
        cat.sendall(f"MD{expected['MD']};".encode())
        _wait_mode({"MD": expected["MD"]})
        if "DT" in expected:
            cat.sendall(f"DT{expected['DT']};MD{expected['MD']};".encode())
            _wait_mode({"MD": expected["MD"], "DT": expected["DT"]})
        cat.sendall(f"BW{expected['BW']};".encode())
        return _wait_mode(expected)


def native_power():
    cfg = config()
    with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2) as cat:
        cat.settimeout(2)
        cat.sendall(b"PC;")
        pending = b""
        while True:
            part = cat.recv(4096)
            if not part:
                raise UserError("QK4 closed before power readback")
            pending += part
            if len(pending) > 4096:
                raise UserError("Oversized power reply")
            while b";" in pending:
                frame, pending = pending.split(b";", 1)
                if re.fullmatch(rb"PC\d{3}[HLX]", frame):
                    return frame


def operating_state():
    """Read VFO A, mode and offsets independently of Hamlib's SET result."""
    cfg = config()
    patterns = {
        "FA": rb"FA\d{11}",
        "MD": rb"MD\d",
        "DT": rb"DT[0-3]",
        "BW": rb"BW\d{4}",
        "FT": rb"FT[01]",
        "RT": rb"RT[01]",
        "XT": rb"XT[01]",
        "TQ": rb"TQ[01]",
    }
    result = {}
    deadline = time.monotonic() + 2
    with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2) as cat:
        cat.settimeout(0.5)
        cat.sendall(b"FA;MD;DT;BW;FT;RT;XT;TQ;")
        pending = b""
        while time.monotonic() < deadline:
            try:
                part = cat.recv(4096)
            except TimeoutError:
                continue
            if not part:
                break
            pending += part
            if len(pending) > 4096:
                raise UserError("Oversized operating-state reply")
            while b";" in pending:
                frame, pending = pending.split(b";", 1)
                for key, pattern in patterns.items():
                    if re.fullmatch(pattern, frame):
                        result[key] = frame[2:].decode()
            if result.keys() == patterns.keys():
                return result
    raise UserError(f"Incomplete QK4 operating state: {result}")


def restore_frequency(hz):
    """Restore dial only after receive is confirmed; never sends a key request."""
    wait_for_receive()
    cfg = config()
    with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2) as cat:
        cat.sendall(f"FA{int(hz):011d};".encode())
        deadline = time.monotonic() + 5
        matching_since = None
        while time.monotonic() < deadline:
            state = operating_state()
            now = time.monotonic()
            if int(state["FA"]) == int(hz) and state["TQ"] == "0":
                if matching_since is None:
                    matching_since = now
                if now - matching_since >= 1:
                    return
            else:
                matching_since = None
            time.sleep(0.1)
    raise UserError(f"Frequency restoration to {hz} Hz was not confirmed")


def wait_for_receive(timeout=3, request_rx=False):
    """Poll actual TQ readback; the radio may still be unkeying on the first GET."""
    cfg = config()
    deadline = time.monotonic() + timeout
    with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2) as cat:
        cat.settimeout(min(timeout, 1))
        if request_rx:
            cat.sendall(b"RX;")
        pending = b""
        while time.monotonic() < deadline:
            cat.sendall(b"TQ;")
            try:
                part = cat.recv(4096)
            except TimeoutError:
                continue
            if not part:
                raise UserError("QK4 disconnected before receive readback")
            pending += part
            if b"TQ0;" in pending:
                return
            if len(pending) > 4096:
                raise UserError("Oversized QK4 status reply")
            pending = pending[-32:]
            time.sleep(0.1)
    raise UserError("QK4 did not report receive before the deadline")
