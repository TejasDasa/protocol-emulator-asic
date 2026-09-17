# Row format: recommendation

**This is a recommendation, not a decision.** It is handed back for the freeze.

Two configurations are live. Every number below is measured on IHP
`sg13cmos5l` through the flow in this repository; `docs/area-study.md` §0 states
the three area bases and the four rules for comparing them, and every row here
names its basis.

| | **C** | **D** |
|---|---|---|
| row width | 21 bits | 32 bits |
| action encoding | 5-bit index into a 32-entry palette | 13-bit action group, inline |
| instruction memory | 2x `CFGMEM_IHP16` | 2x `CFGMEM_IHP16` |
| palette hardware | 24-entry ROM + 8 loadable (104 flops) | none |

---

## 1. Side by side

Both use the same two CFGMEM tiles, so the storage cost is identical and the
difference is entirely in the logic around it.

| | A: 21-bit, flops | B: 32-bit, flops | **C: 21-bit, CFGMEM** | **D: 32-bit, CFGMEM** |
|---|---|---|---|---|
| per-SM soft area (cell) | 78,960.32 | 107,794.76 | **25,410.23** | **18,252.56** |
| reserved macro area per SM | 0 | 0 | 57,589.06 | 57,589.06 |
| **SMs @ 50%** | 5.50 | 4.03 | **8.01** | **9.24** |
| **SMs @ 60%** (TT default) | 6.64 | 4.87 | **8.75** | **9.94** |

> These SM counts are **area** results and are superseded as build targets by
> §5.5: a 6-SM floorplan fails global routing at 37% average routing usage, so
> routing resource binds before area does. The comparison between the columns is
> unaffected — every column is computed the same way — but the absolute numbers
> are upper bounds, not plans. The target is 5-6 machines.
| palette holds? | yes, 32 entries | yes | yes | n/a — no palette |

A and B are shown because B is the trap: **32-bit rows without CFGMEM are worse
than doing nothing**, 4 SMs against the 6 of today's baseline. Row width and
memory technology are one decision, not two. Widening 21 → 32 costs **+51.4%**
on the imem with flops and **+1.9%** with CFGMEM, because storage is two macros
at any width up to 32.

### Program bits, six benchmarks

UART TX, UART RX, SPI mode 0, I²C master, USB LS token TX, JTAG. **Six, not
seven — CAN was not completed** (§6). CAN has since been written (24
rows), but the format comparison below is deliberately left over the original
six: that is the set the encoding freeze covers, and re-running it with a
seventh program would move the totals without changing the conclusion.

| format | total program bits |
|---|---|
| 21-bit, palette built in-sample | 1,829 |
| 21-bit, palette leave-one-out | 1,868 |
| 32-bit, inline | 2,688 |

D costs **+44%** in program bits. Under CFGMEM that buys nothing and costs
nothing: a row bit is **79.34 µm²** with tiled CFGMEM against **2,617.72 µm²**
with flops, both measured. The bits are close to free; the palette hardware
they replace is not.

---

## 2. Recommendation: D

**Not because of the area.** D beats C by **one SM** (9.94 vs 8.75 at 60%), and
one SM is a thin margin to restructure a row format for. The case is:

### 2.1 D is a strict superset, not a trade

A palette *entry* is itself a 13-bit grouped code — `rowenc.GROUP_BITS == 13`,
`hybridsweep.ENTRY_BITS == 13`, and `scripts/gen_palette.py::entry_bits()`
calls `encode_actions_grouped()` and packs exactly `GROUP_BITS`. Verified in the
generator, not inferred from constants.

So the palette can only ever hold action sets drawn from the space the inline
field spans in full:

| | distinct action sets |
|---|---|
| palette | **32** |
| inline 13-bit group | **1,800** |

The palette is a 32-entry cache of D's space. Inlining does not narrow the
expressible set; it removes a lookup table whose only job was compressing 13
bits into 5. **56x more reachable, and nothing reachable under C that is not
reachable under D.**

### 2.2 Post-fab, D has *fewer* dead ends — the competition's central requirement

The announcement's requirement is that the chip stay reprogrammable for new
protocols after fabrication. Deleting the loadable palette looks like deleting
the mechanism for that. It is the opposite.

For an action set not among the 24 frozen in silicon:

* **Under C**: spend one of **8** loadable slots. Need a ninth and the rows
  split, costing rows and cycles. USB already uses **7 of 8** in leave-one-out.
* **Under D**: any of the 1,800 encodes directly in the row. There are no slots
  to exhaust.

Both handle the 1.37% of all 2¹⁷ action subsets that the *grouping* forbids the
same way — by splitting rows — because that limit is the group structure, which
C and D share. **There is no case where C can express a row that D cannot.**

### 2.3 D's programs are self-contained

C's 8 loadable entries are per-program state that must be shifted in at
startup, before the state machine can run. That is a host-interface cost and a
reconfiguration-latency cost. D's programs carry their actions in the rows; a
reconfiguration is a row load and nothing else. Not an area argument, and it
does not change the ranking, but it is real.

---

## 3. What would have to be true for C to win

Stated plainly, because these are the conditions to test before freezing:

1. **CFGMEM cannot be integrated.** If the macros cannot be placed and powered
   on a Tiny Tapeout tile, both C and D collapse to A, and 21-bit rows win by
   default — B is two SMs worse than doing nothing. This is the live risk
   (§5.1); it is an integration risk, not a build risk, because the macro
   *builds* (§4).
2. **A protocol needs more than 32 rows.** Then the imem goes to four tiles and
   **D falls to 6.03 SMs — level with the flop baseline A** (§5.2). At that
   point the whole CFGMEM case evaporates and row width should be reconsidered
   from scratch.
3. **The 13-bit group turns out to be the wrong grouping.** C and D share it,
   so this does not favour C over D — but if the mutual exclusions inside a
   group are wrong for a protocol we have not written, that is a reason to
   revisit the group structure *before* freezing either option.
4. **Startup latency is free and area is not.** If the host can afford to shift
   palette entries but cannot afford 8,030 µm² per SM, C's smaller row wins. At
   6x4 with 8-9 SMs available either way, this does not currently bind.

---

## 4. What is measured, and how

| claim | evidence |
|---|---|
| macro builds on cmos5l | `dffram.py -b cfgmem_ihp 16x32` through LibreLane 3.1.0.dev3, exit 0 |
| macro area | 1029 logic cells = 21,525.44 µm² (cell); LEF 331.2 x 86.94 = 28,794.53 µm² (placed); 74.8% utilization |
| our build == prism's | identical on every figure above |
| retained glue | `stt_imem_cfgmem`: 31 flops, 3,030.05 µm² at 32x21 |
| palette removal | `stt_palette` INLINE_ENTRY: 8,544.09 µm² / 104 flops → 235.87 µm² / 0 flops |
| SM budget | `area(N) = 17,000.50 + N x 78,960.32`, R² = 0.999989 over NSM 1..5 |
| die and core area | template hardened at `tiles: "6x4"`, `design__core__area` = 902,417 µm², DRC clean |
| all benchmarks pass | 15 runs, timing checked, mutation score 89.1% |

Reproduce: `make area && make check`, and `cd isa_bench && python3 widthsweep.py`.

---

## 5. The thin margins, stated rather than buried

These are what a reader should probe first.

### 5.1 D beats C by one SM

9.94 vs 8.75 at 60% density. The area case for D is weak; the expressiveness
and post-fab cases carry it. If you disagree with §2.1–2.3, the area alone does
not justify restructuring the row format.

**CFGMEM integration is now demonstrated** (`pdn_test/`): one SM with two macros
hardens through the full flow with 0 power-grid violations, 0 DRC, 0 antenna
violations, and LVS reporting "Circuits match uniquely". It requires a
non-default flow -- the `ExtendPowerStripes` plugin, a stripe pitch of 44.96
matched to the macro, and macro placement on that grid -- but it works, and the
recipe is recorded. What remains unpriced is the *multi-SM* floorplan (§5.4).

### 5.2 JTAG sits at 25 of 32 rows — 78% full

The constraint is the **encoding, not the memory**: `single5` allows one pin
write per row, and a TAP walk needs TMS, TDI and TCK. Bit-loop protocols are
cheap in rows; state-machine protocols are not.

A protocol needing a 33rd row does not cost one more row. It costs a **third
and fourth CFGMEM tile**, because depth quantises at 16:

| | reserved macro area per SM | SMs @ 60% |
|---|---|---|
| 32 rows, 2 tiles | 57,589.06 | **9.94** |
| 64 rows, 4 tiles | 115,178.12 | **6.03** |

**Going over 32 rows erases the entire CFGMEM advantage** — 6.03 is level with
the flop baseline. The 32-row budget is not merely tight; it is load-bearing for
this recommendation. That argues for spending some of D's 3 spare bits, or
future ISA work, on making state-machine protocols cheaper in rows.

### 5.3 Timing: the model cannot see the risk that matters

An earlier revision of this document reported "timing margin is 0% on SPI SCK
and I²C SCL low" as an alarming finding. **That was wrong on both counts** and
is corrected here (§8, correction 4).

The 0% was an artifact of anchoring: the nominal was set to exactly what the
program produces. Sweeping P shows every phase is an exact function of P — SCK
and SCL-low are precisely `P/2`, SCL-high precisely `P/4 + 2` — so asking "how
much longer than `P/2` is it" could only answer zero.

The attached alarm — that pin-path delay "comes straight out of the phase" — was
also wrong. Phase length is a count of core clock cycles between two toggles,
integral and exact. A pad delay `d` shifts every edge by `d`, so the phase
measures `(t2 + d) − (t1 + d)` and is unchanged. Pad delay moves the waveform; it
does not compress it.

**The real timing risks are outside this model entirely:**

* **Inter-pin skew** — differing pad and routing delay between SCK and MOSI, or
  SCL and SDA, shifting the data-to-clock relationship. This is the actual
  failure mode and it needs STA with SDF back-annotation.
* **Absolute time against spec minimums** — I²C standard mode wants
  `t_HIGH ≥ 4.0 µs`, `t_LOW ≥ 4.7 µs`. Whether the programmed cycle counts clear
  that depends on the core clock. The duty cycle is low-heavy (~33%), which is
  the spec-friendly direction.

So timing is neither reassuring nor alarming on this evidence — it is
**unmeasured**, and it belongs to STA. That is already §7 item 5, and it is the
most important thing this study does *not* establish.

---

### 5.4 Macro placement is quantised — priced, and it does not cost SMs

The PDN work (§5.1, `pdn_test/`) turned up a constraint none of the area
arithmetic accounted for: **CFGMEM macros must sit on the 44.96 µm stripe grid
at a fixed offset**, or their Metal4 power pins never meet a stripe. At 9 SMs
that is 18 macros all needing aligned positions. The 9.94 figure assumed macros
pack freely. They do not, so it was worth pricing before building on it.

**It prices out favourably**, for three reasons that are geometry, not luck:

* **y is not quantised at all.** The macro is 86.94 µm = exactly 23 standard-cell
  rows, so macros stack vertically with zero waste.
* **The x gap is usable, not lost.** A macro is 331.20 µm = 7.367 pitches, so the
  next legal origin is 8 pitches = 359.68 µm, leaving a 28.48 µm gap between
  adjacent macro columns. That gap is **59 standard-cell sites wide** — narrow,
  but it hosts logic rather than being wasted.
* **Grid capacity exceeds demand.** Three macro columns fit across the core
  (a fourth would end at 1410.24 > 1283.52) and eight macros fit per column, so
  the grid holds **24 macros = 12 SMs**. We need 18.

Floorplan for 9 SMs, three columns of six:

| region | size | µm² |
|---|---|---|
| above each column | 3 x 331.20 x 181.44 | 180,279 |
| gaps between columns | 2 x 28.48 x 703.08 | 40,047 |
| strip right of the macros | 232.96 x 703.08 | **163,790** (largest contiguous) |
| **total usable for logic** | | **384,116** |
| logic needed (9 SMs @ 60%) | | 301,491 |
| **slack** | | **+82,625 (+27.4%)** |

At 10 SMs it does not fit (−1.6%), which is consistent with the §1 budget
independently putting the limit at 9.94.

> **What this still does not establish.** This is an area-and-shape check, not a
> placement run. It says the logic area exists and sits in reasonably shaped
> regions; it does not show that *each SM's* logic can sit near *its own* two
> macros, which is what wirelength and timing will care about. A 59-site gap is
> placeable but awkward. **Treat 9 SMs as an upper bound until a multi-SM
> floorplan has actually been run** — it now has been, and the bound does not
> hold: see §5.5. Everything in this subsection stands as an area-and-shape
> result and none of it was ever a routability claim, which is the natural second half of the
> §5.1 experiment: get the PDN recipe working on one SM, then immediately try
> the multi-SM floorplan with aligned macros.

### 5.5 The multi-SM floorplan has now been run, and 9 SMs is falsified

**2026-09-16.** §5.4 closed by saying "treat 9 SMs as an upper bound until a
multi-SM floorplan has actually been run." It has been run (`floorplan/`), and
the upper bound does not hold. **Routing resource binds well before area does,
and none of the arithmetic in this document counts routing resource.**

The first 6-SM run, interleaved macros at the Tiny Tapeout target density,
**failed global routing**: `GRT-0116, Global routing finished with congestion`.
What makes that decisive is not the failure but the numbers underneath it:

| layer | resource | demand | usage |
|---|---|---|---|
| Metal2 | 98,472 | 40,839 | 41.5% |
| Metal3 | 144,521 | 75,092 | 52.0% |
| Metal4 | 95,853 | 10,463 | **10.9%** |
| **total** | **338,846** | **126,394** | **37.3%** |

Total overflow 104 GCells; 1,252,555 µm of wirelength over 14,206 nets. A design
does not fail routing at 37% average usage because it ran out of resource. It
fails because the resource is in the wrong place.

**The structural reason, which no parameter fixes.** The CFGMEM macro blocks
Metal1–Metal3 under its entire footprint, and Metal4 is the PDN's vertical
layer. Above a macro there is therefore effectively nowhere to route — which is
why Metal4 sits at 10.9% while Metal3 is at 52%. Twelve macros put 28,188
blockages on the die. Interleaving the macro rows through the core, so each
machine's logic sits beside its own memory, forces every vertical signal to
cross four macro shadows. That trade — locality against routability — is not
visible in an area budget at all.

**What this does to the SM count.** At 6 machines the design measures 9,898
instances: 9,886 standard cells at 178,987 µm² plus 12 macros at 345,534 µm²,
which is 58.1% of the 902,417 µm² core. At 9 machines the macros **alone** are
18 × 28,794.53 = 518,302 µm², or **57.4% of the core before a single gate of
logic is placed** — essentially the entire budget the 6-machine design used in
total, and that design did not route. The 9.94 figure in §1 and the +27.4%
slack in §5.4 are area-and-shape results and remain correct as area-and-shape
results. They were never a routability claim, and they should not be read as
one.

**This does not reopen the freeze.** D beats C at every machine count, for the
reasons in §2, and none of them are area arguments. What changes is not the row
format but what we plan to build: **the target is now 5 state machines, not 9.**
The sweep settled it: 6 machines could not be made to route at any placement
density or macro grouping, and 5 places and routes with zero router DRC errors.
See `floorplan/README.md` for the eight-point sweep and the signoff run.

**What is still true, and it is more mixed than the pre-route number suggested.**
The same run produced the first static timing analysis this project has ever
had — §7 item 5 called its absence "the largest verification gap in the study."
The pre-place-and-route numbers looked good. The post-route numbers, measured on
the routed 5-machine design with extracted parasitics, do not:

| corner | pre-PnR setup | **post-PnR setup** | post-PnR hold |
|---|---|---|---|
| slow, 1.08 V, 125 °C | +1.596 MET | **−1.266 VIOLATED** | +0.506 MET |
| typ, 1.20 V, 25 °C | +6.035 MET | +3.641 MET | +0.202 MET |
| fast, 1.32 V, −40 °C | +8.695 MET | +6.483 MET | +0.016 MET |

Real parasitics cost 2.9 ns at the slow corner, turning an 8% margin into a 6%
deficit. **Worst-case frequency is about 47 MHz, not 50.** Hold is met at every
corner. The verification gap is closed in the sense that the number now exists;
what it says is that 50 MHz does not currently close worst-case, with 115
max-fanout, 4 max-slew and 1 max-cap violations outstanding — several of them
artifacts of `obs`, an observability port that XOR-reduces signals from every
machine into one pin, and of a `clk` net with 1,844 terminals. Neither belongs
in a design meant to be taped out. Whether the target should be 50 MHz or
47 MHz is an RTL-phase decision, not a floorplan one, and configuration D is
different logic with different critical paths.

#### 5.5.1 Why the ceiling is routing, quantified

Two measurements, both from the sweep in `floorplan/`, both surprising enough to
be worth stating on their own.

**Adding core area reduced usable routing resource.** The first 6-machine run
used LibreLane's default IO margin multipliers (`BOTTOM/TOP_MARGIN_MULT` 4,
`LEFT/RIGHT` 12) instead of the hardened template's 1 and 6, which inset the core
to 1277.76 x 680.40 = 869,369 µm². Correcting it restored the full
1283.52 x 703.08 = 902,417 µm², **+3.8% of core** — and total routing resource
*fell*:

| layer | 869,369 µm² core | 902,417 µm² core | change |
|---|---|---|---|
| Metal2 | 98,472 | 98,138 | −0.3% |
| Metal3 | 144,521 | 144,453 | −0.0% |
| Metal4 | 95,853 | **87,110** | **−9.1%** |
| total | 338,846 | 329,701 | −2.7% |

The entire loss is Metal4, with Metal2 and Metal3 flat to within 0.3%. Metal4 is
the PDN's vertical layer, so a taller core lengthens every power stripe and a
wider one adds stripes; with `PDN_MULTILAYER` off, that whole cost lands on the
single layer that is also the only layer able to cross a macro. **On this PDK
under a single-layer PDN, enlarging the core can shrink the signal routing
budget.** The core figure is still the right denominator for *area*, and 902,417
is the correct one — it just does not predict routing.

**Macros cost more routing resource than they cost area.** Same margins, 12
macros versus 10:

| layer | 12 macros | 10 macros | change |
|---|---|---|---|
| Metal2 | 98,138 | 107,740 | +9.8% |
| Metal3 | 144,453 | 152,816 | +5.8% |
| Metal4 | 87,110 | 95,426 | +9.5% |
| total | 329,701 | 355,982 | **+8.0%** |

Two macros are 57,589.06 µm², **6.4% of the core**, but they account for **7.4%
of total routing resource** — a 1.15x multiplier, and it applies on every layer,
not just the ones they physically block. That multiplier is the whole reason the
area budget overshot: §1 solved `N x 57,589.06 + logic/0.60 <= 902,417` and got
9.94, treating a macro as nothing but its footprint. A macro is its footprint
*plus* a Metal1-3 blockage over that footprint *plus* its share of a Metal4 layer
it cannot use.

**For anyone else building macro-heavy designs on this PDK:** area arithmetic
will overestimate how many macros fit, and the error is not small. Ours put the
ceiling at 9.94 state machines. Measured, it binds at 5 — **roughly half**. The
single-layer PDN is what makes it severe: with only Metal2-Metal4 for signals,
one of those three reserved for power, and Metal1-3 blocked under every macro,
a macro's shadow has no routing layer at all.

## 6. CRC and bit stuffer: keep both, on capability

The old argument — "the CRC costs 1.28 row bits, so it pays for itself if it
saves two" — **does not survive**. Under CFGMEM a row bit is 79.34 µm², so the
CRC is 42.2 row bits and the stuffer 13.6. Nothing can pay for itself in row
bits when row bits are nearly free. The right question is capability against the
**17,000.50 µm² fixed budget**, which both are charged to once, not per SM.

* **CRC/LFSR, 3,350.59 µm², 19.7% of fixed.** 16-bit programmable polynomial,
  both bit orders. USB, CAN, Ethernet, SD and 1-Wire all require a CRC and none
  can compute one in-loop at line rate. Without it those protocols are not
  merely expensive, they are out of reach.
* **Bit stuffer, 1,079.57 µm², 6.4% of fixed.** The test set is `{always, c2z,
  cz, fifo, in0h, in0l, in1h, in1l, srbit, tmr}` — there is **no "same as the
  previous bit" test**, so in-loop run detection needs separate 1-run and 0-run
  paths, each with its own counter. That is a row-count cost on exactly the
  state-machine-shaped protocols that §5.2 says are already the tight case.

Together 4,430.16 µm², 26.1% of the fixed budget, against 5-6 SMs of per-SM
area. **Recommend keeping both.**

### 6.1 The capability argument had no encoding path — it does now

**2026-09-16.** The argument above justified 4,430.16 µm² of fixed budget on
what the two units make possible, but at the time nothing in the row format
reached them. In `rtl/stt_chip.v` their control inputs are tied to raw
`ui_in`/`uio_in` bits so that the area harness's "every input driven" rule is
satisfied; that is a measurement scaffold, not an architecture. Keeping them on
capability grounds while no program could invoke them would have meant taping
out logic no program can reach.

Two of the four units named elsewhere in this document were never affected.
`stt_hostbuf` is driven by `tx_pop`/`rx_push`/`tx_ne`, which are the `load` and
`push` actions and the `fifo` test; `stt_iomux` is driven by `sm_out`/`sm_oe`/
`sm_in`, which are every pin op and the `in0`/`in1` tests. Both are reached
through fields that already exist. The per-SM CRC5 is also reachable and used:
the USB program issues `crcrst` once, `loadcrc` once and `crcstep` three times.
The gap was the two *wider* units only.

That amendment is now implemented; `isa_bench/freeze_check.py` guards it. Of 12 control inputs across the two
modules, **7 are per-program constants** the existing serial configuration chain
carries and **5 need a row to say them**. All five fit in codes that were already
free — `test` 10→11 of 16, `pin_op` 7→8 of 8, `act_xx` 5→8 of 8 — so the
amendment **costs zero row bits**, and because every code is appended rather
than inserted, no existing code index moves. That claim is checked rather than
asserted: every reference program is re-encoded with and without the amendment
and the packed words compared, all identical, all still 32 bits. `make
check-freeze` fails if that stops being true.

**The freeze on D survives intact.** The residual cost is mutual exclusion, not
space: `act_xx` and `pin_op` are now full, so a row wanting `crc16step`
alongside `call`, `crcrst` or `crcstep` must split into two. `act_xx` is already
non-zero on 8 of 59 reference rows, all in USB. The codes are recorded in
`spec/isa.json` and specified in `docs/SPEC.md` §9. They are now **implemented**
— in `isa_bench/stt.py`, in `rtl2/`, and exercised as a protocol by the CAN
transmitter of `isa_bench/can_prog.py` — and `spec/conformance.py` checks them
alongside every other code.

One thing turned out differently from the pricing above: both units are
**per state machine, not shared**. The blocks in `rtl/` were written as single
instances and the configuration C floorplan instantiates one of each for the
whole chip, but §8.1 forbids that — they hold per-stream state, sharing needs
arbitration, and arbitration means a machine waits, which §8.1 does not allow.
That multiplies their cost by the machine count, and is most of why format D
synthesises **larger** than C at five machines rather than smaller.

---

## 7. What the measurements cannot settle

1. **The multi-SM floorplan.** SETTLED, and against us: see §5.5. Twelve
   macros and six machines fail global routing at 37% average routing usage,
   because the macros block Metal1-3 and Metal4 is the PDN layer. The target is
   now 5-6 machines, not 9. What remains open is which of 5 or 6 closes, and
   whether a grouped-macro floorplan beats an interleaved one.
2. **Whether 32 rows holds for protocols nobody has written.** JTAG is at 78%
   and CAN at 75%, and they are the only state-machine protocols tested.
   Ethernet and SD are unwritten. The ceiling has now been seen to bind once:
   the software-stuffing CAN variant needs 54 rows and cannot be built.
3. **CAN.** SETTLED. `isa_bench/can_prog.py` transmits a 2.0A base frame in
   **24 of 32 rows**, verified against `CanRx` in `isa_bench/jtag_can.py` and
   in cycle-exact lockstep with `rtl2`. It needs both SPEC §9 wider units and
   neither is a convenience: the legacy `crc` unit is 5 bits with a fixed
   polynomial, so CRC-15 is unreachable at any row count, and software bit
   stuffing costs 54 rows (`isa_bench/can_soft.py`) and still cannot cover the
   CRC field, because no test can see the bit `crcb` emits. Measured cost of
   the two units: **+53 flops per machine** (core 62→84, config 69→100) and
   **+6.6% cell area** on `stt_top`.
4. **Post-P&R area for our own design.** Every per-SM figure is `stat` cell area
   or a density projection. No routing, no clock tree, no congestion. The
   template harden calibrates the die, not our logic.
5. **Timing, at every level.** PARTLY SETTLED: §5.5 has the first STA, and 50 MHz
   MISSES at the slow corner post-route by -1.266 ns (~47 MHz worst case), though
   it met pre-route. Still no STA on `stt_core`
   alone for the frozen format D, and no SDF-back-annotated simulation on anything.
   §5.3 explains why the cycle-accurate model cannot speak to pin timing at all: it has no pin path.
   Inter-pin skew between SCK/MOSI and SCL/SDA is the failure mode that matters
   and it is entirely unmeasured. That, not the frequency, is now **the largest
   verification gap in the study**.
6. **Whether the 13-bit grouping is right.** C and D share it. The 1.37%
   reachability of all action subsets is a design choice nobody has re-examined
   since it was set.
7. **Whether the reserved codes are the right five.** §6.1 shows five codes
   suffice and that they fit for free, which is what the freeze needed. It does
   not show they are sufficient *in practice*: no program uses them, so the
   split-row cost of `act_xx` being full is estimated from where existing rows
   already spend that field (8 of 59, all USB), not measured on a program that
   actually stuffs bits or runs a CRC-16.

---

## 8. Correction history

Four derived conclusions in this study were wrong, and each was caught by
measuring rather than arguing. They are kept here deliberately: for a
competition that says verification is what it judges, a decision document that
shows its own errors being found is worth more than a clean one.

| claim | corrected to | how it was caught |
|---|---|---|
| tiling CFGMEM saves ~36,400 µm²/SM (39%) | 10,318 (18.3%) cell, 31,359 (33.4%) placed | building `stt_imem_cfgmem` and measuring the glue the macro does not supply |
| moving the imem to DFFRAM: 6 SMs → ~11 | 6 → 8 | same |
| "8 injected-bug tests, all caught" | never existed | searching the repository for it |
| "timing margin is 0% on SPI SCK and I²C SCL low" | an anchoring artifact, and the alarm attached to it was mechanically wrong (§5.3) | sweeping P and finding every phase exact |

**The pattern in the first two is one failure mode**: comparing two correct
measurements on mismatched bases — a module against a bare macro, `stat` against
a LEF footprint. Neither was a wrong measurement. §0 of `docs/area-study.md` now
carries the like-for-like check as a required step with four rules, because
review caught it twice and that is twice too many.

**The third is worse and different.** It was a prose assertion with no code
behind it, and it travelled furthest — into conversation summaries and planning,
not just the documents. `isa_bench/mutate.py` now implements what the claim
described (89.1% semantic kill rate), and `mutate.py --gate` fails the build if
the score or the mutant count regresses. Unbacked prose in the older documents
should be treated as unverified until checked.

**The fourth is a third kind of error.** Not a mismatched basis, and not an
unbacked claim, but a measurement that was **tautological by construction** —
anchoring a nominal at exactly the observed value, then measuring the gap to it
— wrapped in a mechanism argument that was simply incorrect. It survived review
twice, including mine, partly because the number looked alarming, and alarming
numbers attract less scrutiny than convenient ones. The check that caught it was
cheap and should have been automatic: vary the parameter and see whether the
result moves. It did not, which is the signature of an artifact.
