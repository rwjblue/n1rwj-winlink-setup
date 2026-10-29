# Station evidence — 2026-10-28

**Current state: RF keying and output have been verified on the approved
antenna at a 5 W setting. The first RMS did not answer. The stack is stopped;
QK4 exited and the Mac is locked, preventing app controls from reopening it.
No RMS link or end-to-end HF message transfer is claimed.**

Test environment: Apple Silicon arm64 macOS; mise Python 3.14.4, Go 1.26.2,
uv 0.11.7; Pat v1.0.0 at the pinned source revision; hfmodem/hfhost/creance
0.3.4; installed QK4 `0.7.0-dev.1d7de138`; Homebrew Hamlib 4.7.2 and Qt 6.11.2.
QK4 was reused rather than rebuilt or replaced.

## Verified

| Area | Observation | Reproduce |
|---|---|---|
| Dependency setup | Pinned tools installed; project venv sync reran successfully. Fresh upstream checkout also materializes its files. | `mise run setup` |
| Project configuration | Actual Pat resolves N1RWJ/FN41fr and local config/mailbox paths from a fresh copy of checked-in files, with reused installed runtimes and no ignored configuration. Both mise task and repo PATH launcher work. | `mise run config`, `mise run pat -- env`, `mise exec -- pat env` |
| Pat/Kestrel | Pat reports `VARA modem (4.9.0.KestrelOpen) initialized`; HTTP status lists `varahf`. Both TCP ports attached. | `mise run start`, `mise run doctor` |
| CAT reads | Hamlib K4 model 2047 reads frequency, mode, bandwidth and PTT through guarded QK4 CAT. | `mise run doctor` |
| Pat frequency selection | Pat QSY set 14.1015 MHz USB/2800 Hz; readback matched. Original 14.0123 MHz CW/400 Hz was restored and PTT remained off. | `mise run receive-check` |
| Native power setting | `PC050L` read back as 5.0 W; original `PC075H` was restored. TQ0 was verified before, during and after; no audio or key-up generated. | Controlled native CAT check; archived `logs/power-check.log` |
| Live RX | Ten seconds of EM0/SL0 K4 audio captured through QK4/Loopback at 48 kHz. Main RMS -35.99 dBFS, peak -16.21 dBFS, no clipped samples; right/sub channel silent. | `mise run receive-check` |
| Exact QK4 format | Qt accepts 12 kHz stereo Float32; QK4 log confirms it opened `K4 RX to WSJT-X` with that format. | `mise run qt-audio-probe` and app logs |
| RX cable conversion | 12->48 kHz chirp, gain 0.999333, residual SNR 63.0 dB, estimated latency 16.02 ms, no stream errors. QK4 was disconnected for the injected cable signal. | `mise run audio -- cable --direction rx` |
| TX cable | 48 kHz chirp, gain 1.0, residual SNR >130 dB, estimated latency 16.0 ms, no stream errors. QK4 gate explicitly closed. | `mise run audio -- cable --direction tx` |
| Pat/Hamlib PTT bench | Actual Pat and Hamlib produced TX/RX/TX/RX on a simulated K4. Key notification to CAT ~1.33 ms; unkey ~0.70 ms. Missing OFF forced unkey at the bench's 0.5 s deadline. No audio/radio opened. | `mise run bench-ptt` |
| Interlocks/configuration | Twenty-three local tests pass, including fresh configuration, runtime drift/backup, environment isolation, receive-only refusal, CAT policy/deadman, native power limits, closing-ID ordering, bounded cancellation and delayed unkey readback. | `mise run check` |
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

Generated evidence remains private. The initial test artifacts were moved
intact to `~/Library/Application Support/n1rwj-winlink-setup/archives/20261028T235918620272Z/.local`.
That includes `logs`, `receive-raw.wav` and `radio-before-receive-test.json`.
New runs write to the usual ignored `.local` paths. QK4 preference backups
remain under the adjacent `backups` directory outside the repository.

## Remaining gates

1. Unlock the Mac and reopen/connect QK4. The user already approved antenna
   RF tests on 40m/20m at 5 W; no repeat RF approval is needed for this work.
2. Try another current RMS, with receive recording and corrected closing-ID
   order. KB8AY on 7.100 MHz / BW2750 is a candidate with upstream
   interoperability evidence, listed 1013 km from the configured grid.
3. Qualify leading/trailing waveforms and physical unkey on an interrupted
   RF client. Normal live key/unkey is observed; deliberate loss/deadman
   tests so far use a simulated transmitter.
4. Measure radio/network turnaround and qualify PTT lead/tail against VARA
   response windows. Local cable latency is insufficient.
5. After a radio link succeeds, configure Winlink credentials via keychain
   and test message transfer plus destination receipt. The user explicitly
   chose radio-link testing before supplying credentials.
6. No CRC-valid VARA frame has yet been identified in this station's off-air
   audio. Live audio and offline codec tests remain separate evidence.

## First live RF trial

On 2026-10-28 the operator authorized the current antenna instead of a dummy
load and reported turning the radio down to 5 W. Native PC050L readback
confirmed the setting; QK4's amplifier integration was disabled.

The standalone CW test's preflight classifier refused its first channel and
never keyed. A subsequent real Pat attempt to W2KBF-1 on 7.050 MHz / BW500
waited for Kestrel's BUSY OFF and transmitted connect requests at
23:17–23:18 UTC. No gateway response or HF CONNECTED was observed. The call
was cancelled through Pat.

Evidence from QK4 and the live CAT stream:

- QK4 opened WSJT-X TX to K4 at 48 kHz mono Float32 and decimated to 12 kHz.
- TQ1 was observed during bursts; TQ0 between bursts and afterward.
- Native power remained PC050L. K4's internal forward meter peaked at 5.8 W;
  reported ALC peak was zero and SWR peak 1.0:1. This is internal telemetry,
  not an independently calibrated external wattmeter.
- Closing CW identification was sent. Its original callback order allowed
  Pat's QSX frequency restoration to overlap the ID. The launcher now sends
  ID and PTT OFF before reporting DISCONNECTED. That correction is unit
  tested and awaits the next live trial.
- Sampled cached TQ receive readback followed the audio completion record
  with median 0.462 s / maximum 0.569 s over 17 bursts. This combines state
  caching/polling and radio/audio delay; it is not calibrated RF turnaround.

Evidence is in the archive's `.local/logs/first-rf-telemetry.jsonl`,
`kestrel.log` and QK4 audio log. The trial preceded automatic
RF-session receive recording, so its RX waveform was not saved. Metering
establishes RF output and key/unkey; no independent receiver has decoded the
transmitted waveform.

The upstream audio driver labels transmissions dry_run when it has no rig
controller. Here Pat owns PTT, so that label is not an RF result. Independent
QK4 meter/TQ observations establish that RF occurred. The new bounded
link-test has been dry-run/unit tested; its on-air execution awaits QK4
being available again. Mail authentication and transfer have not been tested.

## Long-running receive fix

A longer receive run exposed Pat modem reconnects. Stack dumps located the
owner in the optional VarAC UI turbo decoder, processing unrelated audio
while ARQ polling and IAMALIVE stalled. The Winlink launcher now leaves that
optional decoder off on every ARQ station replacement. Three successive
minute heartbeats were observed on one live attachment after the fix; CPU
use dropped from roughly one saturated core to a few percent. The ARQ
receiver remains enabled.
