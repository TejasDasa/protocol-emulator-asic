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
| palette holds? | yes, 32 entries | yes | yes | n/a — no palette |

A and B are shown because B is the trap: **32-bit rows without CFGMEM are worse
than doing nothing**, 4 SMs against the 6 of today's baseline. Row width and
memory technology are one decision, not two. Widening 21 → 32 costs **+51.4%**
on the imem with flops and **+1.9%** with CFGMEM, because storage is two macros
at any width up to 32.

### Program bits, six benchmarks

UART TX, UART RX, SPI mode 0, I²C master, USB LS token TX, JTAG. **Six, not
seven — CAN was not completed** (§6).

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

And both rest on CFGMEM being *integrable*, which is not yet demonstrated. The
Tiny Tapeout single-layer PDN cannot reach the macros' Metal4 power pins
without an `ExtendPowerStripes`-style flow plugin, as `kdp1965/ihp-um-janestreet-prism`
does, and 2N macros must be floorplanned on the tile's stripe pitch. **That work
is not priced in any number here.**

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

Together 4,430.16 µm², 26.1% of the fixed budget, against 8-9 SMs of per-SM
area. **Recommend keeping both.**

---

## 7. What the measurements cannot settle

1. **CFGMEM integration on a TT tile.** The macro builds; placing and powering
   2N of them under a single-layer PDN is unmeasured (§5.1). This is the single
   largest open risk to the recommendation.
2. **Whether 32 rows holds for protocols nobody has written.** JTAG is at 78%
   and it is the only state-machine protocol tested. Ethernet, SD and CAN are
   unwritten.
3. **CAN.** Device model written (`isa_bench/jtag_can.py`), STT program not.
   The structural finding stands in for it (§6) but the row count is unknown.
4. **Post-P&R area for our own design.** Every per-SM figure is `stat` cell area
   or a density projection. No routing, no clock tree, no congestion. The
   template harden calibrates the die, not our logic.
5. **Timing, at every level.** No STA has been run on `stt_core`, and no
   SDF-back-annotated simulation on anything. §5.3 explains why the
   cycle-accurate model cannot speak to pin timing at all: it has no pin path.
   Inter-pin skew between SCK/MOSI and SCL/SDA is the failure mode that matters
   and it is entirely unmeasured. **This is the largest verification gap in the
   study**, and the first thing the next sixteen weeks should close.
6. **Whether the 13-bit grouping is right.** C and D share it. The 1.37%
   reachability of all action subsets is a design choice nobody has re-examined
   since it was set.

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
