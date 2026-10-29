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

Station startup selects DATA-A normal and an RX filter of at least 2.8 kHz. Hamlib names
this `PKTUSB`; native K4 readback must be `MD6; DT0;` with `BW0280;` or wider.
DATA-A internally disables speech compression. Set the K4 DATA TX bandwidth
to at least 3 kHz and keep TX EQ, VOX, noise reduction/blanking and automatic
notch off. These other radio DSP settings have not been automated or qualified.
QK4's amplifier integration was disabled during the first trial.

For initial Winlink tests, select the band in QK4 and keep VFO B on the same
band as A. The [K4 operating manual](https://ftp.elecraft.com/K4/Manuals%20Downloads/K4%20Built-In%20Operating%20Manual%20rev%20D14/K4BuiltInOperatingManualrevD14.html)
documents a shared-antenna constraint: the transmit VFO's low-pass filter must
allow the other receiver's band. A lower transmit band can conflict with a
higher receive band. The `VFO B Different Band` menu setting also matters.
Sub audio volume zero does not turn the sub receiver off. QK4's current CAT
`SB;` reply is a fixed placeholder, so do not use it to prove SUB is disabled.

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
mise run audio -- devices
mise run audio -- record --seconds 10 --output .local/rx.wav
mise run receive-check                # DATA-A/Pat QSY at current dial, record, restore
mise run receive-check -- --dial-khz 7100  # Optional different test dial; no keying
mise run audio -- cable --direction tx # QK4 gate forced closed before local tone
```

For RX cable injection, stop the station and disconnect/quit QK4 first, then
run `mise run audio -- cable --direction rx`. For silent receive, check QK4's
connection/output, cable Pass-Thru, left-channel routing and volume. QK4's
`NO RX AUDIO` log means Qt rejected the device format.

Use `doctor` for health checks: probing port 8300 with netcat attaches a modem
client. `mise run tx-test` prints a plan without network/audio access. Its
approved execution sends `N1RWJ` in CW at 20 WPM (3.78 seconds) with a
five-second key deadline and restores frequency, native mode/submode and RX
bandwidth. It uses the radio's selected power without changing it.
Its conservative channel classifier may refuse to transmit on a noisy channel.

```sh
mise run stop
mise run tx-test -- --execute --approved-transmit --antenna-confirmed
```

Use this only within the operator's RF authorization. Normal live unkeying
has been observed; deliberate interrupted-client RF tests remain unverified.
See [STATUS](STATUS.md) for the exact evidence boundaries.

## DATA-A and mode rollback

The K4's [operating manual](https://ftp.elecraft.com/K4/Manuals%20Downloads/K4%20Built-In%20Operating%20Manual%20rev%20C22/K4BuiltInOperatingManualrevC22.html)
describes DATA-A as the generic audio-data mode: normal orientation is USB,
the dial is the suppressed carrier frequency, and compression is internally
disabled. The [programmer's reference](https://ftp.elecraft.com/K4/Manuals%20Downloads/K4%20Programmer%27s%20Reference%2C%20rev.%20D5.pdf)
defines `MD6` as DATA, `MD9` as reverse DATA, and `DT0` as DATA-A.

Startup selects Hamlib `PKTUSB`, waits for stable native mode/submode, then
widens a narrower RX filter to 2.8 kHz last. Wider operator-selected filters are retained. Hamlib 4.7.2 sends BW before DT; the live K4
recalled a 2.5 kHz filter after DT0 until the helper reapplied BW0280. A one-second
stable readback is required. `doctor` checks mode/submode/filter without
changing them. QK4's CAT server does not return `DW` (DATA TX bandwidth), so
check that setting on the radio; RX `BW0280` does not prove TX bandwidth.

QK4's microphone stream carries the Loopback TX cable into its existing
network-audio encoder. Its source selection and PTT gate are independent of
SSB versus DATA-A. The DATA-A receive test and gate-closed TX cable test do
not establish RF modulation through the radio in DATA-A; see STATUS for what
was actually measured. Raw EM0/SL0 and the named Loopback devices are unchanged.

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
