# Station evidence — 2026-10-28

**Current state: DATA-A normal is selected and the station is running
receive-only with QK4 Vail. Live receive, local TX cable fidelity, and outgoing
network audio with the K4 RF output inhibited in TX TEST have been verified.
Drive is calibrated at Kestrel peak 0.35 with QK4 mic gain 25: the real modem
waveform reached ALC 4 on both 40m and 20m with forward power zero.
Earlier RF trials used USB. No DATA-A on-air RMS link or HF message transfer
is claimed. Project `.env` credentials are loaded, but authentication remains
untested. The operator is continuing gateway connectivity testing.**

Test environment: Apple Silicon arm64 macOS; mise Python 3.14.4, Go 1.26.2,
uv 0.11.7; Pat v1.0.0 at the pinned source revision; hfmodem/hfhost/creance
0.3.4; QK4 Vail `0.8.0-beta.1.7-vail` (earlier trials used
`0.7.0-dev.1d7de138`); Homebrew Hamlib 4.7.2 and Qt 6.11.2. QK4 was reused.

## Verified

| Area | Observation | Reproduce |
|---|---|---|
| Dependency setup | Pinned tools installed; project venv sync reran successfully. Fresh upstream checkout also materializes its files. | `mise run setup` |
| Project configuration | Actual Pat resolves N1RWJ/FN41fr and local config/mailbox paths from a fresh copy of checked-in files, with reused installed runtimes and no ignored configuration. Both mise task and repo PATH launcher work. | `mise run config`, `mise run pat env`, `mise exec -- pat env` |
| Pat/Kestrel | Pat reports `VARA modem (4.9.0.KestrelOpen) initialized`; HTTP status lists `varahf`. Both TCP ports attached. | `mise run start --receive-only`, `mise run doctor` |
| CAT reads | Hamlib K4 model 2047 reads frequency, mode, bandwidth and PTT through guarded QK4 CAT. | `mise run doctor` |
| Pat frequency selection | Pat QSY at 7.055 MHz DATA-A normal, 3 kHz RX; native MD6/DT0/BW0300 and TQ0 matched before/after receive capture. | `mise run receive-check` |
| Native power setting | `PC050L` read back as 5.0 W; original `PC075H` was restored. TQ0 was verified before, during and after; no audio or key-up generated. | Controlled native CAT check; archived `logs/power-check.log` |
| Live RX | Ten seconds of DATA-A EM0/SL0 K4 audio through QK4/Loopback at 48 kHz. Main RMS -34.84 dBFS, peak -19.60 dBFS, no clipped samples. | `mise run receive-check` |
| Exact QK4 format | Qt accepts 12 kHz stereo Float32; QK4 log confirms it opened `K4 RX to WSJT-X` with that format. | `mise run qt-audio-probe` and app logs |
| RX cable conversion | 12->48 kHz chirp, gain 0.999333, residual SNR 63.0 dB, estimated latency 16.02 ms, no stream errors. QK4 was disconnected for the injected cable signal. | `mise run audio cable --direction rx` |
| TX cable | 48 kHz chirp, gain 1.0, residual SNR 132.41 dB, estimated latency 16.0 ms, no stream errors. QK4 gate closed; receive readback before/after. | `mise run audio cable --direction tx` |
| DATA-A outgoing audio | In confirmed K4 TX TEST, QK4 captured the TX cable at 48 kHz mono and converted 4:1 to 12 kHz. A 3.78-second CW ID produced 50 logical-TX samples; all 67 forward-meter samples were zero. TQ0 and DATA-A/3 kHz were restored; PC050H was unchanged. | `mise run tx-test --execute --radio-test-mode --dial-khz 7055` |
| Pat/Hamlib PTT bench | Actual Hamlib selected PKTUSB/2800, producing MD6/DT0 through the guard. Pat then produced TX/RX/TX/RX on a simulated K4. Key ~1.19 ms; unkey ~1.03 ms; 0.5 s deadman unkey passed. No real radio/audio opened. | `mise run bench-ptt` |
| Interlocks/configuration | 48 local tests pass, covering credentials, DATA-A/submode/filter validation, band recall ordering, routing/gain drift, TX TEST confirmation, drive overrides, real waveform normalization, zero-forward-power telemetry, cancellation and independent unkey. | `mise run check` |
| Modem regression | 37 upstream host lifecycle and BW2300 codec tests passed. Synthetic payload recovery is not independent RF evidence. | Commands below |
| Failure shutdown | SIGKILL to the live receive-only Kestrel process caused all five station listener ports to close; normal restart reattached Pat. | Supervisor log; deliberate manual fault injection |

## DATA-A audio verification

During the DATA-A change, the first receive capture was silent. QK4's saved
speaker selection was the system default and its microphone selection was
the built-in Mac microphone. Preferences were backed up privately and
`mise run configure-qk4` restored the named Loopback UIDs. Vail was relaunched
and reconnected to `K4-SN01967 Local`. Startup and `doctor` now detect this
saved-routing mismatch; they never print stored radio credentials.

The K4 initially recalled a 2.5 kHz filter after Hamlib's MD/BW/DT sequence.
The helper now waits for native MD6/DT0, applies BW0280 afterward if necessary,
and accepts wider filters. Live receive and the subsequent outgoing check
used the operator-selected 3 kHz filter at 7.055 MHz.

The outgoing test was performed with the K4 in TX TEST, positively observed
in QK4's VFO indicator before PTT. QK4's permanent TEST caption underneath
XMIT is excluded from that check. The client opened the correct mic cable,
the K4 reported logical TX, and the internal forward meter remained zero.
TX NORM was restored only after TQ0 was confirmed. This verifies the remote
audio/keying route with RF inhibited; it is not a DATA-A RF or RMS decode test.
No new gateway attempt or mail transfer was made.

Private evidence: `.local/logs/qk4-data-a.log`,
`.local/logs/tx-telemetry.json`, `.local/receive-data-a.wav`,
`.local/radio-before-receive-test.json` and `.local/tx-test-before.json`.
Preference backups remain under the private `backups` directory described
below, including `qk4-before-data-a-audio-20261029T025521495976Z.plist` and
`qk4-20261029T025539764629Z.plist`. Generated logs and audio are ignored by Git.

## Audio drive calibration

At the original 0.05 drive with QK4 mic gain 25, the DATA-A CW baseline
showed logical TX but ALC remained zero. The standalone test also had a separate
5 percent clamp, now removed. Its drive can be overridden only in confirmed
TX TEST. The sweep records each level and does not rewrite defaults.

Measured on 2026-10-28 Eastern, with raw EM0/SL0, DATA-A normal, 3 kHz RX
and QK4 mic gain 25. Native RF setting PC050H was unchanged; all forward-meter
samples were zero and compression remained zero:

| Waveform | Dial MHz | Peak drive | Peak ALC |
|---|---|---|---|
| CW ID | 7.101 | 0.05 | 0 |
| CW ID | 7.101 | 0.20 | 0 |
| CW ID | 7.101 | 0.40 | 4 |
| Kestrel BW2300 connect request | 7.101 | 0.40 | 5 |
| Kestrel BW2300 connect request | 7.101 | 0.30 | 2 |
| Kestrel BW2300 connect request | 7.101 | **0.35** | **4** |
| Kestrel BW2300 connect request | 14.1015 | **0.35** | **4** |

The modem waveform is synthesized by upstream `vara_mfsk.synth_burst` to
N0CALL and normalized with the same `levels.at_drive` used by AudioVaraIO.
This produces a 1.75-second test without opening an RMS session. The selected
0.35/25 pair was verified with 51 zero-forward-meter samples on 40m and 50 on
20m. ALC 4 meets the operating manual's guidance to stay below the "5" mark.
It is audio-drive qualification with RF inhibited, not measured RF output,
high-speed OFDM distortion, an RMS decode or a mail transfer.

The 20m check initially exposed asynchronous band/profile recall: QK4 briefly
served the previous band's DATA-A cache, then the radio recalled USB/FSK-D.
Mode, data submode and filter are now explicitly selected in separate settled
stages, including during restoration. The successful 20m test returned to
7.101 MHz DATA-A/3 kHz, TQ0. TX NORM was restored after unkey.

Defaults now use peak 0.35, 7 times the old amplitude (+16.9 dB), with QK4 mic
gain 25 unchanged. Startup and doctor verify saved gain as well as device IDs;
Kestrel logs its actual devices/drive. The calibration task now defaults to
the modem waveform and includes 0.30/0.35 in its sweep. RF power is still
selected on the radio, with no software power cap or writes.

Private per-level evidence is under `.local/logs/` in
`audio-calibration-20261029T034111078359Z` (CW baseline),
`audio-calibration-20261029T034215011592Z` (CW sweep),
`audio-calibration-20261029T034640494130Z` (modem 0.40),
`audio-calibration-20261029T034730637943Z` (modem 0.30/0.35), and
`audio-calibration-20261029T035305051340Z` (20m confirmation).
Each includes case logs, native snapshots and raw telemetry. Failed 20m
preflight attempts were refused before keying; their logs are also retained.

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

1. Complete a valid bounded RMS attempt after stable band/frequency selection.
   Use the operator's running QK4 Vail and radio-selected power setting.
2. Verify independent deadline shutdown on the live RF path. A receive-only
   deadline drill closed all five listeners and confirmed TQ0.
3. Qualify leading/trailing waveforms and physical unkey on an interrupted
   RF client. Normal live key/unkey is observed; deliberate loss/deadman
   tests so far use a simulated transmitter.
4. Measure radio/network turnaround and qualify PTT lead/tail against VARA
   response windows. Local cable latency is insufficient.
5. Winlink credentials are now supplied through the ignored root `.env`.
   Loading is verified without printing the password or writing it to Pat JSON.
   Authentication, message transfer and destination receipt remain untested;
   the operator chose to continue connectivity testing manually.
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

## QK4 Vail follow-up (2026-10-28, Eastern)

The operator reopened QK4 Vail `0.8.0-beta.1.7-vail` (bundle
`com.rwjblue.qk4.vail`), replacing the earlier app for live tests. The UI tool
could not attach to this bundle; its CAT interface remained available.

A first KB8AY attempt requested 7.100 MHz while all 720 sampled QK4 frequency
frames remained at 14.1085 MHz. It was stopped with TQ0 verified. That trial
cannot establish gateway reachability. Native tuning showed brief optimistic
matches followed by a return to the old band. The operator then tuned 7.100 MHz
from Vail's UI; VFO B also moved onto 40m. Same-band CAT changes subsequently
remained stable. The operator identified the sub-receiver/band constraint as
a likely cause. Antenna assignments and the exact rejection mechanism have
not been independently established.

At 21:24–21:26 Eastern, a second KB8AY attempt held 7.100 MHz USB with
split/RIT/XIT off and native PC050L. Pat waited for BUSY. Cancellation was
requested at 21:25:34, but its pending dial survived until the channel cleared
at 21:25:54, then emitted CONNECT and DISCONNECT together. One connect request
and closing CW ID transmitted. PTT OFF preceded DISCONNECTED, and QSX followed.
No HF connection was observed. This exposed that API cancellation/status alone
was insufficient to enforce an RF deadline; the old bounded-test claim was
not supported by this run.

The revised test uses an independent timer to stop the entire supervised
stack, removing CAT transmit capability even if HTTP is blocked or a dial
remains queued. It also stops the stack after any unsuccessful attempt,
rejects a live worker after cancellation, verifies stable QK4 state before
CONNECT, and rechecks per-band power. A receive-only deadline drill has been
completed; live verification of this correction remains pending.

Private evidence: `.local/logs/vail-*.json*`, `.local/logs/pat.log`,
`.local/logs/kestrel.log`, and `.local/recordings/rx-20261029T012436Z.wav`.
The recording has 114 seconds of receive audio; the capture reported no xruns
or TX underruns. No CRC-valid received VARA frame has been established.

At 21:36–21:37 Eastern, K0SI on 7.1003 MHz/BW2300 passed stable tuning,
remained BUSY, and was stopped by the independent deadline. All 654 sampled
TQ frames were receive; dial frequency returned to 7.100 MHz.

At 21:40–21:41 Eastern, K0BBQ on 7.0895 MHz/BW500 passed stable tuning and
began connect requests when its channel cleared. No HF CONNECTED was observed.
The internal meter peaked at 5.2 W, ALC 0, CMP 3 dB and SWR 1.0:1 with PC050L.
The deadline request fired at 01:41:37.500 UTC, but the last TQ1 sample was
3.44 seconds later. The guard's async server context waited for active clients
before reaching the code that cancelled those clients; the supervisor then
killed the stuck guard after its three-second grace period. Session cancellation
has been moved inside the server context, before waiting for closure. An actual
child-process regression test proves SIGTERM sends RX and exits with the CAT
client still connected. Live confirmation of the corrected shutdown timing
remains pending. Receive recording: `rx-20261029T014034Z.wav` (66 seconds).

## Operator handoff before the DATA-A change

Further RF/gateway attempts were stopped at the operator's request. The
receive-only station is not running. All station listeners are closed; QK4
Vail remains the operator's running app.

The corrected CAT shutdown passed the simulated-radio process regression and
a receive-only live-stack stop, completing in 1.03 seconds including receive
verification. A subsequent VE1YZ attempt stayed BUSY and generated no TX
(all 669 sampled TQ frames were receive); the independent timer requested stop
at 01:49:36.603 UTC and the stack completed cleanup at 01:49:38.203 UTC.
Active-RF unkey timing after the final guard fix remains unverified.

The operator supplied local Winlink credentials. Field names were normalized
with a private backup outside the repo; the password value was preserved.
The launcher reads `.env` without interpolation, validates the email callsign,
and passes the password to Pat through its process environment. Actual local
loading was verified without printing the password; the generated Pat JSON
password remains blank. Authentication and mail transfer were not attempted.

Vail-session logs, receive recordings and loose diagnostics were archived
intact under `~/Library/Application Support/n1rwj-winlink-setup/archives/20261029T020717962501Z/.local`.
References to Vail `.local` evidence above now refer to that archive. Mailbox,
forms, RMS cache, generated configuration, `.env` and dependencies are retained.
