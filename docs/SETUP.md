# Hardware setup, diagnostics and rollback

## QK4 and Loopback

The saved local radio profile on this Mac is profile **1**. Configure sets
**EM0 uncompressed 24-bit**, **SL0** (20 ms), CAT on loopback port 9299,
mono mixing off and sub volume zero. Authentication is preserved. For another
saved profile, use `mise run configure-qk4 -- --profile 2` while QK4 is closed.
On a new Mac, create the radio connection in QK4's Server Manager first.
This Mac's local profile uses `192.168.7.25:9204`, TLS, and identity `N1RWJ`;
enter its existing password through QK4. Preview changes at any time with
`mise run configure-qk4 -- --dry-run` (no preferences changed).

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
peak drive to 0.05. The configure task also disables RX boost and QK4's
amplifier integration. These produced RF near the 5 W setting in the first trial;
waveform quality still needs qualification. QK4's microphone capture opened
successfully on PTT. Allow macOS microphone access for virtual-device capture
if prompted. System audio defaults were not changed.

For modem operation use USB, an appropriate filter, and disable speech
compression, TX EQ, VOX, noise reduction/blanking and automatic notch.
Radio DSP settings have not been automated or qualified. QK4's amplifier
integration was disabled during the first trial.

## Control path

```text
Pat -> VARA :8300/8301 -> Kestrel -> Loopback
Pat -> rigctld :4532 -> CAT guard :9300 -> QK4 :9299 -> K4
```

All listeners bind to loopback. Pat owns PTT (`ptt_ctrl=true`); Hamlib model
2047 sends `TX;`/`RX;` to QK4's audio gate. Audio alone does not open the gate.
Native K4 power readback is used because Hamlib's K3-style power setters are
incompatible with this route. RF startup requires a positive QRP setting
at or below 5 W. The standalone test temporarily sets native `PC050L` and
restores the original setting.

Closing CW identification finishes before DISCONNECTED is reported, allowing
Pat to restore frequency afterward. This ordering correction is unit tested;
its live verification is pending. Passive VarAC broadcast decoding is disabled
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
mise run audio -- devices
mise run audio -- record --seconds 10 --output .local/rx.wav
mise run receive-check                # Temporary USB QSY, record, restore; no keying
mise run audio -- cable --direction tx # QK4 gate forced closed before local tone
```

For RX cable injection, stop the station and disconnect/quit QK4 first, then
run `mise run audio -- cable --direction rx`. For silent receive, check QK4's
connection/output, cable Pass-Thru, left-channel routing and volume. QK4's
`NO RX AUDIO` log means Qt rejected the device format.

Use `doctor` for health checks: probing port 8300 with netcat attaches a modem
client. `mise run tx-test` prints a plan without network/audio access. Its
approved execution sends `N1RWJ` in CW at 20 WPM (3.78 seconds) with a
five-second key deadline and restores frequency, mode, bandwidth and power.
Its conservative channel classifier may refuse to transmit on a noisy channel.

```sh
mise run stop
mise run tx-test -- --execute --approved-transmit --antenna-confirmed
```

Use this only within the operator's RF authorization. Normal live unkeying
has been observed; deliberate interrupted-client RF tests remain unverified.
See [STATUS](STATUS.md) for the exact evidence boundaries.

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
