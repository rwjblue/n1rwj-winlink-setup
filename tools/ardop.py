"""Besra ARDOP over Loopback; Pat alone owns guarded CAT/PTT."""

import argparse
import datetime
import logging
import signal
import threading

import numpy as np

from hfmodem.besra.arq.modem import BesraModem
from hfmodem.besra.host.server import HostServer
from hfmodem.besra.phy.demodulator import SAMPLE_RATE
from hfmodem.besra.radio import FS_RADIO, RadioLink, to_card
from hfmodem.core import levels
from hfmodem.core.audio import play_drained

from cli import UserError, run_cli
from station_config import ROOT, config


class StationModem(BesraModem):
    def __init__(self, *, transmit=False, **kwargs):
        super().__init__(**kwargs)
        self.transmit_enabled = transmit

    def require_transmit(self):
        if not self.transmit_enabled:
            raise PermissionError("Receive-only: ARDOP transmission refused")

    def connect(self, target, repeats=5):
        self.require_transmit()
        return super().connect(target, repeats)

    def set_listen(self, on):
        # Pat's listener must attach for monitoring and health checks, but
        # ARDOP LISTEN means answering calls. Keep the actual ARQ core passive.
        if on and not self.transmit_enabled:
            print(
                "Receive-only: ARDOP listener is passive; incoming replies disabled",
                flush=True,
            )
        return super().set_listen(on and self.transmit_enabled)

    def transmit(self, blob):
        if not self.transmit_enabled:
            self.status("Receive-only: outbound data refused")
            return
        return super().transmit(blob)

    def _emit_samples(self, samples, **kwargs):
        # Covers ID, closing/periodic ID, two-tone and any future ARQ reply
        # before upstream can even notify Pat to key the radio.
        self.require_transmit()
        return super()._emit_samples(samples, **kwargs)


class StationAudio(RadioLink):
    def __init__(self, modem, cfg, *, transmit=False):
        self.transmit_enabled = transmit
        self.retiring = threading.Event()
        self.lead = cfg["ptt_lead_seconds"]
        self.tail = cfg["tx_tail_seconds"]
        record = None
        if transmit:
            folder = ROOT / ".local/recordings"
            folder.mkdir(parents=True, exist_ok=True)
            record = folder / datetime.datetime.now(datetime.UTC).strftime(
                "ardop-rx-%Y%m%dT%H%M%SZ.wav"
            )
        super().__init__(
            modem,
            in_device=cfg["rx_device"],
            out_device=cfg["tx_device"],
            rig=None,
            record=record,
            drive=cfg["amplitude"],
        )

    def _transmit(self, samples, drive=None, *, identification=False):
        if not self.transmit_enabled or self.retiring.is_set():
            raise PermissionError(
                "Receive-only or stopped: ARDOP transmit audio refused"
            )
        # Besra renders 12 kHz int16. Limit the peak after conversion to the
        # Loopback cable's 48 kHz, then fill both channels like Kestrel does.
        # Host DRIVELEVEL must never raise the station's configured ceiling.
        audio = levels.at_drive(to_card(samples, SAMPLE_RATE), self.drive)
        stereo = np.repeat(audio[:, None], 2, axis=1)
        self.muted = True
        self._rx.key_down()
        try:
            # Besra emitted PTT TRUE to Pat before calling this sink. Pat
            # forwards it through rigctld and the independent CAT deadman.
            if self.retiring.wait(self.lead):
                raise ConnectionAbortedError("ARDOP audio retired before playback")
            play_drained(stereo, FS_RADIO, self.out_device)
            self.bursts_sent += 1
            self.retiring.wait(self.tail)
        finally:
            self.muted = False

    def close(self):
        self.retiring.set()
        return super().close()


def check_health(modem, audio, server):
    if not server._running:
        raise UserError("ARDOP host stopped")
    for name, thread in (("timer", modem._pump), ("receiver", audio._pump)):
        if thread is None or not thread.is_alive():
            raise UserError(f"ARDOP {name} stopped")
    if audio._stream is None or not audio._stream.active:
        raise UserError("ARDOP capture stream stopped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-transmit", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    modem = StationModem(transmit=args.approved_transmit, bandwidth=2000, threaded=True)
    audio = StationAudio(modem, config(), transmit=args.approved_transmit)
    server = HostServer(modem, host="127.0.0.1", control_port=8515, data_port=8516)
    server._cfg.update(LISTEN="FALSE", ARQBW="2000MAX")
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    try:
        audio.start()
        server.start()
        check_health(modem, audio, server)
        print(
            f"ARDOP ready on 8515/8516; transmit={args.approved_transmit}", flush=True
        )
        while not stopping.wait(0.1):
            check_health(modem, audio, server)
    finally:
        # Retire output before waiting on a host thread inside a transmission.
        # The supervisor closes CAT first, independently of these audio waits.
        modem.transmit_enabled = False
        audio.retiring.set()
        try:
            server.stop()
        finally:
            audio.close()


if __name__ == "__main__":
    run_cli(main)
