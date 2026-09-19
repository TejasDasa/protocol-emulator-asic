# STT — a programmable protocol emulator ASIC
 
An open-source protocol emulator for the [Jane Street ASIC design
competition](https://blog.janestreet.com/protocol-emulator-asic-competition/),
targeting IHP's 130nm CMOS5L process through Tiny Tapeout at 6×4 tiles.
 
Five independent state machines bit-bang hardware protocols from firmware.
Each executes one 32-bit row per clock cycle — no pipeline, no stalls, no
skipped cycles — which makes protocol timing something you read off the
program rather than count and hope about. Which protocols the chip speaks is
reprogrammable after fabrication.
 
Implemented and passing: UART TX, UART RX, SPI mode 0, I²C master, USB
low-speed token TX, JTAG TAP, CAN, and a UART protocol detector.
 
## Start here
 
- **[`docs/SPEC.md`](docs/SPEC.md)** — the normative specification. The single
  source of truth for the instruction set, the timing model and the chip
  boundary. If you read one thing, read this.
- **[`docs/writeup.md`](docs/writeup.md)** — the argument: what the
  architecture makes possible, why the shared units exist, and what the
  verification found.
- **[`docs/row-format-decision.md`](docs/row-format-decision.md)** — how the
  row format was chosen, and what the alternatives cost.
- **[`docs/area-study.md`](docs/area-study.md)** — the area and integration
  measurements, including §8's record of conclusions that turned out to be
  wrong.
## The instruction set in one paragraph
 
A row says one thing: *when this test passes, do these actions, then go
there*. Ten test codes read the timer, two counters, a shift-register bit,
input pins, or FIFO status. Thirteen bits encode actions inline across five
mutually-exclusive groups. Eight bits name a branch target, and a two-bit mode
derives both the true and false exits from it. There is no implicit
fall-through — every row carries its own successor, which is what lets a
single self-looping row be a precise wait. A program is at most 32 rows.
 
## Repository layout
 
| Path | What's in it |
|---|---|
| `spec/` | `isa.json`, the machine-readable encoding source, plus the generator and conformance checker |
| `docs/` | The specification and the written arguments |
| `rtl2/` | The implementation: five machines, iomux, host interface, TT-legal top |
| `isa_bench/` | Python ISA models, the protocol programs, and the device models they run against |
| `rtl/` | **Superseded.** A structural harness written to measure area under the previous row format. It has never passed a functional test and is kept only so the area study stays reproducible. |
| `floorplan/` | Place-and-route configuration and results |
| `pdn_test/` | The CFGMEM power-integration recipe and its test harness |
 
## Building and testing
 
```bash
make check
```
 
That runs everything: specification drift, latch checks, the frozen-format
check, the per-machine flop-slope gate, the mutation floor, and every
benchmark. It exits non-zero on any failure.
 
The encoding is generated, not transcribed. `spec/gen_spec.py` emits the
tables in `docs/SPEC.md` from `spec/isa.json`, and `spec/conformance.py`
checks that source against the Python models. A change to the encoding that
isn't reflected everywhere is a build failure rather than a silent
inconsistency.
 
## Verification
 
Four adversarial layers, all of which must pass:
 
- **Cycle-exact lockstep.** The RTL and the Python model step together and are
  compared every cycle on every architectural register and FIFO operation, not
  just on final output. Seven programs, and five machines each against their
  own model.
- **Mutation.** Programs are corrupted one point at a time — wrong test code,
  wrong branch mode, shifted target, dropped action, wrong pin op — and the
  benchmarks must catch it. The gate fails on a score drop *and* on a mutant
  count drop, which catches a benchmark being quietly removed.
- **Random programs.** Generated programs reaching encoding paths no
  hand-written protocol exercises. This is what found the decode bugs mutation
  structurally cannot reach.
- **Directed tests.** The instruction-memory load path and the pin boundary,
  where the lockstep suites are blind because every program loads through the
  same path.
Timing is part of conformance: UART TX and USB require zero jitter, SPI and
I²C require every clock phase to meet its minimum, and the device models
inject phase offset and jitter rather than producing clock-aligned edges.
 
## Physical status
 
Signoff clean at five machines: zero DRC (Magic, KLayout and the router), zero
LVS errors on every sub-count, zero antenna violations, 0.02% worst-case IR
drop.
 
Worst-case setup timing is −2.20 ns at the slow corner, so roughly 45 MHz.
This is a violation against the 50 MHz template target, not a target that was
met — see `docs/SPEC.md` §16. Every protocol in the conformance set has
substantial headroom at that clock.
 
Two physical constraints are worth knowing before reproducing any of this.
Instruction-memory macros must be placed on the power-stripe grid, or the
entire power network is left without a source and signoff fails. And macros
cost more routing resource than their footprint suggests, because they block
three of the four metal layers beneath them while the fourth carries power —
area arithmetic overestimates how many fit. Both are documented in
`docs/SPEC.md` §14 and `pdn_test/README.md`.
 
## Known limits
 
Inter-pin skew is unmeasured — the model has no pin path, and skew between a
clock and its data is the failure mode that matters in silicon. Phase
independence has been tested on inputs only. Of 622 max-fanout violations, 320
are inside the vendored memory macro and outside this design's control; the
remaining 302 survived both available levers. `docs/SPEC.md` §16 is the
complete list.
 
## License
 
Open source, as the competition requires. See `LICENSE`.