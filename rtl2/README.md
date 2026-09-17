# rtl2 — the implementation of the frozen ISA

One state machine that runs all six reference programs in **cycle-exact
lockstep** with the authoritative Python models. `docs/SPEC.md` is normative;
where anything here and the spec disagree, the spec wins.

`rtl/` is untouched. It implements the *previous* row format (21-bit, 5-bit
target, palette), has never passed a functional test, and exists to keep the
area study reproducible. This is a separate implementation, not an extension.

## What is implemented

| | |
|---|---|
| row fetch and decode | asynchronous imem read, 32 rows x 32 bits (SPEC §12) |
| the seven-step cycle | SPEC §8.1, in one combinational block |
| test codes | all ten (SPEC §4), read on start-of-cycle state |
| action groups | all five, in the SPEC §6.3 order |
| pin operations | all seven ops, three slots plus the pair (SPEC §7) |
| branch modes | all four, `RET`, and `next` wrapping mod 32 (SPEC §5) |
| timer | free-running, `trst`/`thalf` only on a passing row (SPEC §8.4) |
| counters | both, wrapping mod 256 |
| shift register | configurable width, direction and fill |
| CRC5 | per state machine, reflected polynomial 0x14 (SPEC §9) |
| input synchronizer | two cycles (SPEC §8.3) |
| serial load | staging register, bit counter, write pointer (SPEC §12) |
| configuration | one serial chain holding the SPEC §2 configuration list |

## Deliberately NOT implemented

Still absent rather than half-built: `crc_lfsr16`, `bit_stuffer`, and the
reserved codes of SPEC §9.

The host byte port is brought out as module ports rather than reaching real
pins. Giving the host pins needs the iomux to reserve some, which output select
code 15 is free to express -- there are 15 drivers, 0..14 -- and that is the next
step.

Done since: replication to five machines, `stt_iomux` with the pin-assignment
chain, the `run` flag, and per-machine host FIFOs.

Both memories are built and both pass every suite: `stt_imem.v` is a
behavioural array, `stt_imem_cfgmem.v` drives two real `CFGMEM_IHP16` macros.
See "The CFGMEM_IHP16 swap" below. The read is asynchronous either way, which
SPEC §12 requires and the macro's liberty confirms: no `CLK` pin, no `ff()` or
`latch()` groups, all 224 timing arcs `timing_type : combinational`, worst
address-to-data 1.994 ns.

## Verification: lockstep, not expectation

Three layers, all asking the same question -- does the RTL agree with `SttCore`
cycle for cycle? -- and differing only in which programs they ask it about. The
second and third each found a real bug; see below the table.

The models are authoritative (SPEC §0), so the testbench does not compare the
RTL against hand-written expectations. It steps `SttCore` and the RTL together
and compares the whole architectural state **every cycle** — row, link, sr, cnt,
c2, crc, tcount, pinv — plus every FIFO operation and its data. The first cycle
they differ fails the test and names the field, the cycle and both values.

The world, devices, payloads and stop condition come from `isa_bench/bench.py`
itself: `World.run` is monkeypatched to stash its arguments instead of running,
so the testbench cannot drift from the benchmark it mirrors. The model drives
the world and the RTL shadows it; this is deliberately not co-simulation, which
could hide a divergence in a feedback loop.

| program | rows | cycles in lockstep |
|---|---|---|
| UART TX | 5 | 2232 |
| UART RX | 8 | 2888 |
| SPI mode 0 | 8 | 1316 |
| I²C master | 22 | 1621 |
| USB LS token TX | 16 | 4584 |
| JTAG TAP | 25 | 818 |
| **total** | | **13,459** |

`uart_rx` reports "ran to max_cycles" because its benchmark has no early-done
condition, not because anything went wrong.
### What the six reference programs do NOT cover

They prove the thing works; they are not what finds bugs, because they were
written to drive six protocols rather than to cover the ISA. `tb/coverage.py`
measures how much of the encoding they reach:

```
field       cap  encoded  executed   never executed
test         10        9         9   7:in1l
pin_op        7        6         6   6:d1
act_xx        5        4         4   1:crcrst
                                     (mode, pin_slot, act_sr, act_c1,
                                      act_c2, act_tm all complete)

rows: 84 of 84 encoded rows are reached at run time
code coverage: 46/49 = 93.9% of defined field values executed
```

### Mutation, against the RTL rather than the models

`tb/test_mutants.py` takes the single-point corruptions `isa_bench/mutate.py`
applies to a program, encodes each mutant at the frozen format, and runs it on
both the model and the RTL. The mutant is *not* expected to pass its benchmark —
that is what `mutate.py` measures. What is expected is that the RTL and the model
**agree about what the corrupted program does**, since they are executing the
same rows.

```
mutants checked in lockstep: 541  (uart_tx 29, uart_rx 40, spi 57,
                                   i2c 135, usb 105, jtag 175)
  skipped, not encodable at 32 bits: 27
  skipped, model raised:             14
  executed code coverage: 49/49 = 100.0%
  divergences: 0
```

**Found one real bug.** `uart_tx/act_add/row START: add action load` drains the
TX FIFO faster than the program refills it and reaches `load` on an **empty
FIFO** at cycle 995. The model calls `w.error` and leaves the shift register
unchanged; the RTL loaded whatever was on `tx_data`, which is 0 when the FIFO is
empty. SPEC §16.1 records this case as unspecified — "the model raises an error;
hardware behaviour is undefined" — so the RTL now follows the model, holds the
shift register and issues no pop. **This is a candidate for §16.1 to specify
rather than leave open.**

### Random 32-row programs

Mutation reaches 100% of individual field *values*, but only combinations near
programs somebody wrote, and it structurally cannot reach two things:

* **`next` wrapping from row 31 to row 0** (SPEC §5). No reference program has
  32 rows — the largest is JTAG at 25 — and mutation does not add rows, so
  *nothing in the repository executed that wrap*.
* Most combinations of mode × target × pin op × action group. **RET is used by
  exactly one row of one program** (USB row 8).

`tb/randprog.py` generates 32 rows of random legal fields, so row 31 exists and
its `next` exit wraps. Words are generated first and the symbolic program is
decoded *from* them, so the model and the RTL provably run the identical
program. No expected output is needed: any program the model can run is a valid
test.

**Found a second real bug, which the reference programs cannot expose.** The
`srbit_of` function read `cfg_shift_left` and `msb_idx` from the enclosing scope
instead of taking them as arguments. That is legal Verilog, but it leaves the
continuous assignments `srbit_pre`/`srbit_mid`/`srbit_post` sensitive only to
their `v` argument, so each was computed once at time 0 — when the configuration
register still held X — and re-evaluated only when the shift register changed.
Every reference program shifts constantly, which refreshes the stale value and
hides it completely. A random program that left the shift register at zero for 33
cycles carried the X into the `srbit` test and into `test_pass`. All dependencies
are now explicit arguments.

That bug also exposed a hole in the testbench: an X in the DUT was being caught
as "model raised ... not comparable, skipped". A test that skips on X cannot fail
on X, so `steps.py` now treats a non-0/1 read as a named failure.

### The directed load-path test

All three lockstep suites load the program through the same serial path, so they
do exercise it — but they visit whatever rows the program branches to, and
nothing guarantees all 32 addresses are ever read. `tb/test_imem.py` writes six
patterns (zeros, ones, walking-one, walking-zero, alternating, and a
distinct-per-row pattern that catches a row written to the *wrong address*) and
walks the row pointer across every address, reading back through the real read
path. **192 address reads across 6 patterns.**

It matters most for what comes next. Replacing the behavioural array with two
`CFGMEM_IHP16` macros introduces a one-hot `WROW` write decode that the
behavioural model does not need — new logic, in the one place all three suites
are blind, because they all load through it identically.

Separately, `tb/steps.py` now checks on **every cycle of every suite** that the
word the RTL is about to execute is the word that was loaded at that address.

## Synthesis

Against `sg13cmos5l_stdcell_typ_1p20V_25C`: **1197 flops**, chip area
94,517.96 µm². Every flop is accounted for by the architecture, which is the
point of reporting it — there is no accidental state:

```
imem    1024 storage + 32 staging + 5 bit counter + 5 write pointer = 1066
config    69 (one shift register holding the SPEC section 2 list)
core      10 rowp/link + 24 sr/cnt/c2 + 24 crc/tcount/pinv + 4 sync =   62
                                                             total   1197
```

The imem dominates because it is flops in this pass. The real design puts those
1024 bits in two `CFGMEM_IHP16` macros, which is the whole reason the row format
was frozen at 32 bits (`docs/row-format-decision.md`). Do not read 94,517 µm² as
a per-machine area figure; it is not comparable to the area study, which charges
the macros instead.

**No inferred latches**, asserted by the synthesis script rather than assumed.
Verified in both directions: deleting the default assignment in the pin-op block
makes it fail with `Assertion failed: selection is not empty: t:$dlatch`.

## The CFGMEM_IHP16 swap

`IMEM=cfgmem` builds `stt_top_cfgmem` with the memory in two `CFGMEM_IHP16`
macros instead of the behavioural array. Every suite runs unchanged on both,
which is the point: the swap must change nothing observable.

| suite | behavioural | CFGMEM macros |
|---|---|---|
| 6 reference programs | 13,459 cycles, no divergence | same, no divergence |
| imem load path | 192 address reads, 6 patterns | same |
| random 32-row programs | 40/40, 49/49 codes | same |
| mutants | 542, 0 divergences | same |

**Flop count, which is the check that the swap actually reached the macro:**

| | flops | logic area |
|---|---|---|
| behavioural array | 1197 | 94,583.16 µm² |
| CFGMEM macros | **213** | 20,548.42 µm² (macros charged separately) |

A drop of **984** — the 1024 storage flops removed, less the ~40 the walking
loader adds. Had it come back near 1197 the macro had not been blackboxed; near
173, the loader had not synthesised.

### What the macro actually is, and what that cost

`CFGMEM_IHP16` is a **shift chain, not a random-access array**. Only row 0 can
be written from `Di0`; every other row takes its predecessor. See SPEC §10 for
the three confirmations and the resulting host protocol.

Three write schemes were tried and the directed test rejected the first two:

1. **one-hot `WROW`** — what `rtl/stt_imem_cfgmem.v` does. Copies the previous
   row into the selected one. Cannot work at all.
2. **all rows open** — the value ripples down the whole chain in one strobe.
3. **even/odd two-phase** — whichever half runs second reads rows the first half
   already updated.

What works is prism's: walk a one-hot enable from row 15 **down** to row 0,
three clocks apiece, so each row is written while its source still holds the old
value. 48 cycles per row, during which `ld_busy` is high.

The second requirement took a second failure to find. After the walk was right,
five of six reference programs still failed — and the pattern named the cause:

| | rows | result |
|---|---|---|
| random programs | 32 | pass |
| USB | **16** | pass |
| uart_tx, uart_rx, spi, i2c, jtag | 5, 8, 8, 22, 25 | **fail** |

Everything that passed was a multiple of 16. Writing *k* words into a tile
leaves them at chain rows 0…*k*−1, so the read mapping only holds when a tile
gets all 16. Hence the full-load rule: the host loads all 32 rows, padding.

**None of this was visible to the three lockstep suites before the swap.** They
all load through the same path and visit only rows a program branches to. The
directed test exists for exactly this, and it found every one of these.

## Replication: five machines

`stt_array.v` instantiates NSM machines. Replication and nothing else — each has
its own imem, configuration register and core, and they share only the clock,
the reset and the serial load data. There is deliberately **no iomux, no run
flag and no shared host FIFO yet**: pins and host bytes come out per machine,
flattened, so independence can be proven before anything is shared.

`-DIMEM_MACRO` selects the CFGMEM-backed machine; the port lists are identical
by construction, so only the module name changes.

### Independence is the thing being tested

The failure mode for replication is not that a machine computes the wrong
answer. It is that machines are **not independent**: a load reaching the wrong
one, or instances synthesis merged because they were never given different
state. This project has already made that error once — every machine received
the same serial stream, held identical state, and Yosys merged them, understating
per-machine cost by ~180 flops (`docs/area-study.md`).

So `tb/test_multi.py` does not run one program five times. It loads a
**different** reference program into each machine, gives each its own `SttCore`
and its own `World`, and compares all five against their own models on every
cycle:

```
5 machines in lockstep for 2500 cycles, no divergence:
  uart_tx(5r), uart_rx(8r), spi(8r), i2c(22r), jtag(25r)
```

Passes with both memories. A machine disturbed by its neighbour, or a load that
addressed the wrong one, diverges immediately and the failure names which
machine and which field.

### The flop slope gate

The structural counterpart. N machines must cost exactly N times one machine:

| NSM | flops | expected | area (µm²) |
|---|---|---|---|
| 1 | 1196 | — | 94,646 |
| 2 | 2392 | 2392 ✓ | 189,306 |
| 5 | **5980** | 5980 ✓ | 472,778 |

Verified in the failing direction: replacing the per-machine load select with a
constant makes five machines cost **5580** rather than 5980 — merging would
quietly cost 80 flops per machine — and `check_slope.py` exits 1.

Area is very slightly sub-linear (5 x 94,646 = 473,232 against 472,778 measured)
because the machines share the `sm_sel` decode. Flops are exactly linear, which
is the property that matters for detecting merged state.

## The Tiny Tapeout boundary: iomux and the run flag

`stt_iomux.v` and `stt_chip.v` implement SPEC §11.1. The output side is
pin-centric — each of the 16 output-capable pins carries a 4-bit field naming
the one driver that drives it, so two machines cannot contend for a pin. Inputs
are the same shape. One 105-bit chain holds the assignment and the `run` flag.

`tb/test_chip.py` configures the chip the way a host actually would: five
machines over `ui_in` with machine select on `uio_in[7:5]`, then the
pin-assignment chain, then `run`. Then it checks, every cycle, each machine
against its own model **and** each assigned driver on its assigned pin.

```
machines started 2 cycles after run
5 machines through the TT boundary for 2000 cycles,
  no divergence and every assigned pin correct
output pins used: [0,1,2,3,4,5,6,8,9]   input pins used: [0,1,2,3,4]
```

The assignment is deliberately **not** the identity, and splits by drive mode:
open-drain slots to `uio` (SPEC §11 — a `uo_out` pin is always driven and cannot
release a net, so I²C would not work there), push-pull to `uo_out`, packed in
use-order within each group. That exercises all three output behaviours the spec
distinguishes, including `uio_oe` on an open-drain release.

### Five bugs, and where they lived

Three were in the RTL, all in the gap between "the machines work" and "a host
can bring the chip up" — none reachable from `test_multi.py`, which drives the
array directly and never touches the chain or the boundary:

1. **`run` taken from the shift register's MSB.** New bits enter at the MSB, so
   `run` flickered with the data and the first `1` in the chain gated off
   `sel_ld_en` and froze the load permanently. It is now bit 0, sent first, so it
   arrives exactly on the final shift. In silicon this would have made the chip
   unconfigurable.
2. **Machines started before their inputs were valid.** `run` is the last bit of
   the chain, so `ui_in` carries chain data right up to the moment it goes high.
   `uart_rx` read a chain bit as a UART start bit. `stt_chip` now releases the
   pins on `run` and enables the machines two cycles later, so §8.3 is satisfied
   by construction.
3. **`uo_out[0]` aliases loader busy only while `run` is low.** A real host
   constraint, now in §11.1.

Two were in the testbench: the host byte interface was not driven, and `ui_in`
was set *before* stepping the model rather than after. The second is subtle —
invisible for any machine reading an external driver, and caught only by I²C,
because I²C reads the same wires it drives.

## Host buffering

`stt_hostbuf.v` gives every machine its own TX and RX byte FIFO, built from
`stt_fifo.v`. SPEC §9 pins the depth at **4** and specifies overflow and
underflow; both were open items in §16 and are now closed.

**Per machine, not shared**, and that is correctness rather than preference. The
models give every `SttCore` its own queues. A shared buffer with round-robin
arbitration — which `rtl/stt_hostbuf.v` implements and the area study priced —
loses a machine's `push` on any cycle it loses the arbiter, and §8.1 forbids
stalling to retry. Cycle-exact lockstep against a per-machine model could not
hold, and that lockstep is what the whole rtl2 effort rests on. The cost is
5 × 2 × 4 × 8 = 320 storage flops plus pointers against roughly 100 shared.

**Why 4.** Measured at each program's minimum working bit period, the binding
case is the fastest *receiver*, not the slowest protocol:

| protocol | dir | min cyc/bit | cyc/byte | depth-4 budget |
|---|---|---|---|---|
| **uart_rx** | **RX** | **3** | **30** | **120 cycles** |
| spi | both | 6.525 | 52.2 | 209 |
| i2c | both | 5.875 | 52.9 | 212 |

So depth 4 gives a host 120 cycles — 2.55 µs at the 47 MHz of §14 — to service a
byte. `FIFO_DEPTH` is a parameter.

> A capture mode pushing one entry per *edge* would not be served by more depth:
> an edge can arrive every 3 cycles, so depth 4 gives 12 and even depth 32 gives
> 96. That capability needs different machinery, not a bigger FIFO.

### What the tests cover, and what they cannot

`tb/test_chip.py` exercises the FIFOs in traffic: the host services one machine
per cycle round-robin, topping up TX and draining RX, and every drained byte is
checked against the model's push order. But **it never fills a FIFO** — that is
precisely what depth 4 buys — so the boundary behaviour has no coverage there.

`tb/test_fifo.py` drives `stt_hostbuf` directly for that: exactly DEPTH bytes
fit, a write to a full FIFO is dropped and leaves the contents **in order**
rather than overwriting the oldest, a pop from empty is a no-op, both set sticky
flags that stay set, the flags are **per machine**, and reset clears them.

### The benchmarks queue more than the hardware holds

`uart_tx` drops all 7 payload bytes into an unbounded model queue on cycle 0,
against a 4-deep FIFO. `test_chip.py` therefore intercepts whatever the
benchmark's host device queues and releases it to **both sides together** as the
hardware has room, so the two queues stay identical and the lockstep stays exact.
The interception runs every cycle, not once up front — the device fires inside
the loop.

## Running the tests

Everything needs LibreLane's devshell (iverilog, yosys) plus the cocotb venv:

```bash
export NP_LOCATION=/home/tejas/eda NP_RUNTIME=bwrap
nix-portable nix shell /nix/store/lrlpbc...-devshell-dir --command bash

# cycle-exact lockstep, all six programs
cd rtl2 && /home/tejas/venv-cocotb/bin/python tb/run_tests.py

# mutation and random-program lockstep
/home/tejas/venv-cocotb/bin/python tb/run_mutants.py
RAND_N=60 RAND_CYCLES=500 /home/tejas/venv-cocotb/bin/python tb/run_random.py

# how much of the encoding the six reference programs reach
python3 tb/coverage.py

# one program
/home/tejas/venv-cocotb/bin/python tb/run_tests.py i2c

# the macro variant: every suite, same commands
IMEM=cfgmem /home/tejas/venv-cocotb/bin/python tb/run_tests.py
IMEM=cfgmem /home/tejas/venv-cocotb/bin/python tb/run_imem.py

# synthesis and the latch gate, either variant
bash rtl2/run_synth.sh          # behavioural
bash rtl2/run_synth_cfgmem.sh   # macros blackboxed
```

`make check` runs the two gates that need no simulator: the generated-header
drift check and the latch gate. `make rtl2-test`, `make rtl2-mutants`,
`make rtl2-random` and `make rtl2-full` run the simulation suites and need
`COCOTB_PY` pointed at the cocotb venv.

Note that cocotb 2.x's `runner.test()` does **not** raise when a test fails — it
returns a JUnit XML path. `tb/run_tests.py` parses it, because a gate that
cannot fail is not a gate. That was caught by watching it report "OK" on a
failing run.

## Files

| file | |
|---|---|
| `stt_isa.vh` | **generated** from `spec/isa.json` by `gen_isa_vh.py`; never edit |
| `stt_core.v` | the SPEC §8.1 cycle |
| `stt_imem.v` | 32x32 behavioural array plus the SPEC §12 load path |
| `stt_imem_cfgmem.v` | the same, driving two `CFGMEM_IHP16` macros |
| `cfgmem_ihp16_model.v` | simulation model of the macro; synthesis uses the real one |
| `stt_top_cfgmem.v` | top with the macro-backed memory |
| `stt_array.v` | NSM independent machines |
| `check_slope.py` | the flop-slope gate |
| `tb/test_multi.py` | five machines, five programs, all in lockstep |
| `stt_iomux.v`, `stt_chip.v` | SPEC 11.1: pin assignment and the run flag |
| `tb/test_chip.py` | the TT boundary, configured through the pins |
| `stt_config.v` | the SPEC §2 configuration list as one serial chain |
| `stt_top.v` | the three wired together; the unit the testbench drives |
| `tb/lockstep.py` | benchmark capture and the configuration bit map |
| `tb/test_lockstep.py` | the cocotb test |
| `tb/steps.py` | the lockstep loop, shared by every suite |
| `tb/test_mutants.py` | mutation against the RTL |
| `tb/test_random.py`, `tb/randprog.py` | random 32-row programs |
| `tb/test_imem.py` | directed load-path test, all 32 addresses |
| `tb/coverage.py`, `tb/coverage_util.py` | encoding coverage |
| `tb/run_tests.py`, `run_mutants.py`, `run_random.py`, `run_imem.py` | runners that fail properly |
| `dump_programs.py` | encodes the six programs; used to check `RET` placement |

## Three things this work moved out of SPEC §16

Each was an open item that an implementer would have had to guess at. All three
are now normative, because the RTL pins them down and a suite tests them.

**`load` on an empty TX FIFO** (§9). The shift register holds and no byte is
popped. Found by mutation; §16.1 previously said "hardware behaviour is
undefined."

**What the input synchronizer holds after reset** (§8.3). Both stages reset to 0,
so inputs read low for two cycles, and a machine must not be enabled until its
inputs have been stable that long — which the load sequence guarantees. The model
gives itself zero lag on cycles 0 and 1, which hardware cannot; `tb/steps.py`
seeds the history so it lags the same way.

**`RET` on a false exit** (§5). `RET` applies to whichever exit the target field
feeds, which in `SKIP` is the false exit. `SttCore` resolved it only on the true
exit and raised `KeyError`; it now applies the same rule to either. No reference
program contains such a row, which is why it survived — it is reachable only from
a program nobody had written.
