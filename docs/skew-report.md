# Inter-pin skew

`docs/SPEC.md` §16 named skew between a clock and its data — SCK/MOSI, SCL/SDA,
TCK/TMS — as the one open item where the answer could be bad rather than merely
absent. The Python models have no pin path: they say when a machine *decides*
to change a pin. This says when the pin changes.

**Result: every pair passes, with margins of two to three orders of magnitude.**
The numbers are static rather than simulated (§5).

## 1. Skew is not setup time

Stating this first because getting it wrong produced a false alarm during this
work. Skew between two pins does **not** compare against a device's setup
requirement. The program decides how far apart it drives the two signals; skew
then erodes that separation by a few nanoseconds. What must clear the
requirement is

> setup at the pin = (separation the program creates) − (skew)

Comparing skew directly against t<sub>SU</sub> treats a small correction as if
it were the whole quantity, and turns a design with 300 ns of margin into an
apparent failure.

## 2. Measured skew, per pair

From the signed-off run `RUN_2026-09-18_00-21-34` — zero DRC, zero LVS errors,
0.02% IR drop — analysed by the OpenSTA that signed it off
(`rtl2/sdf/pin_skew_sta.tcl`). Both pins of a pair are driven by registers on
the same clock, so their skew is the difference in clock-to-output delay.

| pair | slow 1.08 V 125 °C | typ 1.20 V 25 °C |
|---|---|---|
| SPI SCK vs MOSI | 0.68 ns | **1.88 ns** |
| JTAG TCK vs TDI | 0.68 ns | **1.88 ns** |
| USB D+ vs D− | 0.68 ns | **1.88 ns** |
| I²C SCL vs SDA | **1.00 ns** | 0.64 ns |
| JTAG TCK vs TMS | 0.13 ns | 0.08 ns |

**Why not the larger figure.** Each pin's clock-to-output delay is a range
(1.62–6.14 ns for `uo_out[1]` at the slow corner) because a pin is fed through
the iomux, which selects among 15 drivers of differing depth (§11.1). Pairing
one pin's *minimum* against the other's *maximum* gives up to 5.21 ns, but
those are different iomux routes and cannot both be live in one configuration
— that bound describes no real chip. The table compares like with like, fast
path against fast path and slow against slow, which is the right estimate for
a fixed pin assignment where both slots take structurally similar routes.

## 3. Margin against the requirement

**SPI, against a real target device.** W25Q128JV serial flash, datasheet
Rev. C (27 March 2018), AC characteristics: Data In Setup Time
t<sub>DVCH</sub>/t<sub>DSU</sub> = **1 ns**, Data In Hold Time
t<sub>CHDX</sub>/t<sub>DH</sub> = **2 ns**.

The SPI program (`isa_bench/programs.py`, P = 16) drives MOSI on row `FALL2`,
one cycle after the `FALL` tick, and raises SCK on the *next* tick — a
separation of **15 cycles**. At ~45 MHz that is ~333 ns.

| | |
|---|---|
| separation the program creates | ~333 ns |
| worst skew | 1.88 ns |
| **setup at the pin** | **~331 ns** |
| required | 1 ns |
| **margin** | **~330 ns** |

Hold is larger still: MOSI next changes 17 cycles after SCK rises, ~377 ns
against a 2 ns requirement.

**I²C.** UM10204 Rev. 7.0 (1 October 2021) sets t<sub>SU;DAT</sub> ≥ 250 ns
Standard-mode and ≥ 100 ns Fast-mode. Measured skew 1.00 ns, against a program
separation likewise measured in hundreds of nanoseconds. Passes by more than
two orders of magnitude.

**JTAG.** IEEE 1149.1 fixes no absolute setup/hold; they are per-device. TCK
vs TMS skew of 0.13 ns and TCK vs TDI of 0.68 ns are small against any TAP
device's requirement, which is typically single-digit nanoseconds.

**USB low-speed.** D+ and D− are driven by one row through the pair slot and
are specified to move together, so their 1.88 ns is pure implementation skew.
USB 2.0 §7.1.x is not publicly retrievable, so no budget is quoted; for
context, a low-speed bit is 667 ns.

## 4. What this does not cover

Input timing. Everything here is output-to-output. Setup and hold on the pins
a machine *reads* — MISO, TDO, SDA when the target drives it — is a different
measurement and is not done.

## 5. Static, not simulated

Gate-level simulation was brought up far enough to annotate SDF and resolve
real picoseconds on the clock tree — 813–856 ps at the slow corner against a
flat 0 ps unannotated — but the machines never reached a state where they drive
pins, so no waveform was obtained. `rtl2/sdf/README.md` records that work and
the three silent Icarus failures it had to get past, one of which quantized
every delay to 1 ns and would have reported exactly zero skew everywhere.

A simulated number would improve on this in one specific way: it would measure
the live path for one configuration directly, rather than estimating it by
comparing like-for-like paths from a static envelope.
