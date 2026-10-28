# Station evidence — 2026-10-28

**Current state: receive-only station prepared and verified; awaiting human
approval for the first dummy-load transmission. No RF was intentionally
transmitted during setup. No end-to-end HF message transfer is claimed.**

Test environment: Apple Silicon arm64 macOS; mise Python 3.14.4, Go 1.26.2,
uv 0.11.7; Pat v1.0.0 at the pinned source revision; hfmodem/hfhost/creance
0.3.4; installed QK4 `0.7.0-dev.1d7de138`; Homebrew Hamlib 4.7.2 and Qt 6.11.2.
QK4 was reused rather than rebuilt or replaced.

## Verified

| Area | Observation | Reproduce |
|---|---|---|
| Dependency setup | Pinned tools installed; project venv sync reran successfully. Fresh upstream checkout also materializes its files. | `mise run setup` |
| Pat/Kestrel | Pat reports `VARA modem (4.9.0.KestrelOpen) initialized`; HTTP status lists `varahf`. Both TCP ports attached. | `mise run start`, `mise run doctor` |
| CAT reads | Hamlib K4 model 2047 reads frequency, mode, bandwidth and PTT through guarded QK4 CAT. | `mise run doctor` |
| Pat frequency selection | Pat QSY set 14.1015 MHz USB/2800 Hz; readback matched. Original 14.0123 MHz CW/400 Hz was restored and PTT remained off. | `mise run receive-check` |
| Native power setting | `PC050L` read back as 5.0 W; original `PC075H` was restored. TQ0 was verified before, during and after; no audio or key-up generated. | Controlled native CAT check; `.local/logs/power-check.log` |
| Live RX | Ten seconds of EM0/SL0 K4 audio captured through QK4/Loopback at 48 kHz. Main RMS -35.99 dBFS, peak -16.21 dBFS, no clipped samples; right/sub channel silent. | `mise run receive-check` |
| Exact QK4 format | Qt accepts 12 kHz stereo Float32; QK4 log confirms it opened `K4 RX to WSJT-X` with that format. | `mise run qt-audio-probe` and app logs |
| RX cable conversion | 12->48 kHz chirp, gain 0.999333, residual SNR 63.0 dB, estimated latency 16.02 ms, no stream errors. QK4 was disconnected for the injected cable signal. | `mise run audio -- cable --direction rx` |
| TX cable | 48 kHz chirp, gain 1.0, residual SNR >130 dB, estimated latency 16.0 ms, no stream errors. QK4 gate explicitly closed. | `mise run audio -- cable --direction tx` |
| Pat/Hamlib PTT bench | Actual Pat and Hamlib produced TX/RX/TX/RX on a simulated K4. Key notification to CAT ~1.33 ms; unkey ~0.70 ms. Missing OFF forced unkey at the bench's 0.5 s deadline. No audio/radio opened. | `mise run bench-ptt` |
| Interlocks | Twelve local tests pass: receive-only key/audio refusal, CAT policy, framing, owner disconnect, deadline, supervisor loss, oversized input, RF approval entry gates and native K4 power formatting. | `mise run check` |
| Modem regression | 37 upstream host lifecycle and BW2300 codec tests passed. Synthetic payload recovery is not independent RF evidence. | Commands below |
| Failure shutdown | SIGKILL to the live receive-only Kestrel process caused all five station listener ports to close; normal restart reattached Pat. | Supervisor log; deliberate manual fault injection |

## Raw versus Opus diagnostic

Four deterministic payloads, one each at BW2300 MFSK records 0–3, were
synthesized, reduced to 12 kHz, processed, returned to 48 kHz, aligned and
decoded. Raw 24-bit, Opus SL0 and Opus SL3 each recovered **4/4 byte-exact,
CRC-valid payloads**. Residual waveform SNR was approximately:

| Path | SNR across four payloads |
|---|---|
| Raw 24-bit + resampling | 50.39–55.33 dB |
| QK4-style Opus, 20 ms | 17.61–20.00 dB |
| QK4-style Opus, 60 ms | 18.19–20.90 dB |

This models the QK4 transmit encoder using the installed app's libopus. It
does not test the K4 encoder, high-speed OFDM, fading, clipping or RF.
The chosen initial operating profile is raw EM0/SL0.

```sh
mise run codec-bench
.venv/bin/pytest -q \
  .cache/upstream/hfmodem/packages/hfmodem/hfmodem/tests/kestrel/test_vara_host_modem.py \
  .cache/upstream/hfmodem/packages/hfmodem/hfmodem/tests/kestrel/test_bw2300_roundtrip.py
```

Generated evidence is local and ignored: `.local/logs`,
`.local/receive-raw.wav`, `.local/radio-before-receive-test.json`.
QK4 preference backups live in the user's Library outside the repository.

## Remaining gates

1. **Human approval and physical preparation:** confirm a 50-ohm dummy load
   and bypassed external amplifier before the proposed 5 W, one-second tone.
2. Verify QK4 microphone permission, actual TX cable consumption and K4 RF
   output; calibrate levels against ALC and the wattmeter. The TX cable alone
   does not prove QK4's gated microphone/network transmit path.
3. Verify physical unkey, leading/trailing waveform integrity and behavior
   on a lost modem/PTT client while using the dummy load. Existing tests use
   a simulated transmitter or receive-only hardware.
4. Measure radio/network turnaround and decide whether PTT lead/tail need
   reduction for VARA's response windows. Local cable latency is insufficient.
5. With separate antenna/RMS approval, choose an active public VARA gateway,
   configure the Winlink account via keychain, and test reception followed by
   a message transfer and destination receipt.
6. No live CRC-valid VARA frame has yet been identified in this station's
   off-air recording. Live audio and offline codec functionality are verified
   separately.

The dry-run `tx-test` has been inspected and run without opening devices.
Its real-radio transmit execution and restoration paths remain unexecuted.
