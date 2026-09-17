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

Out of scope for this pass, and absent rather than half-built: multiple state
machines, `stt_iomux` and the pin-assignment chain, `stt_hostbuf`, the `run`
flag (SPEC §11.1), `crc_lfsr16`, `bit_stuffer`, and the reserved codes of SPEC
§9. Those come after one machine is proven.

The imem is a **behavioural array**, not two `CFGMEM_IHP16` macros. The load
path around it is not behavioural — the staging register, bit counter and write
pointer are exactly the logic SPEC §12 says the tiles do not provide, so
swapping the array for the macros must not change behaviour. The read is
asynchronous, which SPEC §12 requires and the macro's own liberty confirms: no
`CLK` pin, no `ff()` or `latch()` groups, all 224 timing arcs
`timing_type : combinational`, worst address-to-data 1.994 ns.

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

# synthesis and the latch gate
bash rtl2/run_synth.sh
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
| `stt_config.v` | the SPEC §2 configuration list as one serial chain |
| `stt_top.v` | the three wired together; the unit the testbench drives |
| `tb/lockstep.py` | benchmark capture and the configuration bit map |
| `tb/test_lockstep.py` | the cocotb test |
| `tb/run_tests.py` | runs all six and fails properly |
| `dump_programs.py` | encodes the six programs; used to check `RET` placement |

## One thing the spec leaves open, and why it does not bite

SPEC §5 says target 255 means return. `SttCore` only resolves `ret` on the
**true** exit, but in `SKIP` mode the target field feeds the **false** exit, so a
`SKIP` row with target 255 would be a spec/model disagreement — the model would
raise `KeyError`. This RTL implements the spec's general rule: `RET` applies to
whichever exit the target field feeds. `dump_programs.py` confirms **no row in
any of the six reference programs puts 255 on a false exit**, so the case is
unreachable and the lockstep result is unaffected. Worth knowing before someone
writes a seventh program.
