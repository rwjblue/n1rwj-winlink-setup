# N1RWJ remote HF Winlink

**Pat** is the Winlink mail client (`pat` is the command). Kestrel is its
VARA-compatible software modem; QK4 supplies remote K4 audio and radio control.
This repository configures and launches all three interfaces together.

Receive audio, CAT, RF output and normal unkeying are verified on this Mac.
**An RMS connection and HF message transfer have not succeeded yet.** Kestrel
is experimental. See [test results and remaining work](docs/STATUS.md).

## First setup

Install mise, Homebrew, Xcode Command Line Tools, QK4 and Loopback. The existing
Loopback cables are `K4 RX to WSJT-X` and `WSJT-X TX to K4`.

```sh
mise trust
mise run setup
mise run config             # Shows N1RWJ / FN41fr and the configuration paths
mise run pat -- env         # Confirms Pat sees this repo's identity and paths
# Quit QK4 first; its existing preferences are backed up before changes.
mise run configure-qk4
```

Setup installs pinned Go, Python, uv and Pat through mise, and Kestrel into
`.venv` through uv. There is no separate PACT dependency. All non-secret
station settings are checked in; a fresh checkout needs no copied `.local`
files. QK4 retains its saved radio connection and credentials in macOS.
Follow [hardware and macOS setup](docs/SETUP.md) when configuring another Mac.

## Daily use

1. Open QK4 and connect its saved local K4 profile. Close other modem/CAT clients.
2. Run `mise run start`. This starts Kestrel, guarded CAT/Hamlib and Pat together,
   **receive-only**, in the background.
3. Open [Pat's mailbox](http://127.0.0.1:8080/ui). Read mail or compose a message
   into the outbox. Sending requires the separate RF session described below.
4. Run `mise run doctor` to check the station, or `mise run status` for its mode.
5. Run `mise run stop` when finished. `mise run unkey` requests RX and verifies
   receive readback if an unexpected transmission occurs.

Use the project launcher for other Pat commands:

```sh
mise run pat -- rmslist --mode varahf --band 20m   # Internet query, no RF
mise run pat -- help compose
mise run pat -- read
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
| `config/pat.json` | Pat's VARA, listener, bandwidth and mail preferences | Yes; password blank |
| `config/station.local.toml` | Optional overrides for another machine | No; not required here |
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

Passwords are supplied only through `PAT_SECURE_LOGIN_PASSWORD` in the
launching process, ideally loaded from macOS Keychain. They are never rendered
into the generated config. Radio-link testing comes before credential setup
and authenticated mail testing on this station.

## An approved RF session

The operator authorized the existing resonant 40m/20m antenna at a 5 W setting
for this testing session on 2026-10-28. This superseded the initial dummy-load
requirement. Later operation requires the operator's authorization.

Connect QK4, select USB with an appropriate filter, disable speech compression
and TX EQ, and confirm the native QRP setting is at most 5 W. DSP settings and
PTT timing still need radio-path qualification. Then:

```sh
mise run stop
mise run transmit -- --approved-transmit  # Keep this foreground terminal open
# In another terminal, use a current RMS URL from the list:
mise run link-test -- 'varahf:///KB8AY?bw=2750&freq=7100' --execute --approved-transmit
```

The bounded link test stops on an HF connection or after 45 seconds, cancels
the attempt, and verifies receive readback. It tests the radio link before
mail authentication. Without `--execute`, it only prints a plan. RMS URLs
specify **dial kHz**; the audio centre is 1500 Hz higher. Ctrl-C in the RF
terminal stops the complete stack. Receive audio is saved under
`.local/recordings` during RF sessions.

Pat owns PTT through Hamlib and the CAT guard. Kestrel has no CAT controller.
The default receive stack independently blocks keying and TX samples. Child
failure stops the stack; the guard unkeys on disconnect and limits keys to
30 seconds. Direct QK4 controls and unrelated clients remain independent.
See [source and audio findings](docs/UPSTREAM.md) for details.

## Troubleshooting and maintenance

Start with `mise run doctor`, `.local/logs/supervisor.log` and the child logs.
For a callsign/config problem, run `mise run pat -- env`: it must report
`N1RWJ`, `FN41fr` and paths inside this checkout. If bare `pat` still reports
home paths, refresh mise's shell environment or use `mise run pat -- …`.

`mise run check` tests local configuration and interlocks without RF. Advanced
audio, codec and simulated-PTT diagnostics are in [SETUP](docs/SETUP.md).
The same document explains preference backups and rollback.

`mise tasks ls --local` lists the everyday tasks. After stopping the station,
`mise run clean` moves logs, recordings and loose test artifacts into a private
timestamped archive under
`~/Library/Application Support/n1rwj-winlink-setup/archives`. It preserves
`.local/pat` (including mail), dependency caches and `.venv`, and refuses
cleanup while station controls are active. No archived evidence is deleted.
