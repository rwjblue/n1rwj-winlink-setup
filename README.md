# N1RWJ remote HF Winlink

Pat + Kestrel + QK4 on Apple Silicon macOS. **Receive audio, CAT and RF
transmission through QK4 are verified. No RMS link or message transfer yet.**
Kestrel is experimental; upstream success does not establish this station's
end-to-end operation. See [tested scope and remaining gates](docs/STATUS.md).

## Setup

Prerequisites: mise, Homebrew, Xcode Command Line Tools, QK4 and the existing
Loopback cables. Close other modem, CAT and TCI clients.

```sh
mise trust
mise run setup
# Quit QK4 first; this backs up preferences before changing them.
mise run configure-qk4
```

Mise pins Go, Python, uv and Pat; uv installs Kestrel into `.venv`.
`upstream.lock.json` freezes source revisions. Homebrew supplies Hamlib/Qt,
reusing installed versions. QK4 and Loopback remain installed apps. No separate
PACT package is needed.

In QK4's Server Manager, connect the saved local K4 profile. Configure defaults
to profile **1**, **EM0 uncompressed 24-bit**, **SL0**; use `--profile 2` for
another profile. Existing authentication is preserved.

| Direction | QK4 device | Kestrel device |
|---|---|---|
| RX | Output: `K4 RX to WSJT-X` | Input: same cable, left/main channel |
| TX | Input: `WSJT-X TX to K4` | Output: same cable, duplicated mono |

Keep Loopback Pass-Thru at unity, without other sources or monitor feeds.
Both cables accept QK4's **12 kHz stereo Float32** output; Qt and the running
app were verified. CoreAudio converts RX to Kestrel's 48 kHz; QK4 converts
48 kHz TX back to 12 kHz. No BlackHole or TCI backend is needed.

Configure disables mono mixing and sets sub volume to zero. Main volume is
47 here; mic gain is 25 and modem peak drive 0.05. Keep RX boost off. TX gain
produced RF near the 5 W setting in the first trial; waveform quality still
needs qualification. QK4's microphone capture opened successfully on PTT.
Allow macOS microphone access for virtual-device capture if prompted.
System audio defaults were unchanged.

## Operate

```sh
mise run start       # Background; ALWAYS receive-only
mise run doctor      # Pat, radio state and device checks
mise run status
mise run stop        # Stop the supervised stack
mise run unkey       # Emergency RX request and TQ0 verification; never keys
```

Open [Pat](http://127.0.0.1:8080/ui). Configuration/mailbox live in `.local/pat`;
logs/recordings in `.local`. Generated data and `.cache` are ignored by Git.
Existing global Pat data is untouched. Put overrides in ignored
`config/station.local.toml`; match changed ports in `.local/pat/config.json`.
Startup rejects Pat settings that bypass the guarded route.

Set your grid before distance-ranked RMS queries. Leave the JSON password
blank; provide `PAT_SECURE_LOGIN_PASSWORD` from your OS keychain for an
approved session. This query does not transmit RF:

```sh
mise run pat -- rmslist --mode varahf --band 20m
```

RMS URLs use **dial kHz**; centre is 1500 Hz higher. Use the returned URL
directly. Select USB and a suitable filter. Disable speech compression, TX EQ,
VOX, noise reduction/blanking and automatic notch for modem tests. DSP settings
have not been automated or qualified here.

## PTT and shutdown

```text
Pat -> VARA :8300/8301 -> Kestrel -> Loopback
Pat -> rigctld :4532 -> CAT guard :9300 -> QK4 :9299 -> K4
```

All listeners bind to loopback. Pat owns PTT (`ptt_ctrl=true`): Kestrel reports
PTT events; Hamlib model 2047 sends `TX;`/`RX;` to QK4's audio gate. Kestrel
has no CAT controller. Audio alone cannot open QK4's gate.

Kestrel and the guard independently enforce receive-only. A child failure
stops the stack, closing CAT first. The guard unkeys on session/parent loss
and limits keys to 30 seconds; QK4 also unkeys on owning-client disconnect.
Direct QK4 controls and other clients remain independent. Use stop/Ctrl-C for
cleanup. RF startup requires native QRP power readback at or below 5 W.
Closing CW identification precedes the disconnect notification, so Pat's
frequency restoration follows unkey. See [source review and
audio findings](docs/UPSTREAM.md).

## Diagnostics and troubleshooting

```sh
mise run check
mise run bench-ptt                    # Real Pat/Hamlib, simulated K4; no RF/audio
mise run codec-bench                  # Offline raw/Opus comparison
mise run link-test -- 'varahf:///KB8AY?bw=2750&freq=7100' # Dry run
mise run qt-audio-probe
mise run audio -- record --seconds 10 --output .local/rx.wav
mise run receive-check                # Temporary USB QSY, record, restore
mise run audio -- cable --direction tx # Forces QK4 gate closed before local tone
```

For RX cable injection, stop the station and disconnect/quit QK4 first, then
run `mise run audio -- cable --direction rx`. Use `audio -- devices` to list
devices. [STATUS](docs/STATUS.md) records measurements and test boundaries.

For silent RX, check QK4 connection/output, Loopback Pass-Thru, left-channel
routing and volume. QK4's `NO RX AUDIO` log means Qt rejected the format.
For startup failures, inspect `.local/logs/supervisor.log` and child logs.
Use `doctor` for health checks: probing 8300 with netcat attaches a modem client.

## Approved RF operation

`mise run tx-test` prints a dry run without opening audio or CAT devices.
The standalone test sends `N1RWJ` in CW at 20 WPM (3.78 seconds), at a
1500 Hz audio offset, with a 5 W setting and five-second key deadline.
It restores frequency, mode, filter and native power after receive readback.
Its conservative channel check can refuse a noisy channel before key-up.

The operator authorized the current resonant 40m/20m antenna and transmission
at a 5 W setting on 2026-10-28, replacing the earlier dummy-load requirement
for this session. Future use still requires operator authorization.
For an identified standalone check:

```sh
mise run stop
mise run tx-test -- --execute --approved-transmit --antenna-confirmed
```

For a radio-link test, connect QK4, select USB/a suitable filter, and run:

```sh
mise run transmit -- --approved-transmit  # Foreground RF stack
# In another terminal, use a URL from the current RMS list:
mise run link-test -- 'varahf:///KB8AY?bw=2750&freq=7100' --execute --approved-transmit
```

`link-test` ends on HF connection or its 45-second deadline, explicitly
cancels Pat, and verifies receive readback. Monitoring/cancellation failure
requests full RF-stack shutdown. It tests the radio link before mail login.
RF sessions record RX under `.local/recordings`; monitor available disk space.
The upstream audio driver's `dry_run` journal label means it does not own
CAT; QK4 telemetry is the RF evidence when Pat owns PTT.

Passive VarAC broadcast decoding stays off in this Winlink launcher to keep
unrelated turbo decoding from stalling ARQ/heartbeats. Verify an RMS link,
then authenticated message transfer and destination receipt before claiming
complete Winlink operation.

## Rollback

Stop the station and quit QK4. Backups are outside Git under
`~/Library/Application Support/n1rwj-winlink-setup/backups`, with private
permissions because preferences may contain saved credentials. Restore this
Mac's pre-setup settings:

```sh
.venv/bin/python tools/qk4_settings.py --restore \
  "$HOME/Library/Application Support/n1rwj-winlink-setup/backups/qk4-initial.plist"
```

Relaunch QK4. On another Mac, use its configure task's timestamped backup.
Archive runtime data before removing `.local`, `.venv` or `.cache`.
Shared mise tools, native dependencies, QK4 and Loopback stay installed;
no driver, system audio default or existing user checkout was replaced.
