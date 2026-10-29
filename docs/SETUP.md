# Hardware setup, diagnostics and rollback

## QK4 and Loopback

The saved local radio profile on this Mac is profile **1**. Configure sets
**EM0 uncompressed 24-bit**, **SL0** (20 ms), CAT on loopback port 9299,
mono mixing off and sub volume zero. Authentication is preserved. For another
saved profile, use `mise run configure-qk4 --profile 2` while QK4 is closed.
On a new Mac, create the radio connection in QK4's Server Manager first.
This Mac's local profile uses `192.168.7.25:9204`, TLS, and identity `N1RWJ`;
enter its existing password through QK4. Preview changes at any time with
`mise run configure-qk4 --dry-run` (no preferences changed).

| Direction | QK4 device | Kestrel device |
|---|---|---|
| RX | Output: `K4 RX to WSJT-X` | Input: same cable, left/main channel |
| TX | Input: `WSJT-X TX to K4` | Output: same cable, duplicated mono |

Each Loopback cable needs one enabled Pass-Thru source at unity, channel
1->1 and 2->2, without other sources or monitor feeds. The configure task
finds devices by name and writes this Mac's actual device IDs; IDs are not
hard-coded in Git.

Both existing cables accept QK4's exact **12 kHz stereo Float32** output.
Qt and the running app were verified. CoreAudio converts RX to Kestrel's
48 kHz; QK4 captures TX at 48 kHz and decimates to 12 kHz mono. BlackHole
and a new TCI backend are unnecessary. See [UPSTREAM](UPSTREAM.md) for raw
versus Opus fidelity and latency measurements.

Tracked station settings set QK4 main volume to 47, mic gain to 25 and modem
peak drive to **0.35**, calibrated with real Kestrel MFSK in DATA-A TX TEST
on 40m and 20m. The previous 0.05 drive produced no ALC deflection. The
configure task also disables RX boost and QK4's amplifier integration.
RF waveform quality still needs qualification. QK4's microphone capture opened
successfully on PTT. Allow macOS microphone access for virtual-device capture
if prompted. System audio defaults were not changed.

Station startup selects DATA-A normal and an RX filter of at least 2.8 kHz.
Hamlib names this `PKTUSB`; native K4 readback must be `MD6; DT0;` with
`BW0280;` or wider.
DATA-A internally disables speech compression. Set the K4 DATA TX bandwidth
to at least 3 kHz and keep TX EQ, VOX, noise reduction/blanking and automatic
notch off. These other radio DSP settings have not been automated or qualified.
QK4's amplifier integration was disabled during the first trial.

The station's Pat build runs a receive-only preparation hook after each
successful QSY. It waits for the target frequency, selects DATA-A normal
after band recall, reapplies DT0 after DATA profile recall, and ensures an
RX filter of at least 2.8 kHz while preserving wider filters. Stable native
frequency/mode/submode/filter and receive readback must pass before Pat
reports QSY success. Connect without a frequency runs the same preparation
at the current dial. `doctor` checks the result without changing it.

The link test requires stable QK4 frequency, DATA-A normal, an RX filter of at least 2.8 kHz
and split/RIT/XIT off before CONNECT, and rejects transient optimistic UI state.
It reapplies the mode after tuning in case the band recalls another profile.
Hamlib caching is
disabled in the supervised rigctld so status reads do not reuse a SET value.
QK4 still serves its own RadioState cache; this is not an independent RF
frequency measurement.

## Control path

```text
Pat -> VARA :8300/8301 -> Kestrel -> Loopback
Pat -> rigctld :4532 -> CAT guard :9300 -> QK4 :9299 -> K4
```

All listeners bind to loopback. Pat owns PTT (`ptt_ctrl=true`); Hamlib model
2047 sends `TX;`/`RX;` to QK4's audio gate. Audio alone does not open the gate.
Native K4 power readback is used because Hamlib's K3-style power setters are
incompatible with this route. Set RF power in QK4/K4; startup, link tests and
the standalone transmit test use the radio's current setting. Power readback
is informational, with no software ceiling or automatic power writes.

Closing CW identification finishes before DISCONNECTED is reported, allowing
Pat to restore frequency afterward. This ordering was observed live with Vail.
Deadline/error shutdown closes CAT immediately and may interrupt closing ID.
Passive VarAC broadcast decoding is disabled
in this launcher because unrelated turbo decoding could stall ARQ/heartbeats.

The upstream audio journal's `dry_run` label describes its lack of an own rig
controller. In this external-PTT arrangement, use QK4 telemetry as RF evidence.
Do not infer RF absence from that label.

## Advanced diagnostics

These are maintained, repeatable diagnostics; normal operation needs only
the commands in the README. They are hidden from the default task list but
remain directly runnable (or visible with `mise tasks ls --local --hidden`).

```sh
mise run check
mise run bench-ptt                    # Actual Pat/Hamlib, simulated radio; no RF/audio
mise run codec-bench                  # Offline raw/Opus comparison
mise run qt-audio-probe               # Exact Qt format support
mise run audio devices
mise run audio record --seconds 10 --output .local/rx.wav
mise run receive-check                # DATA-A/Pat QSY at current dial, record, restore
mise run receive-check --dial-khz 7100  # Optional different test dial; no keying
mise run audio cable --direction tx # QK4 gate forced closed before local tone
```

For RX cable injection, stop the station and disconnect/quit QK4 first, then
run `mise run audio cable --direction rx`. For silent receive, check QK4's
connection/output, cable Pass-Thru, left-channel routing and volume. QK4's
`NO RX AUDIO` log means Qt rejected the device format.

`receive-check` requires a receive-only station. Run `mise run stop`, then
`mise run start --receive-only` before this diagnostic. Normal `mise run start`
enables transmission; stop and start again without the option to resume HF mail.

Use `doctor` for health checks: probing port 8300 with netcat attaches a modem
client. `mise run tx-test` prints a plan without network/audio access. Its
approved execution sends `N1RWJ` in CW at 20 WPM (3.78 seconds) with a
five-second key deadline and restores frequency, native mode/submode and RX
bandwidth. It uses the radio's selected power without changing it.
Its conservative channel classifier may refuse to transmit on a noisy channel.

```sh
mise run stop
mise run tx-test --execute --approved-transmit --antenna-confirmed
```

Use this only within the operator's RF authorization. Normal live unkeying
has been observed; deliberate interrupted-client RF tests remain unverified.
See [STATUS](STATUS.md) for the exact evidence boundaries.

For an **off-air** check through QK4 and the K4 network-audio input, stop the
station and enable the K4's TX TEST mode. Confirm the active TEST indicator
beside the VFO, rather than the permanent TEST caption under XMIT. Then run:

```sh
mise run tx-test --execute --radio-test-mode --dial-khz 7055
```

This variant positively checks the radio-reported VFO indicator through
macOS System Events before preparation and immediately before PTT. It currently
supports the installed QK4 Vail bundle `com.rwjblue.qk4.vail`; macOS automation
and accessibility permission may be required. Missing UI confirmation stops
the check. It requires logical TX and zero forward-meter samples to report
success. K4 TX TEST inhibits radio RF but still keys downstream gear, as
described in the programmer's reference. Return to TX NORM only after the
check has unkeyed. The script does not toggle TX TEST or alter RF power.

## Audio drive calibration

`amplitude` controls Kestrel's normalized audio peak, not RF watts. QK4
applies its cubic mic gain afterward: the calibrated 0.35/25 pair produces
peak audio of about 0.00547 (-45.2 dBFS) before network encoding. Compared
with 0.05/25, the signal is 7 times higher in amplitude (+16.9 dB). Radio
power remains operator-controlled; calibration used native `PC050H` unchanged.

The [K4 operating manual](https://ftp.elecraft.com/K4/Manuals%20Downloads/K4%20Built-In%20Operating%20Manual%20rev%20C22/K4BuiltInOperatingManualrevC22.html)
advises keeping audio-data ALC just below the "5" mark. TX TEST supports
audio-only ALC adjustment while RF is inhibited. Stop the station, enable
TX TEST, and confirm the VFO's active TEST indicator before executing:

```sh
mise run calibrate-audio                                  # Plan, no I/O
mise run calibrate-audio --execute --dial-khz 7101       # Sweep 40m
mise run calibrate-audio --execute --dial-khz 14101.5 --peaks 0.35
```

The default waveform is the upstream Kestrel BW2300 connect request to
N0CALL, rendered offline and normalized exactly as `AudioVaraIO.tx` does.
No RMS connection is attempted. `--signal cw` selects the identified CW
comparison signal. Every case rechecks TX TEST immediately before PTT,
uses the standalone five-second key guard, verifies logical TX and zero
forward-meter readings, and saves private per-level logs and telemetry under
`.local/logs/audio-calibration-*/`. The sweep stops on ALC 4 or above; it
refuses to qualify a run with no measured response in the 2–4 range.

The task does not rewrite configuration or toggle TX TEST. Choose the pair
from its measurements, edit `config/station.toml`, and restart the station.
If changing `qk4_mic_gain`, quit QK4, run `mise run configure-qk4` and relaunch
Vail before measuring. Startup/doctor verify the saved mic gain matches the
configuration. Restore TX NORM after confirmed receive. The standalone test
now honors configured drive; its former hard-coded 5 percent clamp is removed.

For a single diagnostic level without changing defaults:

```sh
mise run tx-test --execute --radio-test-mode --dial-khz 7101 \
  --signal vara-connect --audio-peak 0.35
```

Overrides require TX TEST. Waveform-specific ALC matters: 0.40 reached ALC 4
with CW but 5 with the modem waveform, so the chosen modem default is 0.35.
This qualifies drive at the tested settings, not high-speed OFDM distortion,
RF output power, gateway decoding or mail transfer. Recheck ALC when changing
the radio power, signal bandwidth, QK4 gain or audio encoding.

## DATA-A and mode rollback

The K4's [operating manual](https://ftp.elecraft.com/K4/Manuals%20Downloads/K4%20Built-In%20Operating%20Manual%20rev%20C22/K4BuiltInOperatingManualrevC22.html)
describes DATA-A as the generic audio-data mode: normal orientation is USB,
the dial is the suppressed carrier frequency, and compression is internally
disabled. The [programmer's reference](https://ftp.elecraft.com/K4/Manuals%20Downloads/K4%20Programmer%27s%20Reference%2C%20rev.%20D5.pdf)
defines `MD6` as DATA, `MD9` as reverse DATA, and `DT0` as DATA-A.

Startup always selects Hamlib `PKTUSB`, waits for DATA mode to settle, then
reapplies DT0 and waits before setting the RX filter last. A band change can
briefly report the old DATA-A cache while the K4 recalls USB or FSK-D. Hamlib
4.7.2 sends BW before DT; the live K4 recalled a 2.5 kHz filter after DT0 until
the helper reapplied BW0280. Wider operator-selected filters are retained. A one-second
stable readback is required. `doctor` checks mode/submode/filter without
changing them. QK4's CAT server does not return `DW` (DATA TX bandwidth), so
check that setting on the radio; RX `BW0280` does not prove TX bandwidth.

QK4's microphone stream carries the Loopback TX cable into its existing
network-audio encoder. Its source selection and PTT gate are independent of
SSB versus DATA-A. Live receive, the gate-closed TX cable, and outgoing
network audio with the K4 in TX TEST were verified. These do not establish
DATA-A RF modulation or RMS decoding; see STATUS for the measurements.
Raw EM0/SL0 and the named Loopback devices are unchanged.

Startup and `doctor` compare QK4's saved device IDs with Qt's exact compatible
Loopback devices and verify the calibrated mic gain. If settings drift,
quit QK4 and run `mise run configure-qk4`; it backs up preferences first.
Reopen Vail and connect the local profile. Stored settings alone cannot prove
live audio, which is why the receive and outgoing-path checks are separate.

Each startup saves the previous native settings in
`.local/logs/radio-before-data-a-*.json`; normal stop leaves DATA-A selected.
To undo the live selection, stop the station and restore the recorded mode,
data submode (if applicable), frequency and RX filter in QK4. The receive
check and standalone transmit diagnostic restore their own pre-test settings.
Reverting the DATA-A commit restores the prior startup behavior.

## Artifact cleanup

Run `mise run stop`, then `mise run clean`. Cleanup holds the station lock
and refuses active control ports. It moves `.local` diagnostics into a private
timestamped directory under
`~/Library/Application Support/n1rwj-winlink-setup/archives`; each archive has
an index of original paths. Earlier channel surveys, HTML captures,
receive recordings, telemetry and logs are archived there.

The entire `.local/pat` directory is retained, including messages, forms,
configuration and RMS caches. `.venv` and `.cache` are also retained: Kestrel
uses the cached hfmodem source as an editable installation. The Qt probe and
Ruff cache now build under `.cache`, rather than cluttering runtime data or
the repository root. Nothing from these generated directories belongs in Git.

## Rollback

Stop the station and quit QK4. Backups are outside Git under
`~/Library/Application Support/n1rwj-winlink-setup/backups`, with private
permissions because preferences may contain credentials. Restore this Mac's
pre-setup settings:

```sh
.venv/bin/python tools/qk4_settings.py --restore \
  "$HOME/Library/Application Support/n1rwj-winlink-setup/backups/qk4-initial.plist"
```

Relaunch QK4. On another Mac, use that machine's timestamped preference backup.
Preserve `.local/pat` before removing runtime data: it contains your mailbox
and downloaded forms. `.cache` and `.venv` can be recreated by setup.
Shared mise tools, native dependencies, QK4 and Loopback stay installed;
no driver, system audio default or existing user checkout was replaced.

## Handshake capture and timing

`mise run capture-handshake` prints a plan without opening devices. Its
execution mode is strictly passive: it opens the **input** side of both
Loopback cables at 48 kHz stereo and polls only native `TQ;TM;` status queries.
It does not play audio, tune, attach to Kestrel, or send PTT commands. It can
run beside the existing station without restarting it:

```sh
mise run capture-handshake --seconds 30 --execute
```

The private `.local/recordings/handshake-*/` directory contains `rx.wav` and
`tx.wav` as PCM32 stereo, per-input `*-timing.jsonl`, `radio.jsonl`, the station
log additions during capture, and `manifest.json`. The TX recording is the
Loopback signal **before QK4's mic gain, resampler, network codec and radio**;
it is not a recording of the radiated signal. An idle capture should have
silent TX. File/queue failures, stream status flags and incomplete telemetry
make the result incomplete and return an error; partial evidence is retained.
Silent RX is reported separately as a routing warning, even if every captured
buffer and telemetry reply arrived intact. Run `mise run doctor` before
interpreting a silent recording as a quiet channel.

Each audio block records its capture-frame index, file-frame index, PortAudio
ADC/current timestamps and a callback-anchored monotonic estimate. Use these
records to align the two WAVs; their first samples do not share an assumed
origin. Missing buffers remain explicit. QK4 `TQ` and meter reports are polled
cached state, **not measured physical PTT or RF edges**. The host timing and
radio polling resolution cannot establish a precise RF turnaround by themselves.

For a future Kestrel run, `--diagnostics` adds exact normalized Float32 source
WAVs and an asynchronous event journal under `.local/recordings/kestrel-*/`,
plus upstream playback/capture-cursor timing in `kestrel.log`. CAT guard lines
include receipt timestamps on the same machine's monotonic clock. Match the
source journal's `burst` number to `tx_event.tx_id`, and use the detailed
`timing` lines to distinguish playback start, playback drain, idle tail and
PTT notifications. A saved source represents generated playback intent;
check the playback outcome before claiming it was played. Queue/file errors
are reported in the source capture's `summary.json` at station shutdown.

A receive-only startup with this instrumentation is:

```sh
mise run start --receive-only --diagnostics
```

This still blocks CONNECT, PTT and transmit audio, so it cannot produce a TX
waveform. The option does not change the station's transmit mode. Enable it
on a future operator-approved transmit-enabled run when an actual handshake
capture is needed. Never restart an active station merely to attach the
passive recorder. RF-inhibited tests through the radio still require the
separate positive TX TEST checks described above; these capture tools do not
select TX TEST or certify RF inhibition.
