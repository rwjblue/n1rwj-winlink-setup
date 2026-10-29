"""Bound one approved Pat VARA radio-link attempt and always cancel on timeout."""

import argparse
import contextlib
import datetime
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from qk4_cat import (
    DATA_A_BANDWIDTH,
    is_data_a,
    operating_state,
    native_power,
    restore_frequency,
    select_data_a,
    wait_for_receive,
)
from station import LOCAL
from station_config import config


def api(path, data=None, timeout=3):
    cfg = config()
    request = urllib.request.Request(
        f"http://127.0.0.1:{cfg['http_port']}/api/{path}",
        data=data,
        headers={"Content-Type": "application/json"} if path == "qsy" else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def require_frequency(hz, settle_seconds=0, stable_seconds=0):
    deadline = time.monotonic() + settle_seconds
    matching_since = None
    while True:
        state = operating_state()
        now = time.monotonic()
        if (
            int(state["FA"]) == hz
            and is_data_a(state)
            and int(state["BW"]) * 10 >= DATA_A_BANDWIDTH
            and all(state[key] == "0" for key in ("FT", "RT", "XT"))
        ):
            if matching_since is None:
                matching_since = now
            if now - matching_since >= stable_seconds:
                return state
        else:
            matching_since = None
        if now >= deadline:
            raise RuntimeError(
                f"Expected {hz} Hz DATA-A normal, RX >=2800 Hz, split/RIT/XIT off; got {state}"
            )
        time.sleep(0.1)


@contextlib.contextmanager
def tuned_frequency(khz):
    previous = operating_state()
    if previous["TQ"] != "0":
        raise RuntimeError("Radio already transmitting; preflight refused")
    (LOCAL / "logs/link-test-radio-before.json").write_text(
        json.dumps(previous, indent=2)
    )
    hz = round(khz * 1000)
    try:
        api("qsy", json.dumps({"transport": "varahf", "freq": khz}).encode(), timeout=6)
        select_data_a()  # A band change can recall a different mode/filter.
        require_frequency(hz, settle_seconds=5, stable_seconds=1)
        print(
            f"Frequency verified before CONNECT: {hz} Hz DATA-A normal, RX >=2800 Hz, split/RIT/XIT off",
            flush=True,
        )
        yield hz
    finally:
        # Pat sees the pre-tuned frequency as its QSX return. Restore the
        # original operator frequency ourselves, after cancellation/unkey.
        try:
            if (LOCAL / "stop-request").exists():
                deadline = time.monotonic() + 8
                while (LOCAL / "station.json").exists():
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "RF stack did not stop; frequency restoration deferred"
                        )
                    time.sleep(0.1)
            restore_frequency(int(previous["FA"]))
        except BaseException:
            (LOCAL / "stop-request").touch()
            raise


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
        if worker.is_alive():
            raise RuntimeError("Pat's dial request is still running after cancellation")
        wait_for_receive()
    except BaseException:
        # A failed control request must not leave an unattended RF operation.
        (LOCAL / "stop-request").touch()
        raise


def stop_rf_stack():
    # Pat can acknowledge cancellation while a BUSY wait still owns a queued
    # dial. Remove its physical transmit capability before waiting on HTTP.
    (LOCAL / "stop-request").touch()
    deadline = time.monotonic() + 12
    while (LOCAL / "station.json").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("RF stack did not stop at the attempt deadline")
        time.sleep(0.05)
    wait_for_receive(request_rx=True)


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
        "power": "radio's current setting (unchanged)",
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

    with tuned_frequency(frequency) as hz:
        # Report the selected band's setting without imposing a power policy.
        outcome["power_readback"] = native_power().decode()
        print(
            f"Power readback: {outcome['power_readback']} (radio controlled)",
            flush=True,
        )
        worker = threading.Thread(target=connect, daemon=True)
        connected = False
        expired = threading.Event()

        def expire():
            expired.set()
            outcome["deadline_requested_utc"] = datetime.datetime.now(
                datetime.UTC
            ).isoformat()
            (LOCAL / "stop-request").touch()

        # The timer must run independently of blocked HTTP/CAT operations.
        timer = threading.Timer(args.seconds, expire)
        timer.daemon = True
        outcome["rf_deadline_utc"] = (
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(seconds=args.seconds)
        ).isoformat()
        timer.start()
        worker.start()
        deadline = time.monotonic() + args.seconds
        try:
            while worker.is_alive() and time.monotonic() < deadline:
                status = api("status")
                require_frequency(hz)
                if status.get("connected"):
                    connected = True
                    break
                time.sleep(0.25)
        except BaseException as error:
            # Loss of telemetry or frequency drift closes
            # the CAT gate immediately, without another normal over or ID.
            stop_rf_stack()
            if not expired.is_set() or isinstance(
                error, (KeyboardInterrupt, SystemExit)
            ):
                raise
        finally:
            if time.monotonic() >= deadline:
                expired.set()
            try:
                if connected and not expired.is_set():
                    try:
                        cancel_attempt(worker)
                    finally:
                        stop_rf_stack()
                else:
                    stop_rf_stack()
                worker.join(timeout=2)
                outcome["rf_stack_stopped_utc"] = datetime.datetime.now(
                    datetime.UTC
                ).isoformat()
            finally:
                timer.cancel()
    outcome.update(
        {
            "hf_connected": connected,
            "radio_unkeyed": True,
            "mail_tested": False,
            "url": args.url,
            "attempt_end": "deadline"
            if expired.is_set()
            else "hf_connected"
            if connected
            else "no_link",
        }
    )
    (LOCAL / "logs/link-test-result.json").write_text(json.dumps(outcome, indent=2))
    print(json.dumps(outcome, indent=2))
    if not connected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
