# N1RWJ remote HF Winlink

**Pat** is the Winlink mail client (`pat` is the command). Kestrel is its
VARA-compatible software modem; Besra provides optional ARDOP. QK4 supplies
remote K4 audio and radio control. VARA remains the default.
This repository configures and launches all three interfaces together.

Receive audio, CAT, RF output and normal unkeying are verified on this Mac.
**An RMS connection and HF message transfer have not succeeded yet.** Kestrel
is experimental. See [test results and remaining work](docs/STATUS.md).
The DATA-A audio path is verified off-air; earlier on-air tests used USB.

## First setup

Install mise, Homebrew, Xcode Command Line Tools, QK4 and Loopback. The existing
Loopback cables are `K4 RX to WSJT-X` and `WSJT-X TX to K4`.

```sh
mise trust
mise run setup
mise run config             # Shows N1RWJ / FN41fr and the configuration paths
mise run pat env         # Confirms Pat sees this repo's identity and paths
# Quit QK4 first; its existing preferences are backed up before changes.
mise run configure-qk4 --dry-run  # Optional preview; safe while QK4 is open
mise run configure-qk4
```

Setup installs pinned Go, Python, uv and Pat through mise, builds the station's
Pat QSY overlay, and installs Kestrel into `.venv` through uv. There is no
separate PACT dependency. All non-secret
station settings are checked in; a fresh checkout needs no copied `.local`
files. QK4 retains its saved radio connection and credentials in macOS.
Follow [hardware and macOS setup](docs/SETUP.md) when configuring another Mac.

## Daily use

1. Open QK4 Vail and connect its saved local K4 profile. Close other modem/CAT clients.
2. Run `mise run start`. This checks QK4's saved Loopback device selections,
   then starts Kestrel, guarded CAT/Hamlib and Pat together,
   **transmit-enabled**, in the background, and selects normal DATA-A with an
   RX filter of at least 2.8 kHz. Both mode and data submode are checked before Pat starts.
3. Open [Pat's mailbox](http://127.0.0.1:8080/ui). Read mail or compose a message
   into the outbox. Use Connect to exchange mail over HF as described below.
4. Run `mise run doctor` to check the station, or `mise run status` for its mode.
5. Run `mise run stop` when finished. `mise run unkey` requests RX and verifies
   receive readback if an unexpected transmission occurs.

Normal operation needs only `start` and `stop`; there is no separate transmit
command or approval flag. While started, the station can transmit to connect
or answer incoming calls. Set the desired RF power in QK4/K4 before starting.

For ARDOP, stop the station in its owning checkout, then select the modem:

```sh
mise run start --modem ardop --receive-only  # Initial hardware checks; no transmit
mise run doctor
mise run stop
mise run start --modem ardop                 # Operator use; enables transmission
```

Choose **ARDOP** in Pat's Connect form and use a current ARDOP RMS listing
(`mise run pat rmslist --mode ardop --band 20m`). Supported bandwidths are
200/500/1000/2000 **MAX**; FORCED is rejected. Stop/start to switch modems;
`mise run start` selects VARA again. Only the selected modem opens audio and
host ports. Status and doctor report the selection. ARDOP hardware audio,
RF and gateway transfer remain unverified; see [ARDOP operation and validation](docs/ARDOP.md).

Use the project launcher for other Pat commands:

```sh
mise run pat rmslist --mode varahf --band 20m   # Internet query, no RF
mise run pat help compose
mise run pat read
```

With mise shell activation, `pat` inside this repo resolves to `bin/pat` and
uses the same settings. `mise exec -- pat env` and `./bin/pat env` also work.
Use `mise run start` to start the complete station; `pat http` starts only Pat.
No `pat init` or callsign prompt is needed. Outside this repo, the upstream
Pat command keeps its usual home-directory behavior.

## Where configuration lives

| Path | Purpose | In Git? |
|---|---|---|
| `config/station.toml` | Callsign, grid, audio devices, CAT/HTTP ports, modem drive and timing | Yes |
| `config/pat.json` | Pat's VARA/ARDOP, bandwidth and mail preferences | Yes; password blank |
| `config/station.local.toml` | Optional overrides for another machine | No; not required here |
| `.env` | Local Winlink email and password; see `.env.example` for names | No |
| `.local/pat/config.json` | Generated effective Pat configuration | No; rebuilt automatically |
| `.local/pat/mailbox`, `forms` | Your messages and downloaded forms | No; preserve these |
| `.local/pat` | Pat's other private state and downloaded RMS caches | No |
| `.local/logs`, `recordings` | Runtime diagnostics and receive recordings | No |
| `.cache`, `.venv` | Downloaded source, build outputs and Python dependencies | No; reproducible |
| `mise.lock`, `requirements.lock`, `upstream.lock.json` | Pinned tools, dependencies and source revisions | Yes |

Edit the checked-in settings, then stop/start the station. The launcher
regenerates `.local/pat/config.json` whenever source settings differ; old
runtime edits are backed up outside the repo. Do not edit the generated copy
or use Pat's configuration editor: those edits are replaced at the next
launch. `mise run config` rebuilds and shows the paths without opening radio
or audio devices.

The launcher supplies all Pat paths and isolates its XDG state, including
RMS caches and form counters. CLI commands use `pat-cli.log` so they do not
truncate the running server's `pat.log`. Other inherited `PAT_*` settings
cannot change the configured identity or radio route; `PAT_DEBUG` is retained.

### Winlink login

The project Pat launcher reads the root `.env` automatically. No `source .env`
or manual export is needed. On a fresh checkout, create it using the field names
in `.env.example`:

```dotenv
WINLINK_EMAIL=N1RWJ@winlink.org
WINLINK_PASSWORD='your-password-here'
```

`WINLINK_EMAIL` supplies Pat's login callsign and must match the station
callsign. `WINLINK_PASSWORD` is passed as `PAT_SECURE_LOGIN_PASSWORD` only to
Pat's child process. It is not written into the generated JSON or command-line
arguments. Quotes and literal dollar signs are supported; shell commands and
`${...}` expansion are not evaluated. Keep `.env` private (`chmod 600 .env`).

Explicit process `WINLINK_*` values override the file. An explicitly supplied
`PAT_SECURE_LOGIN_PASSWORD` takes priority over both. Other `.env` fields do
not change routing or tools. Restart the station after editing credentials.
`mise run config` reports whether a password is available without printing it;
this checks loading, not whether Winlink accepts the password.

## Audio drive

Both modems read their Loopback devices and peak drive from `config/station.toml`.
The calibrated pair is **`amplitude = 0.35` and `qk4_mic_gain = 25`**.
QK4's mic slider is cubic, so these settings must be considered together.
The real Kestrel BW2300 connect waveform reached ALC 4 on both 40m and 20m
in TX TEST, below the K4's "5" mark, with compression and forward power zero.
This calibrates audio drive; it does not verify on-air RMS connectivity.

`mise run doctor` reports the pair and checks QK4's saved mic gain. Kestrel's
startup log shows the actual devices and peak drive. After changing QK4 gain,
recalibrate before using that new pair. `mise run calibrate-audio` prints a
plan; [SETUP](docs/SETUP.md#audio-drive-calibration) explains the TX TEST sweep.
The radio's RF power setting is independent and is never changed by these tools.

## Exchanging mail over HF

The operator authorized the existing resonant 40m/20m antenna and use of the
radio's selected power setting for this setup. Earlier recorded RF tests used
5 W; the software no longer imposes that limit.

Connect QK4 and select the desired RF power in QK4/K4. Startup selects
**DATA-A normal** (upper sideband), shown as `PKTUSB` by Hamlib, and an RX
filter of at least 2.8 kHz. DATA-A disables speech compression internally.
Check that the K4's
DATA transmit bandwidth passes the modem audio (at least 3 kHz), and keep
TX EQ and receive noise processing off. Power readback is informational.
DSP settings and PTT timing still need radio-path qualification.

DATA-A uses upper sideband on 40m as well as 20m; the 40m voice LSB convention
does not apply to these VARA dial frequencies. Do not select DATA-A reverse,
AFSK, FSK or PSK submodes. Selecting a gateway channel from Pat's RMS list
tunes the radio, then reapplies and verifies DATA-A normal and an RX filter
of at least 2.8 kHz, including after a band change. Wider filters are preserved.
Wait for Pat's frequency field to turn green before connecting. A failed
readback reports QSY failure. Connect also checks mode and filter when no
frequency is supplied.

Startup saves the previous native mode/submode/filter/frequency under
`.local/logs/radio-before-data-a-*.json`. Stopping leaves DATA-A selected.
See [mode checks and rollback](docs/SETUP.md#data-a-and-mode-rollback).

```sh
mise run start
```

For mail, open [Pat](http://127.0.0.1:8080/ui), compose your message, then use
its Connect form with VARA HF, the RMS callsign, dial frequency in kHz and
bandwidth from the current RMS list. The `.env` credentials are already loaded.
The station runs in the background, so the terminal can be closed. Run
`mise run stop` when finished or to abort reliably: Pat's UI cancellation can
leave a dial queued behind BUSY.

For a bounded **radio-link-only** diagnostic while the station is running:

```sh
mise run link-test 'varahf:///KB8AY?bw=2750&freq=7100' --execute --approved-transmit
```

The link test selects DATA-A again after tuning and requires a second of
stable frequency, mode, submode and RX-filter readback before
CONNECT, with split/RIT/XIT off, and reports the radio's power after tuning.
It monitors frequency throughout. An independent 45-second timer closes the
whole RF stack; it does not rely on Pat cancelling a queued busy-channel dial.
Successful HF connections are disconnected before stack shutdown. Original
dial frequency is restored after receive readback. Run `mise run start` again
after the test to resume station operation.

`link-test` disconnects once an HF link appears; use the UI flow above for an
actual mail exchange. Without `--execute`, it only prints a plan. RMS URLs
specify **dial kHz**; the audio centre is 1500 Hz higher. The standalone RF
diagnostics retain their execution/approval flags. Receive audio is saved
under `.local/recordings` during transmit-enabled operation.

Pat owns PTT through Hamlib and the CAT guard. Neither modem has a CAT controller.
Child failure stops the stack; the guard unkeys on disconnect and limits
keys to 30 seconds. Direct QK4 controls and unrelated clients remain independent.
See [source and audio findings](docs/UPSTREAM.md) for details.

For receive-only diagnostics, stop the station and run
`mise run start --receive-only`. This independently blocks RF connections,
keying and transmit audio while keeping the mailbox available for reading and
composing. `mise run receive-check` requires this mode. Stop and start without
the option to return to normal operation.

## Troubleshooting and maintenance

Commands report expected configuration and diagnostic errors directly in the
console without a Python traceback. Background startup failures also include
recent output from the supervisor or failed dependency. Unexpected Python
errors keep their tracebacks. Supervisor and child logs remain under
`.local/logs` for the full history; use `mise run doctor` for station checks.
For `QK4 saved audio settings differ`, quit QK4, run
`mise run configure-qk4`, then reopen **QK4 Vail** and connect the local profile.
The configurator backs up preferences before replacing audio selections.
This fixes silent Loopback RX, an unintended microphone source or a gain
mismatch; restart QK4 so the saved settings become active.
`connect: connection refused` on `127.0.0.1:8300` means Kestrel is stopped;
restart the complete station with `mise run start`. If you started with
`--receive-only`, the modem rejects outgoing connections and incoming ARQ
replies without closing the mailbox or TCP ports. Pat currently labels that
rejected connection `connect timeout`; `.local/logs/kestrel.log` explains the
mode. Run `mise run stop`, then `mise run start` to enable HF connections.

For a callsign/config problem, run `mise run pat env`: it must report
`N1RWJ`, `FN41fr` and paths inside this checkout. If bare `pat` still reports
home paths, refresh mise's shell environment or use `mise run pat …`.
To refresh a cached gateway list, add `--force-download` to the `rmslist` command.

`mise run check` tests local configuration and interlocks without RF. Advanced
audio, codec and simulated-PTT diagnostics are in [SETUP](docs/SETUP.md).
The same document explains preference backups and rollback.

`mise tasks ls --local` lists the everyday tasks; `mise run <task> --help`
describes each task's arguments. After stopping the station,
`mise run clean` moves logs, recordings and loose test artifacts into a private
timestamped archive under
`~/Library/Application Support/n1rwj-winlink-setup/archives`. It preserves
`.local/pat` (including mail), dependency caches and `.venv`, and refuses
cleanup while station controls are active. No archived evidence is deleted.
