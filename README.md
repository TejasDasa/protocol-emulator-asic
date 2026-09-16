# Protocol emulator — milestone 1: one UART TX pin

An initial Hardcaml UART transmitter and autonomous pin demo. This is a
reference implementation for the protocol-emulator project, not yet the
competition's programmable architecture.

## Run using your existing working switch

Extract this directory beside `hardcaml_template_project`, under `~/projects`.
It is a separate small Dune project. It uses the already installed `hardcaml`
library and does not require a new switch or another package installation.

```bash
cd ~/projects/protocol-emulator-uart
opam exec --switch=5.2.0+ox -- dune runtest -j 1
mkdir -p generated
opam exec --switch=5.2.0+ox -- \
  dune exec bin/generate_uart.exe -- hello 10000000 115200 \
  > generated/uart_hello.v
```

`uart_hello` has `clock`, `clear`, and a single `tx` output. After reset it
repeatedly transmits ASCII `U` (`0x55`). Supply a clock matching the generator
argument and assert `clear=1` for at least one rising clock edge before use.
It does not have a power-up initialization guarantee without reset.

Generate the reusable transmitter with its internal byte interface:

```bash
opam exec --switch=5.2.0+ox -- \
  dune exec bin/generate_uart.exe -- tx 10000000 115200 \
  > generated/uart_tx.v
```

The generator prints timing information to stderr and only Verilog to stdout.
The clock value is an example for the prototype, not an ASIC timing commitment.

## Contract

| Signal | Direction | Meaning |
| --- | --- | --- |
| `clock` | input | Rising-edge core clock |
| `clear` | input | Active-high synchronous reset; aborts any active frame |
| `data[7:0]` | input | Byte to transmit |
| `valid` | input | Producer offers a byte |
| `ready` | output | Byte can be accepted; low during reset and transmission |
| `tx` | output | Idle-high serial output |

The `data`, `valid`, and `ready` signals are internal chip interfaces, not
additional serial pins. They disappear in the autonomous `uart_hello` top.
All control inputs must be synchronous to `clock`. For the reusable interface,
a producer keeps `valid` and `data` stable until an edge where `ready=1`.

On an edge where `valid && ready`, the transmitter latches the entire byte
and drives the start bit low. The format is 8N1: one low start bit, eight
data bits least-significant first, and one high stop bit. Each bit lasts
exactly `clocks_per_bit` clocks. `ready` returns high only after the complete
stop bit. The next byte can be accepted on the next rising edge, giving one
additional idle clock between frames when `valid` is held high. This version
has no FIFO and no zero-gap optimization.

Changes to `data` while busy do not change the current frame. A `valid` pulse
entirely within the busy interval is not queued. Holding `valid` high until
the next accepting edge supplies the next byte normally.

Reset takes priority over transmission and acceptance. On a rising edge with
`clear=1`, TX returns high and the partial frame is discarded. The receiver
may see a malformed frame after a mid-frame reset; the next accepted byte
starts a fresh frame.

## What hardware is created?

`lib/uart_tx.ml` contains four registers:

* A 10-bit frame shift register, loaded with stop/data/start bits.
* A 4-bit count of remaining frame bits.
* A countdown timer for the current bit.
* A 1-bit inverted TX register, so synchronous clear-to-zero gives idle high.

Only the timer reaching zero advances the frame. TX is driven by the inverted
output of a single register; the clock is never divided or gated. The widths
and bit period are elaboration-time parameters in this first milestone.

`clocks_per_bit = round(clock_hz / baud)` and
`actual_baud = clock_hz / clocks_per_bit`.
At the default 10 MHz and requested 115,200 baud, the divider is 87 and actual
baud is approximately 114,942.529 (-0.2235%). Other combinations can have larger
rounding errors; inspect the generator's reported error before hardware use.

For `0x55`, the ten serial bits are: start `0`, data `1 0 1 0 1 0 1 0`, stop `1`.

## Verification

`test/test_uart.ml` uses Hardcaml Cyclesim and a pin-level scoreboard. It checks:

* Every byte (0–255) at divisors 1, 2, 3, 7, 16, and 87.
* Every clock of the start, data, and stop bits, including the exact ready edge.
* Input-data changes and asserted valid during busy periods.
* Consecutive frames with valid continuously asserted.
* Reset at every clock offset in a frame at divisors 1, 3, and 7, followed by
  a fresh successful frame.
* The autonomous `U` stream and rejection of an invalid zero divider.

These are ordinary Dune executable tests, with explicit failures rather than
expect-output promotion. Success prints a line beginning `PASS:`.

Generate a waveform from the same actual Cyclesim outputs:

```bash
opam exec --switch=5.2.0+ox -- \
  dune exec test/test_uart.exe -- uart.vcd
```

This reruns the tests, then emits `uart.vcd` with bytes `0x55` and `0xA5`, a
10 MHz clock, and 87 clocks per bit. A VCD viewer can open the file. Inputs are
shown on falling edges and outputs sampled after rising edges; this is a
cycle-level trace, not an event-level model of combinational propagation.

Validation status at delivery: source reviewed and integer transition-model
timing checked locally. The delivery workspace has no OCaml/Hardcaml runtime;
the supplied Hardcaml tests have not been compiled or executed here. Run the
commands above in the existing WSL switch to validate the implementation.

## Next steps for the ASIC competition

1. Pass these tests and inspect the `U` waveform.
2. Generate `uart_hello.v` and connect its TX output through the competition's
   CMOS5L Tiny Tapeout wrapper. Clock/reset and pad mapping belong in that
   wrapper. The full RTL-to-GDS template is not included here.
3. Replace the fixed UART framing controller with a programmable pin engine:
   instruction storage, deterministic wait/count operations, output control,
   and shift/branch operations. Reuse the UART pin-level tests to validate its
   first firmware program. Add loading/control interfaces before fabrication.

An external receiver needs a common ground and compatible logic-level input.
Choose physical voltage levels and board wiring once the target board is known.

## Sources

* [Hardcaml sequential logic](https://docs.hardcaml.org/hardcaml-docs/designing-circuits/sequential_logic/)
* [Hardcaml Cyclesim](https://docs.hardcaml.org/hardcaml-docs/simulating-circuits/simulation/)
* [UART frame format](https://onlinedocs.microchip.com/oxy/GUID-EC8D3BAB-0B5E-454F-AB6E-6A7C91C6F103-en-US-3/GUID-585072A2-2328-4EDD-B24F-E2E7672632B5.html)
* [Competition CMOS5L template](https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l)
