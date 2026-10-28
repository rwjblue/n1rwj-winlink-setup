# Source review — 2026-10-28

The full commits are recorded in `upstream.lock.json`. Downloaded source is
kept in ignored `.cache/upstream`; user checkouts were not changed.

| Project | Revision read | Relevant source |
|---|---|---|
| Pat | `2e6a8d14baf0` / v1.0.0 | [VARA initialization/PTT](https://github.com/la5nta/pat/blob/2e6a8d14baf0268f4e2aa4d01784a54ca935cf52/app/connect.go), [configuration](https://github.com/la5nta/pat/blob/2e6a8d14baf0268f4e2aa4d01784a54ca935cf52/cfg/config.go) |
| hfmodem | `a340f5cff17b` / 0.3.4 | [kestrel_host.py](https://github.com/sstjohn/hfmodem/blob/a340f5cff17b653f9c18765d4acf3182bc74ac12/tools/kestrel_host.py), [CONFIG](https://github.com/sstjohn/hfmodem/blob/a340f5cff17b653f9c18765d4acf3182bc74ac12/docs/CONFIG.md), [STATUS](https://github.com/sstjohn/hfmodem/blob/a340f5cff17b653f9c18765d4acf3182bc74ac12/docs/STATUS.md) |
| QK4 | `72025dfeea15` | [CAT server](https://github.com/mikeg-dal/QK4/blob/72025dfeea15fb31759c8dd03a6146912a6ca648/src/network/catserver.cpp), [audio engine](https://github.com/mikeg-dal/QK4/blob/72025dfeea15fb31759c8dd03a6146912a6ca648/src/audio/audioengine.cpp), [TCI design](https://github.com/mikeg-dal/QK4/blob/72025dfeea15fb31759c8dd03a6146912a6ca648/docs/tci-server-design.md) |

## Host and PTT path

Pat uses adjacent TCP command/data ports. Its VARA adapter sets compression,
MYCALL, bandwidth and LISTEN, and injects a Hamlib PTT controller when
`ptt_ctrl` is enabled. Pat's pinned Pat-Vara v1.2.0 dependency converts
`PTT ON/OFF` to `SetPTT`; its implementation discards returned PTT errors.
The guard therefore owns the independent unkey deadline.

The upstream Kestrel launcher already supports sound-card devices. Its
`AudioVaraIO` and `AudioHostRuntime` are reused by this project's small launcher.
Kestrel reports PTT to the host; no rig object is supplied. This avoids the
Yaesu profile defaults in hfmodem's full station CLI and leaves one normal PTT
controller, Pat. The project station TOML is intentionally separate from
hfmodem's full station-file schema.

The real Hamlib K4 backend emits `TX;`/`RX;` through the CAT guard. QK4 consumes
these as audio-gate requests, rather than forwarding TX/RX to the radio.
Incoming network audio then causes the K4 to transmit. QK4 remembers the CAT
socket that opened its gate and releases it on disconnect/server shutdown.
This behavior was also checked in the installed app's `1d7de138` source.

Power control needs different treatment. The installed Hamlib 4.7.2 K4
backend shares [K3-style power SET formatting](https://github.com/Hamlib/Hamlib/blob/4.7.2/rigs/kenwood/k3.c),
whereas [QK4 passes native K4 PC commands](https://github.com/mikeg-dal/QK4/blob/72025dfeea15fb31759c8dd03a6146912a6ca648/src/network/catframes.cpp).
The test therefore uses native `PC050L` (50 tenths = 5.0 W), requires that exact
readback, and restores the original native power frame. It does not use
Hamlib's normalized RFPOWER setter. Power writes remain blocked in the
ordinary CAT guard. Native SET/readback to 5.0 W and restoration to the
original 75 W setting were verified with TQ0 throughout and no generated
audio. Subsequent antenna testing verified RF output near the 5 W setting;
see STATUS for the internal meter values and their limitations.

The simulated-radio bench exercised actual Pat -> actual Hamlib -> guard ->
simulated QK4 commands. Tests also cover client disconnect, an overlong key,
supervisor loss, fragmented commands and oversized input. Normal live
key/unkey was subsequently observed on the approved antenna. Deliberate RF
fault handling and precise turnaround timing remain qualification gates.

## Audio fidelity and latency

QK4's speaker output is fixed at 12 kHz, two channels, Float32. Unsupported
formats cause output setup to fail; there is no output-rate fallback in the
reviewed source. The existing Loopback devices accept this format, verified
through Qt and the running app. BlackHole was neither needed nor installed.

Kestrel captures at 48 kHz. Its transmit audio is duplicated into stereo;
QK4 captures the virtual microphone at its preferred rate (48 kHz here),
then decimates to 12 kHz mono. Its microphone gain applies to that audio.
The 12 kHz sample rate is sufficient for these audio passbands; the measured
300–2700 Hz Loopback chirp retained about 63 dB residual SNR after 12->48 kHz
conversion. This measures a local cable and converter, not the radio chain.

QK4's raw modes carry EM0 signed S32LE containers with 24-bit payloads, or
EM1 signed 16-bit PCM. EM2/EM3 use the same Opus bitstream with integer/float
decode. EM0 uses approximately 0.768 Mbit/s per stereo direction before
packet/TLS overhead; EM1 approximately 0.384 Mbit/s. Raw EM0 is practical on
this LAN and avoids lossy encoding in the modem path.

The QK4 TX encoder uses 12 kHz mono, Opus VOIP application and 24 kbit/s.
An offline model of those exact settings recovered all four tested BW2300
MFSK payloads, but added substantially more waveform error than raw PCM.
Those results do not qualify high-speed OFDM, weak-signal reception, K4's
receive-side Opus encoder, packet loss or gateway performance. Choosing raw
for the initial setup follows the measured distortion and removes that
uncertainty; Opus is not proven unusable.

SL0 uses 20 ms frames; SL3 uses 60 ms. The receive engine prebuffers one
packet and feeds the device every 10 ms; it has a 500 ms sink capacity and
bounded jitter handling. Capacity is not a measured constant delay. The two
Loopback cable tests estimated about 16 ms each using PortAudio timestamps
anchored to callback time. Opening the first output stream stalled early
input delivery, so the diagnostic anchors its comparison to the detected
signal's block rather than assuming an unbroken sample timeline.
Independent calibration and radio/network turnaround remain outstanding.

The initial 200 ms PTT lead and 150 ms audio tail are conservative,
**unqualified** settings. Live testing must check leading/trailing
audio, RF return to zero and fast modem turnarounds before RMS operation.

## TCI decision

QK4's TCI server offers audio and CAT together, with documented FT8 successes.
The reviewed standalone Kestrel audio launcher supports sound devices and
does not expose a TCI backend. Reusing Loopback and CAT required no new TCI
implementation. TCI stays unused for this setup.

## Evidence boundaries

Upstream STATUS documents VARA Winlink mail reception through K0SI and
confirmed outbound delivery through KB8AY. That is evidence for Kestrel's
interoperability at those stations. This Mac subsequently transmitted VARA
connect requests at a 5 W setting, but has not yet connected to an RMS or
transferred a Winlink message.
