# Gate-level simulation with SDF back-annotation

For measuring what the RTL testbenches cannot: when a **pin** changes, rather
than when a machine decides to change it. `docs/SPEC.md` §16 names inter-pin
skew as the one open item where the answer could be bad rather than merely
absent.

Inputs are the signed-off five-machine run — `floorplan/runs/RUN_2026-09-18_00-21-34`,
zero DRC, zero LVS errors, 0.02% IR drop — specifically `final/nl/tt_um_stt.nl.v`
and `final/sdf/<corner>/`.

## Three things that silently break this

Each was found by bisection, and each fails quietly rather than loudly.

**1. Icarus aborts on the top-level `(INSTANCE)` cell.** OpenSTA emits one CELL
with an empty instance name, holding every port-side INTERCONNECT. Icarus dies
with `NULL handle passed to vpi_scan`, and `(INSTANCE *)`, `(INSTANCE dut)` and
re-rooting the whole file all fail the same way.

`prep_sdf.py` drops that cell. **This is sound for output-pin measurements and
unsound in general**, so the reason is recorded rather than assumed: every
output-side entry in that block is 0.0000 ns — 24 of 24, verified at both
corners, because the output buffer drives the pad with no routing. What is lost
is the `clk` port to clock-buffer hop and the input-pin hops, which are
common-mode for output-to-output skew.

**2. Header triples with an empty typical value.** `(VOLTAGE 1.080::1.080)` and
the PROCESS/TEMPERATURE lines make Icarus report "Chosen value not defined" and
then abandon the file with a syntax error. They are informational; dropped.

**3. Icarus rounds delays to the cell's TIME UNIT, not its precision.** This is
the one that produces wrong numbers instead of no numbers. The PDK cells are
`1ns/10ps`, so the unit is 1 ns and every sub-nanosecond delay is destroyed:

| SDF delay | annotated as |
|---|---|
| 0.250 ns | **0** |
| 0.830 ns | **1 ns** |
| 2.500 ns | **3 ns** |

A design whose skew is tens of picoseconds then simulates as though it had
none, and nothing warns you. Symptom on the real design: all 134 clock leaves
reported an identical 1000 ps arrival, at both corners, which is impossible.
Giving the cells a finer timescale does not fix it — annotation then applies
nothing at all.

**The workaround is a scaled time domain.** `prep_sdf.py --scale=1000`
multiplies every delay so the values are integers in the 1 ns unit, and the
testbench clock is scaled by the same factor. Uniform scaling preserves every
timing relationship exactly; divide measured intervals by the factor to recover
real time. Verified exact at 0.017, 0.250, 0.830 and 2.500 ns.

With it, the same clock-leaf probe resolves real picoseconds:

| leaf | slow 1.08 V 125 °C | typ 1.20 V 25 °C |
|---|---|---|
| 101 | 813 ps | 509 ps |
| 35 | 856 ps | 537 ps |
| spread over 7 leaves | **43 ps** | **28 ps** |

## Running it

    python3 prep_sdf.py <in.sdf> <out.sdf> --scale=1000

then compile with `iverilog -g2012 -gspecify -ginterconnect`. Both flags are
required: without `-gspecify` there are no paths to annotate, and without
`-ginterconnect` Icarus refuses the INTERCONNECT entries with
`Could not find net`.

Icarus does not implement timing checks (`$setup`, `$hold`), so it will not
flag a setup violation. That is not what this is for — the numbers here are
measured edge separations, compared against each protocol's requirement
afterwards.
