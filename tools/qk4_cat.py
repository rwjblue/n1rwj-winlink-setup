"""Native K4 power frames, avoiding Hamlib's incompatible K3 power setters."""

import re
import socket
import time

from station_config import config


def native_power(set_frame=None):
    cfg = config()
    if set_frame is not None and not re.fullmatch(rb"PC\d{3}[HLX]", set_frame):
        raise ValueError("Invalid native K4 power frame")
    with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2) as cat:
        cat.settimeout(2)
        if set_frame is not None:
            cat.sendall(set_frame + b";")
        cat.sendall(b"PC;")
        pending = b""
        while True:
            part = cat.recv(4096)
            if not part:
                raise RuntimeError("QK4 closed before power readback")
            pending += part
            if len(pending) > 4096:
                raise RuntimeError("Oversized power reply")
            while b";" in pending:
                frame, pending = pending.split(b";", 1)
                if re.fullmatch(rb"PC\d{3}[HLX]", frame):
                    return frame


def require_five_watt_limit():
    frame = native_power()
    if frame[-1:] != b"L" or not 0 < int(frame[2:5]) <= 50:
        raise RuntimeError(
            f"RF startup requires QK4 QRP power from 0.1 to 5.0 W; got {frame.decode()}"
        )
    return int(frame[2:5]) / 10


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
                raise RuntimeError("QK4 disconnected before receive readback")
            pending += part
            if b"TQ0;" in pending:
                return
            if len(pending) > 4096:
                raise RuntimeError("Oversized QK4 status reply")
            pending = pending[-32:]
            time.sleep(0.1)
    raise RuntimeError("QK4 did not report receive before the deadline")
