# Inter-pin skew

`docs/SPEC.md` §16 named skew between a clock and its data — SCK/MOSI, SCL/SDA,
TCK/TMS — as the one open item where the answer could be bad rather than merely
absent, because the Python models have no pin path at all. They say when a
machine *decides* to change a pin. This says when the pin changes.

**These numbers are static, not simulated.** That is a real limitation and §4
below says exactly why.

## Method

From the signed-off five-machine run `RUN_2026-09-18_00-21-34` — zero DRC, zero
LVS errors, 0.02% IR drop — the gate netlist, its SPEF and its SDC, analysed by
the same OpenSTA that signed the design off (`rtl2/sdf/pin_skew_sta.tcl`).

Both pins of every pair are driven by registers on the same clock, so the skew
between them is the difference in their clock-to-output delays. Reporting the
delay per pin therefore gives every pair.

## Clock-to-output delay, per pin

| pin | slot | slow 1.08 V 125 °C | typ 1.20 V 25 °C |
|---|---|---|---|
| `uo_out[0]` | slot 0 | 1.7698 – 6.8265 ns | 1.1239 – 5.7624 ns |
| `uo_out[1]` | slot 1 | 1.6200 – 6.1442 ns | 1.0293 – 3.8840 ns |
| `uo_out[2]` | slot 2 | 1.6201 – 6.2772 ns | 1.0243 – 3.9660 ns |
| `uio_out[0]` | slot 0, open drain | 1.8679 – 5.0349 ns | 1.1810 – 3.1681 ns |
| `uio_out[1]` | slot 1, open drain | 1.8948 – 6.0304 ns | 1.1992 – 3.8123 ns |

## Skew per pair, and the margin

Worst case is the widest separation the envelope allows: earliest one pin
against latest the other.

| protocol | pair | slow | typ | requirement | margin (slow) |
|---|---|---|---|---|---|
| SPI mode 0 | SCK vs MOSI | **5.21 ns** | 4.73 ns | per-device, **not verified** | see §3 |
| I²C | SCL vs SDA | **4.16 ns** | 2.63 ns | t<sub>SU;DAT</sub> ≥ **250 ns** standard, **100 ns** fast | **+245.8 ns** / **+95.8 ns** |
| JTAG | TCK vs TMS | **4.66 ns** | 2.94 ns | per-device, **not verified** | see §3 |
| JTAG | TCK vs TDI | **5.21 ns** | 4.73 ns | per-device, **not verified** | see §3 |
| USB LS | D+ vs D− | **5.21 ns** | 4.73 ns | not publicly retrievable | see §3 |

**I²C passes with three orders of magnitude of margin** and is the one pair
with a requirement that could be checked: UM10204 Rev 7.0 (1 October 2021) sets
t<sub>SU;DAT</sub> at 250 ns minimum for Standard-mode and 100 ns for
Fast-mode. Against 4.16 ns of skew that is not close.

## 3. What could not be established

- **SPI and JTAG have no standard setup/hold.** Both are per-device. A
  representative datasheet was sought and the value could not be extracted:
  this machine has no PDF text tooling (`pdftotext`, `pymupdf`, `pdfminer` all
  absent) and the fetched files decompress to drawing operators. Rather than
  invent a threshold, the context: at ~45 MHz a SPI bit is 6.525 cycles ≈ 145
  ns, so 5.21 ns is **3.6% of a bit time**. Many SPI flash parts specify data
  setup in the 2–5 ns range, which 5.21 ns would **not** clear — so this is the
  pair to check against the actual target device before trusting it.
- **USB 2.0 §7.1.x is not publicly retrievable** (usb.org, not open). D+ and D−
  are driven by one row through the pair slot and are specified to move
  together, so the 5.21 ns is pure implementation skew with no budget to
  compare against here.

## 4. Why these are an upper bound, and static

**The envelope spans configurations, not transitions.** Each pin's min and max
are the fastest and slowest *paths* to it, and a pin is fed through the iomux,
which selects among 15 drivers of differing depth (§11.1). For a **fixed** pin
assignment only one driver is live, so the real skew for a given configuration
is smaller than the table — possibly much smaller. The numbers are a bound that
no configuration exceeds, not a prediction for any one of them.

**They are static.** Gate-level simulation was brought up far enough to
annotate SDF and resolve real picoseconds on the clock tree — 813–856 ps at the
slow corner, 509–537 ps typ, against a flat 0 ps unannotated — but the machines
never reached a state where they drive pins, so no waveform was obtained.
`rtl2/sdf/README.md` records that work and the three silent Icarus failures it
had to get past, one of which quantized every delay to 1 ns and would have
reported exactly zero skew everywhere.

**What would settle it.** A simulation that gets the machines running would
give per-transition skew for the actual configuration rather than a bound, and
would show whether the SPI pair is genuinely near a device limit.
