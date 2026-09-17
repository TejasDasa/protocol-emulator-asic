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

# one program
/home/tejas/venv-cocotb/bin/python tb/run_tests.py i2c

# synthesis and the latch gate
bash rtl2/run_synth.sh
```

`make check` runs the two gates that need no simulator: the generated-header
drift check and the latch gate. `make rtl2-test` runs the lockstep suite and
needs `COCOTB_PY` pointed at the cocotb venv.

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
