"""Offline VARA codec round trip through raw PCM or QK4's Opus TX settings.

No sound devices, CAT connections or RF. This models QK4's outbound encoder;
it does not establish the K4's receive encoder configuration or RF performance.
"""

import ctypes as C
import json

import numpy as np
from hfmodem.kestrel.rx import varahf2300 as rx
from hfmodem.kestrel.tx import varahf2300_tx as tx
from scipy import signal


def opus_roundtrip(audio, frame_samples):
    opus = C.CDLL("/Applications/QK4.app/Contents/Frameworks/libopus.0.dylib")
    fp = C.POINTER(C.c_float)
    bp = C.POINTER(C.c_ubyte)
    for name in ("opus_encoder_create", "opus_decoder_create"):
        getattr(opus, name).restype = C.c_void_p
    opus.opus_encoder_create.argtypes = [C.c_int, C.c_int, C.c_int, C.POINTER(C.c_int)]
    opus.opus_decoder_create.argtypes = [C.c_int, C.c_int, C.POINTER(C.c_int)]
    opus.opus_encode_float.argtypes = [C.c_void_p, fp, C.c_int, bp, C.c_int]
    opus.opus_decode_float.argtypes = [C.c_void_p, bp, C.c_int, fp, C.c_int, C.c_int]
    opus.opus_encoder_ctl.argtypes = [C.c_void_p, C.c_int]
    opus.opus_encoder_destroy.argtypes = [C.c_void_p]
    opus.opus_decoder_destroy.argtypes = [C.c_void_p]
    error = C.c_int()
    encoder = opus.opus_encoder_create(
        12000, 1, 2048, C.byref(error)
    )  # OPUS_APPLICATION_VOIP
    if error.value:
        raise RuntimeError(f"Opus encoder error {error.value}")
    decoder = opus.opus_decoder_create(12000, 1, C.byref(error))
    if error.value:
        raise RuntimeError(f"Opus decoder error {error.value}")
    try:
        result = opus.opus_encoder_ctl(
            encoder, 4002, C.c_int(24000)
        )  # OPUS_SET_BITRATE
        if result:
            raise RuntimeError(f"Opus bitrate error {result}")
        blocks = []
        packet = (C.c_ubyte * 4000)()
        padded = np.pad(audio, (0, (-len(audio)) % frame_samples)).astype("float32")
        for offset in range(0, len(padded), frame_samples):
            part = np.ascontiguousarray(padded[offset : offset + frame_samples])
            size = opus.opus_encode_float(
                encoder, part.ctypes.data_as(fp), frame_samples, packet, 4000
            )
            if size < 0:
                raise RuntimeError(f"Opus encode error {size}")
            output = np.zeros(frame_samples, dtype="float32")
            count = opus.opus_decode_float(
                decoder, packet, size, output.ctypes.data_as(fp), frame_samples, 0
            )
            if count < 0:
                raise RuntimeError(f"Opus decode error {count}")
            blocks.append(output[:count])
        return np.concatenate(blocks)
    finally:
        opus.opus_encoder_destroy(encoder)
        opus.opus_decoder_destroy(decoder)


def main():
    rows = []
    for level in rx.LEVELS:
        payload = (
            np.random.default_rng(1000 + level)
            .integers(0, 256, rx.payload_bytes(level), dtype=np.uint8)
            .tobytes()
        )
        original = tx.synth_burst(payload, level).astype("float32")
        original *= 0.1 / np.max(np.abs(original))
        down = signal.resample_poly(np.pad(original, (4800, 9600)), 1, 4)
        variants = [
            ("raw24", np.round(down * 2**23) / 2**23),
            ("opus-sl0-20ms", opus_roundtrip(down, 240)),
            ("opus-sl3-60ms", opus_roundtrip(down, 720)),
        ]
        for mode, encoded in variants:
            decoded = signal.resample_poly(encoded, 4, 1)
            offset = int(
                np.argmax(
                    signal.correlate(decoded, original, mode="valid", method="fft")
                )
            )
            aligned = decoded[offset : offset + len(original)]
            frame = rx.decode_burst(aligned, level)
            gain = np.dot(aligned, original) / np.dot(original, original)
            snr = 10 * np.log10(
                np.mean((gain * original) ** 2)
                / np.mean((aligned - gain * original) ** 2)
            )
            rows.append(
                {
                    "level": level,
                    "mode": mode,
                    "crc_ok": bool(frame.crc_ok),
                    "byte_exact": frame.payload == payload,
                    "residual_snr_db": round(float(snr), 2),
                }
            )
    print(
        json.dumps(
            {
                "settings": "QK4 TX: 12 kHz mono, VOIP, 24 kbit/s; local libopus",
                "scope": "BW2300 MFSK records 0-3, one payload each; no RF or high-speed OFDM",
                "results": rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
