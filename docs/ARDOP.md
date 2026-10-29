# Selectable ARDOP

VARA/Kestrel remains the default. `mise run start --modem ardop` selects
Besra from the already pinned hfmodem source and enables transmission for
operator use. Add `--receive-only` for passive diagnostics. Always stop the
existing station from its owning checkout before switching. Runtime data,
mail and credentials belong to each checkout; an isolated JJ workspace does
not inherit the primary checkout's `.local` or `.env`.

```sh
mise run start --modem ardop --receive-only
mise run doctor
mise run receive-check                    # Current dial; restores test settings
mise run stop
```

For normal mail operation after hardware validation, start with `--modem ardop`
without `--receive-only`, open [Pat](http://127.0.0.1:8080/ui), and choose ARDOP.
Use a current RMS listing and its **dial kHz**, not the audio centre (dial +
1500 Hz). `mise run pat rmslist --mode ardop --band 20m` lists gateways without
RF. Besra accepts 200, 500, 1000 and 2000 MAX negotiation. This adapter rejects
FORCED because the pinned caller would otherwise silently send MAX.
Beacons are disabled. CW identification is enabled; normal completion waits
for closing ID before Pat can restore frequency. Emergency stop can cut ID short.

```text
Pat -> ARDOP :8515/8516 -> Besra -> existing Loopback cables
Pat -> rigctld :4532 -> CAT guard :9300 -> QK4 :9299 -> K4
```

Only the selected modem runs. A shared station lock across workspaces and
checks of both modem port pairs prevent competing supervisors from taking
the radio/audio path. Stop does not switch modes automatically. The same
DATA-A normal, DT0, >=2.8 kHz RX filter and stable QSY checks apply to both
modems, including Connect without a frequency. Normal stop leaves DATA-A set.
Pat CLI/config commands preserve the running modem selection.

Receive-only keeps Pat attached for monitoring, but the actual ARQ core never
listens for calls it could answer. Outgoing calls and data, ID/test key
notifications, audio playback and guarded CAT keying are independently blocked.
Receive-only opens the RX stream without warming or opening the TX cable.
ARDOP monitors its capture stream, receiver and timer threads. A modem or
other child exit shuts down the stack, with guarded CAT closed first.
`doctor` checks processes and Pat's active listener without attaching a modem
client. Logs are `.local/logs/ardop.log`, `pat.log` and `supervisor.log`.

## Backend choice

The [pinned Besra source](https://github.com/sstjohn/hfmodem/tree/a340f5cff17b653f9c18765d4acf3182bc74ac12/packages/hfmodem/hfmodem/besra)
already supplies a real ARDOP PHY/ARQ core, two-port host server, 12-to-48 kHz
conversion and continuous rolling receiver. Its standalone radio launcher
expects named rigs and serial-line PTT, so this repository uses those components
with a small Loopback adapter and leaves PTT authority with Pat. No new
dependency, source pin or QK4/Loopback preference change is needed.

On-demand switching is plausible, but would require a session-aware owner that
retires one decoder/output path and attaches the next before admitting a dial.
The upstream multi-lane station also owns its own audio and transmit arbitration;
adopting it here would replace the existing Pat/PTT integration. Explicit
selection keeps that hardware path and its shutdown behavior consistent.

## Verification and remaining hardware work

Completed without radio or sound-device access:

- TCP receive-only call/ID/test/data refusals and a real incoming connect frame
  that produces no key notification or reply.
- Real Besra waveform connect, payload transfer and disconnect over simulated air.
- Stereo 48 kHz playback shape, peak ceiling, PTT ordering, playback failure,
  retirement, closing-ID ordering and cancellation with playback stubbed out.
- Actual pinned Pat and Hamlib against a simulated K4: ARDOP initialization,
  QSY/band recalls, failed DATA-A blocking Connect with and without `freq`,
  receive-only dial refusal, PTT forwarding and deadman unkeying. VARA passes too.
- Supervisor selection, workspace exclusion, child failures and guard-first
  shutdown, plus task argument forwarding and configuration safety checks.

Repeat with `mise run check`, `mise run bench-ptt --modem ardop` and
`mise run bench-ptt`. The benches use separate loopback ports and simulated
CAT; they never open an audio device or the real QK4 connection.

Hardware validation still required, under the operator's control:

1. Receive-only: verify device access, non-silent/unclipped RX, DATA-A after
   same-band and cross-band QSY, and clean stop. Confirm no TQ1 or TX audio.
2. With the station stopped, positively confirm K4 **TX TEST**, then qualify
   the ARDOP waveform and ALC on both bands. The existing 0.35/25 drive pair
   was measured for Kestrel; it does not establish ARDOP drive quality.

   ```sh
   mise run tx-test --radio-test-mode --signal ardop-connect  # Offline plan
   mise run tx-test --execute --radio-test-mode --signal ardop-connect --dial-khz 7101
   mise run calibrate-audio --signal ardop-connect            # Offline sweep plan
   ```

   Execution checks the active TX TEST indicator through QK4 Vail and requires
   logical TX with zero forward-meter samples. Check TX bandwidth, lead/tail
   timing, waveform clipping and return to receive; restore TX NORM afterward.
3. With explicit approval for each RF test, confirm a clear channel and use a
   current listed MAX gateway. Besra's host BUSYBLOCK setting does not establish
   a busy-channel interlock here. A bounded link test now accepts `ardop:///…`
   URLs and refuses a modem mismatch; without `--execute` it only prints a plan.
   Verify active-over stop/deadman timing, closing ID before QSX, actual RF
   quality, gateway interoperability, authentication and mail transfer.

No ARDOP hardware, RF, gateway or mail success is claimed by the simulations.
