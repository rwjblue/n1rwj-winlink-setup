# N1RWJ remote HF Winlink

Pat + Kestrel + QK4 on Apple Silicon macOS. **Receive-only operation is
verified. RF transmission and RMS message transfer await approval and testing.**
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
needs dummy-load calibration. Allow macOS microphone access for virtual-device
capture; QK4's first microphone open occurs on PTT and remains unverified.
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
cleanup. Physical RF/unkey still needs verification. See [source review and
audio findings](docs/UPSTREAM.md).

## Diagnostics and troubleshooting

```sh
mise run check
mise run bench-ptt                    # Real Pat/Hamlib, simulated K4; no RF/audio
mise run codec-bench                  # Offline raw/Opus comparison
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

## RF approval gate

`mise run tx-test` prints a dry run without opening audio or CAT devices.
The proposed first test is **one second of 1500 Hz tone at 14.1015 MHz USB,
5 W limit, peak audio 0.05**, into a 50-ohm dummy load with the amplifier
bypassed. It requires native K4 `PC050L` readback and has a five-second key
deadline. The test temporarily replaces Pat as sole PTT owner and restores
frequency, mode, filter and native RF power after confirmed unkey.

**Execute only after explicit human RF approval and physical confirmations:**

```sh
mise run stop
mise run tx-test -- --execute --approved-transmit --dummy-load-confirmed --amplifier-bypassed
```

Observe RF power/ALC, verify QK4 mic capture, then verify TQ0 and RF returning
to zero. This real-radio transmit path has only been dry-run tested. Qualify
levels, leading/trailing audio and failure unkey on the dummy load first.

After success, obtain separate antenna/RMS approval. Start the foreground RF
stack with `mise run transmit -- --approved-transmit`, choose a current RMS
URL, receive first, then transfer a short test message. Verify received content
and destination delivery before claiming success.

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
