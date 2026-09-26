# Inter-pin skew

`docs/SPEC.md` §16 named skew between a clock and its data — SCK/MOSI, SCL/SDA,
TCK/TMS — as the one open item where the answer could be bad rather than merely
absent. The Python models have no pin path: they say when a machine *decides*
to change a pin. This says when the pin changes.

**Result: every pair passes, with margins of two to three orders of
magnitude.** The numbers are **simulated** — SDF back-annotated gate-level
simulation of the signed-off netlist, both corners, every pair reported
separately (§2). An earlier revision of this report carried static STA
estimates because the gate-level simulation would not run; §5 records what the
simulation changed about those estimates, including one place where they were
optimistic.

## 1. Skew is not setup time

Stating this first because getting it wrong produced a false alarm during this
work. Skew between two pins does **not** compare against a device's setup
requirement. The program decides how far apart it drives the two signals; skew
then erodes that separation by a fraction of a nanosecond. What must clear the
requirement is

> setup at the pin = (separation the program creates) − (skew)

Comparing skew directly against t<sub>SU</sub> treats a small correction as if
it were the whole quantity, and turns a design with 300 ns of margin into an
apparent failure.

## 2. Measured skew, per pair

Simulated on the gate netlist from the signed-off run
`RUN_2026-09-18_00-21-34` — zero DRC, zero LVS errors, 0.02% IR drop — with
the SDF from that same run back-annotated onto it. `rtl2/tb/run_skew.py`; the
measurement window is 6000 clocks per program per corner.

Both pins of a pair are driven by registers on the same clock, so the skew
between them is the difference in their clock-to-output delays, and that delay
is what is actually sampled: for every pin transition, the time since the
preceding clock edge.

Skew is given as the median over the window and as the worst separation seen
between the two pins' delay ranges. Sign is (first pin − second pin), so a
positive number means the first pin moves later.

| pair | slow 1.08 V 125 °C | | typ 1.20 V 25 °C | |
|---|---|---|---|---|
| | median | worst | median | worst |
| SPI MOSI vs SCK | +643 ps | **+707 ps** | +405 ps | +451 ps |
| JTAG TDI vs TCK | +612 ps | **+707 ps** | +368 ps | +451 ps |
| USB D+ vs D− | +612 ps | **+707 ps** | +368 ps | +451 ps |
| I²C SDA vs SCL | +586 ps | **+681 ps** | +328 ps | +402 ps |
| JTAG TCK vs TMS | −266 ps | **−297 ps** | −154 ps | −191 ps |

**Worst skew anywhere: 0.707 ns, at the slow corner.** Every pair is worse at
the slow corner than at the typical one, which is what skew driven by cell and
net delay must do.

### The instrument is not reporting zeros

A skew measurement that comes back at zero is indistinguishable from a broken
instrument, and this project has already been caught by exactly that: Icarus
rounds annotated SDF delays to the cell's 1 ns time *unit*, which silently
quantized every delay and reported zero skew everywhere (`rtl2/sdf/README.md`,
and §4.3 entry 11 of the writeup). The measurement therefore carries its own
non-zero reference. The clock-to-output delay of each pin is a quantity that
cannot physically be zero, and it is sampled in the same run by the same code:

| | slow | typ |
|---|---|---|
| clock-to-output, across all pins | 2660–3367 ps | 1636–2087 ps |

These are not multiples of 1000 ps, they differ per pin, and they scale by
~1.6× between corners. `test_skew.py` asserts that no pin's measured delay is
zero, so a return to the quantizing failure fails the test rather than
reporting a clean result.

### Sample counts

Transitions observed per pin over the window, slow corner (typ is identical):
MOSI/TDI/D+ 108, 67, 109; SCK/TCK/D− 373, 374, 114; TMS 58; **SDA 2, SCL 2**.

The I²C figure rests on two transitions per pin and should be read as such.
Both fall in the START condition; the program then waits for an ACK that never
arrives, because this testbench attaches no I²C target. The quantity being
measured is a per-path clock-to-output delay rather than a distribution, so
two samples is less thin than it would be for a statistical claim — but it is
two samples, and a longer window does not add more.

SPI's CS reports no transitions at all. It is driven low when the first byte
arrives and stays low, because the host feed keeps the FIFO non-empty so the
program never reaches its `END` row. CS is not a clock/data pair and nothing
here depends on it.

## 3. Margin against the requirement

**SPI, against a real target device.** W25Q128JV serial flash, datasheet
Rev. C (2 March 2018), AC characteristics: Data In Setup Time
t<sub>DVCH</sub>/t<sub>DSU</sub> = **1 ns**, Data In Hold Time
t<sub>CHDX</sub>/t<sub>DH</sub> = **2 ns**.

The datasheet consulted is the **W25Q128JV-DTR** document (cover: *Publication
Release Date: March 02, 2018 - Revision C*), not the plain W25Q128JV one. The
two parts share the pinout and the 9Fh JEDEC response, but a DTR part is
specified for double-transfer-rate reads, and its AC table is the one these
setup and hold numbers come from. The margin here is ~332 ns against 1 ns, so
no plausible difference between the two AC tables changes the conclusion --
but the number's provenance is the DTR sheet, and a reader checking it against
the non-DTR sheet should know that before concluding the figures disagree.

The SPI program (`isa_bench/programs.py`, P = 16) drives MOSI on row `FALL2`,
one cycle after the `FALL` tick, and raises SCK on the *next* tick — a
separation of **15 cycles**. At ~45 MHz that is ~333 ns.

| | |
|---|---|
| separation the program creates | ~333 ns |
| worst skew | 0.707 ns |
| **setup at the pin** | **~332 ns** |
| required | 1 ns |
| **margin** | **~331 ns** |

Hold is larger still: MOSI next changes 17 cycles after SCK rises, ~377 ns
against a 2 ns requirement.

**I²C.** UM10204 Rev. 7.0 (1 October 2021) sets t<sub>SU;DAT</sub> ≥ 250 ns
Standard-mode and ≥ 100 ns Fast-mode. Measured skew 0.681 ns, against a program
separation likewise measured in hundreds of nanoseconds. Passes by more than
two orders of magnitude.

**JTAG.** IEEE 1149.1 fixes no absolute setup/hold; they are per-device. TCK
vs TMS skew of 0.297 ns and TCK vs TDI of 0.707 ns are small against any TAP
device's requirement, which is typically single-digit nanoseconds.

**USB low-speed.** D+ and D− are driven by one row through the pair slot and
are specified to move together, so their 0.707 ns is pure implementation skew.
USB 2.0 §7.1.x is not publicly retrievable, so no budget is quoted; for
context, a low-speed bit is 667 ns.

## 4. What this does not cover

Input timing. Everything here is output-to-output. Setup and hold on the pins
a machine *reads* — MISO, TDO, SDA when the target drives it — is a different
measurement and is **not done**. It is not closed with a caveat; it has not
been attempted. The margins are expected to be similarly large, because the
§8.3 synchronizer already imposes a two-cycle reaction delay, but expected is
not measured.

## 5. What simulation changed about the static estimate

The first version of this report estimated skew from OpenSTA reports, because
gate-level simulation had been brought up far enough to annotate SDF but the
machines never reached a state where they drive pins. That blocker turned out
to be a testbench bug rather than anything about the design (§4.3 entry 13 of
the writeup), and once fixed the simulation produced these numbers directly.

Keeping both is worth more than replacing one with the other, because the
comparison says how much a static estimate of this kind can be trusted:

| pair | static slow | **simulated slow** | static typ | **simulated typ** |
|---|---|---|---|---|
| SPI MOSI/SCK, JTAG TDI/TCK, USB D+/D− | 0.68 ns | **0.707 ns** | 1.88 ns | **0.451 ns** |
| I²C SDA/SCL | 1.00 ns | **0.681 ns** | 0.64 ns | **0.402 ns** |
| JTAG TCK/TMS | 0.13 ns | **0.297 ns** | 0.08 ns | **0.191 ns** |

Three things follow.

**The static estimate was right about the conclusion and unreliable about the
number.** At the slow corner it lands within a factor of ~2.3 — but it errs in
both directions, and on JTAG TCK/TMS it was *optimistic* by 2.3× (0.13 ns
estimated, 0.297 ns measured). An estimate that can be optimistic is not a
bound.

**Its typical-corner figure was backwards and that should have been caught
without simulating anything.** It reported 1.88 ns typical against 0.68 ns
slow for the headline pairs. Skew here is the difference of two delays, so it
must shrink when the corner gets faster; a typical corner worse than the slow
one describes nothing physical. The number was bolded as the headline result
and the inversion went unremarked. Simulation gives 0.451 ns typical against
0.707 ns slow, in the order it has to be.

**The conclusion never depended on the precision.** Every pair passes by two
to three orders of magnitude, so a factor of 2 or 4 in the skew figure does
not move the verdict. That is why the static version was worth publishing at
the time, and why the inverted number survived: nothing downstream was
sensitive enough to it for the error to show.
