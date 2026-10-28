"""Use upstream audio interfaces, with an independent receive-only interlock."""

import argparse
import datetime
import faulthandler
import queue
import signal
import sys
import time

from station_config import ROOT, config

sys.path.insert(0, str(ROOT / ".cache/upstream/hfmodem/tools"))
from kestrel_connect import AudioVaraIO  # noqa: E402
from hfmodem.kestrel.host.audio_runtime import AudioHostRuntime  # noqa: E402
from hfmodem.kestrel.host.server import VaraServer  # noqa: E402
from hfmodem.kestrel.host.vara_modem import VaraHostModem  # noqa: E402
from hfmodem.core import cwid  # noqa: E402


class WinlinkModem(VaraHostModem):
    def start(self, observer):
        modem = self

        class IdentifiedObserver:
            def __getattr__(self, name):
                return getattr(observer, name)

            def modem_disconnected(self):
                modem.identify_if_pending()
                observer.modem_disconnected()

        super().start(IdentifiedObserver())

    def identify_if_pending(self):
        transport = self._transport
        if (
            self._stopping
            or not getattr(transport, "pending_id", False)
            or not getattr(transport, "transmit", False)
        ):
            return
        transport.pending_id = False
        print(
            "Sending closing CW identification before reporting DISCONNECTED",
            flush=True,
        )
        self.station.io.key(True)
        try:
            transport.tx(
                cwid.audio(config()["callsign"], fs=48000, tone_hz=1500),
                identification=True,
            )
        finally:
            self.station.io.key(False)

    def _new_station(self):
        station = super()._new_station()
        # The optional VarAC CQ/UI decoder can spend minutes turbo-decoding
        # non-VARA audio and starve ARQ owner polling/IAMALIVE. Winlink uses
        # the separate ARQ receiver; it needs no passive VarAC broadcasts.
        station.cq_detector = None
        return station


class WinlinkRuntime(AudioHostRuntime):
    def modem_factory(self):
        # Preserve the pinned upstream single-owner attachment queue.
        modem = WinlinkModem(
            self.transport, high_speed=self.high_speed, clock=self.clock
        )
        try:
            self._new.put_nowait(modem)
        except queue.Full:
            raise ConnectionAbortedError(
                "prior VARA attachment awaits its owner"
            ) from None
        return modem


class StationAudio(AudioVaraIO):
    def __init__(self, cfg, transmit):
        record = None
        if transmit:
            folder = ROOT / ".local/recordings"
            folder.mkdir(parents=True, exist_ok=True)
            record = folder / datetime.datetime.now(datetime.UTC).strftime(
                "rx-%Y%m%dT%H%M%SZ.wav"
            )
            print(f"RF session RX recording: {record}", flush=True)
        super().__init__(
            cfg["tx_device"],
            cfg["rx_device"],
            cfg["amplitude"],
            tx_tail=cfg["tx_tail_seconds"],
            record=record,
        )
        self.transmit = transmit
        self.lead = cfg["ptt_lead_seconds"]
        self.pending_id = False

    def key(self, on):
        if on and not self.transmit:
            raise PermissionError("Receive-only: modem key-up refused")
        # No CAT here: Pat alone handles PTT notifications through Hamlib.
        return super().key(on)

    def tx(self, samples, *args, **kwargs):
        if not self.transmit:
            raise PermissionError("Receive-only: audio transmission refused")
        time.sleep(self.lead)
        result = super().tx(samples, *args, **kwargs)
        if not kwargs.get("identification", False):
            self.pending_id = True
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-transmit", action="store_true")
    args = parser.parse_args()
    cfg = config()
    audio = StationAudio(cfg, args.approved_transmit)
    runtime = WinlinkRuntime(audio)
    faulthandler.register(signal.SIGUSR1, all_threads=True)

    def host_log(direction, message):
        stamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")
        print(f"{stamp} {direction}: {message}", flush=True)

    server = VaraServer(
        host="127.0.0.1",
        cmd_port=8300,
        data_port=8301,
        modem_factory=runtime.modem_factory,
        log=host_log,
    )
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        audio.start()
        server.start_background()
        print(
            f"Kestrel ready on 8300/8301; transmit={args.approved_transmit}", flush=True
        )
        while running:
            runtime.step()
    finally:
        server.stop()
        if runtime.modem:
            runtime.modem.stop()
            runtime.modem.poll()
        audio.stop()


if __name__ == "__main__":
    main()
