"""Use upstream audio interfaces, with an independent receive-only interlock."""

import argparse
import signal
import sys
import time

from station_config import ROOT, config

sys.path.insert(0, str(ROOT / ".cache/upstream/hfmodem/tools"))
from kestrel_connect import AudioVaraIO  # noqa: E402
from hfmodem.kestrel.host.audio_runtime import AudioHostRuntime  # noqa: E402
from hfmodem.kestrel.host.server import VaraServer  # noqa: E402


class StationAudio(AudioVaraIO):
    def __init__(self, cfg, transmit):
        super().__init__(
            cfg["tx_device"],
            cfg["rx_device"],
            cfg["amplitude"],
            tx_tail=cfg["tx_tail_seconds"],
        )
        self.transmit = transmit
        self.lead = cfg["ptt_lead_seconds"]

    def key(self, on):
        if on and not self.transmit:
            raise PermissionError("Receive-only: modem key-up refused")
        # No CAT here: Pat alone handles PTT notifications through Hamlib.
        return super().key(on)

    def tx(self, samples, *args, **kwargs):
        if not self.transmit:
            raise PermissionError("Receive-only: audio transmission refused")
        time.sleep(self.lead)
        return super().tx(samples, *args, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-transmit", action="store_true")
    args = parser.parse_args()
    cfg = config()
    audio = StationAudio(cfg, args.approved_transmit)
    runtime = AudioHostRuntime(audio)
    server = VaraServer(
        host="127.0.0.1",
        cmd_port=8300,
        data_port=8301,
        modem_factory=runtime.modem_factory,
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
