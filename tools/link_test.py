"""Bound one approved Pat VARA radio-link attempt and always cancel on timeout."""

import argparse
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from qk4_cat import require_five_watt_limit, wait_for_receive
from station import LOCAL
from station_config import config


def api(path, data=None, timeout=3):
    cfg = config()
    request = urllib.request.Request(
        f"http://127.0.0.1:{cfg['http_port']}/api/{path}", data=data
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def cancel_attempt(worker):
    try:
        api("disconnect", b"")
        shutdown_deadline = time.monotonic() + 12
        while time.monotonic() < shutdown_deadline:
            status = api("status")
            if not status.get("connected") and not status.get("dialing"):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Pat did not finish cancellation")
        worker.join(timeout=2)
        wait_for_receive()
    except BaseException:
        # A failed control request must not leave an unattended RF operation.
        (LOCAL / "stop-request").touch()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="VARA URL from the current Pat RMS list")
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-transmit", action="store_true")
    args = parser.parse_args()
    url = urllib.parse.urlparse(args.url)
    params = urllib.parse.parse_qs(url.query)
    frequency = float(params.get("freq", ["0"])[0])
    if url.scheme != "varahf" or not url.path.strip("/"):
        parser.error("Use a varahf URL containing the RMS callsign")
    if not (7000 <= frequency <= 7300 or 14000 <= frequency <= 14350):
        parser.error("Use a listed 40m or 20m dial frequency in kHz")
    if not 5 <= args.seconds <= 120:
        parser.error("Attempt duration must be 5 to 120 seconds")
    plan = {
        "url": args.url,
        "maximum_attempt_seconds": args.seconds,
        "power_limit_w": 5,
        "stop_after": "HF link is observed, or the attempt deadline; mail authentication is deferred",
    }
    print(json.dumps(plan, indent=2), flush=True)
    if not args.execute:
        print("DRY RUN: no network, audio or CAT access")
        return
    if not args.approved_transmit:
        parser.error("RF execution requires the operator-approved transmit flag")
    state = json.loads((LOCAL / "station.json").read_text())
    if not state.get("transmit"):
        raise SystemExit("Start the approved foreground RF station first")
    print(f"Power readback: {require_five_watt_limit():.1f} W", flush=True)
    initial = api("status")
    if initial.get("connected") or initial.get("dialing"):
        raise SystemExit("An exchange is already active; refusing to interrupt it")
    outcome = {}

    def connect():
        try:
            data = urllib.parse.urlencode({"url": args.url}).encode()
            outcome["reply"] = api("connect", data, timeout=args.seconds + 20)
        except (OSError, urllib.error.HTTPError, ValueError) as error:
            outcome["connect_result"] = str(error)

    worker = threading.Thread(target=connect, daemon=True)
    connected = False
    worker.start()
    deadline = time.monotonic() + args.seconds
    try:
        while worker.is_alive() and time.monotonic() < deadline:
            status = api("status")
            require_five_watt_limit()
            if status.get("connected"):
                connected = True
                break
            time.sleep(0.25)
    except BaseException:
        # Loss of telemetry or a power-limit violation must close the CAT
        # gate immediately rather than permit another normal over or CW ID.
        (LOCAL / "stop-request").touch()
        raise
    finally:
        # Closing an HTTP request does not cancel Pat's radio operation.
        # Explicitly abort, then allow closing ID/PTT OFF to finish.
        if not (LOCAL / "stop-request").exists():
            cancel_attempt(worker)
    outcome.update(
        {
            "hf_connected": connected,
            "radio_unkeyed": True,
            "mail_tested": False,
            "url": args.url,
        }
    )
    (LOCAL / "logs/link-test-result.json").write_text(json.dumps(outcome, indent=2))
    print(json.dumps(outcome, indent=2))
    if not connected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
