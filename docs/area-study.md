# STT protocol emulator — area characterization on IHP sg13cmos5l

Area-only study of the programmable state-table (STT) architecture, to inform
freezing the instruction encoding. No place-and-route of our own design, no
ISA changes, no new architecture.

**Status:** complete, with one exception. All synthesis measurements are done,
and the Tiny Tapeout template baseline (§1) was hardened end to end through
LibreLane. The exception is a DFFRAM macro built at our own row sizes (§5.2):
DFFRAM only ports a single fixed 16x32 block to cmos5l, so 32x21 and 64x21
cannot be built. That is the open question in §9.

---

## 0. Method, and what these numbers are not

All areas come from Yosys `stat -liberty` against the typical-corner cmos5l
standard-cell liberty. Every table cell below is either copied from a Yosys
log in `build/` or is arithmetic on such values, shown inline.

**Liberty selection.** The PDK ships both `sg13g2` and `sg13cmos5l`; they are
different processes. The file used is

    $PDK_ROOT/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib

which on the machine these numbers were produced on resolved to
`/home/tejas/pdk/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib`
(`PDK_ROOT=$HOME/pdk`).

It was chosen because it is the typical corner (`nom_voltage 1.2`, `nom_temperature
25`, `nom_process 1`) matching `DEFAULT_CORNER` in the PDK's own LibreLane
config. Confirmed by grep before use: **84 cells, all `sg13cmos5l_`-prefixed,
zero `sg13g2_` cells**. `make lib-check` re-runs that confirmation.

> **`stat` area excludes the clock tree, fill cells, tap cells and all
> routing.** It is standard-cell area only, therefore a lower bound. It must
> not be compared directly against a tile budget, and it must not be compared
> against a macro LEF footprint, which includes all of those things. §5.4
> handles that comparison explicitly.

**Validity gate.** Every run is checked by `scripts/check_area.py` for the two
conditions the study requires: `dfflibmap` mapped flops to real `sg13cmos5l_`
sequential cells, and the final cell histogram contains no `$`-prefixed cells.
A run failing either is reported as INVALID and its area is not used. **All
runs reported here passed both checks.**

Note that a hierarchical run legitimately shows `$paramod$...` entries — those
are parameterized *module* names on submodule-instance lines, not unmapped
RTLIL cells. `check_area.py` distinguishes the two.

**Reproducing everything:**

```bash
export PATH="$HOME/eda/oss-cad-suite/bin:$PATH"   # Yosys 0.69+62
export PDK_ROOT="$HOME/pdk"                       # IHP-Open-PDK dev 2bbec755
cd ~/projects/protocol-emulator-asic-competition
make area          # all 18 runs + the summary tables
make check         # re-verify the validity gate on existing logs

# or individually:
make area-core     # hierarchical + flattened stt_core
make area-imem     # 32- and 64-row flop imem
make area-extras   # CRC/LFSR and bit stuffer
make area-timer    # A1: TIMER_W = 8,12,16,20,24
make area-fifo     # A6: in-core FIFOs at depth 2,4,8
make area-roww     # row width = 20,21,22,24
```

Each run writes `build/<name>.ys` (the literal expanded script), `<name>.log`
and `<name>.json`, so every number has its script beside it.

**Structural placeholders.** This is a size model, not a product. It is
structurally faithful — same muxes, same flops, same decode depth — but it has
not been functionally verified. Specifically:

* `stt_palette_fixed` holds the 24 frozen entries as a constant ROM generated
  by `scripts/gen_palette.py`. The *entries* are the in-sample six of
  Ambiguity A3; a different freeze changes the ROM contents, not its size.
* `stt_imem` uses an **asynchronous** read: the STT model fetches and decodes a
  row in the same cycle. Any synchronous macro (SRAM, and DFFRAM in registered
  mode) needs an extra pipeline stage that this model does not contain. See
  §5.4.
* The CRC5 in `stt_datapath` is the reflected-0x14 step from the model; the
  separate 16-bit unit in §6 is a different, programmable-polynomial block.
* No functional tests have been run against any of this RTL.

---

## 1. Tiny Tapeout template baseline — COMPLETE

Purpose: calibrate µm²-to-tiles through *our* flow (LibreLane, not OpenLane).

Template: `github.com/TinyTapeout/ttihp-verilog-template`, branch `cmos5l`,
commit `b86a2a7`. Support tools: `TinyTapeout/tt-support-tools`, branch
`ihp-sg13cmos5l`, commit `da63c99`.

### 1.1 Tile geometry — RESOLVED

The authoritative per-tech table is
`tt/tech/ihp-sg13cmos5l/tile_sizes.yaml`:

| tiles | DIE_AREA (µm) | µm² | mm² |
|---|---|---|---|
| 1x1 | 202.08 x 154.98 | 31,318.4 | 0.031 |
| 2x2 | 419.52 x 313.74 | 131,620.2 | 0.132 |
| 6x2 | 1289.28 x 313.74 | 404,502.7 | 0.405 |
| **6x4** | **1289.28 x 710.64** | **916,213.9** | **0.916** |
| 8x2 | 1724.16 x 313.74 | 540,938.0 | 0.541 |

This was confirmed end-to-end by the flow itself, not just read from the file:
`tt_tool.py --create-user-config --ihp` generated

```json
"DIE_AREA": "0 0 202.08 154.98",
"RT_MAX_LAYER": "Metal4"
```

into `src/user_config.json` for the default `tiles: "1x1"`.

> **This corrects two figures used earlier in this study.**
>
> * The `info.yaml` comment "a single tile is about 167x108 uM" is **stale** —
>   it is a sky130-era number (sky130's own `tile_sizes.yaml` gives 1x1 =
>   161.00 x 111.52). It does **not** apply to cmos5l.
> * The competition announcement's "~0.7 mm²" for 6x4 is **low**. The real
>   cmos5l 6x4 die is **0.916 mm², a factor of 1.31 larger**. cmos5l tiles are
>   1.74x the area of sky130 tiles.
>
> Both earlier figures understated the available area. §7 uses 0.916 mm².

**8x4 is not in the cmos5l table.** The stock template offers at most `8x2`,
and the cmos5l file stops at `6x4`. The competition's 8x4 requires the custom
support-tools branch that `kdp1965/ihp-um-janestreet-prism` uses
(`kdp1965/tt-support-tools`, branch `cmos-8x4`). By analogy with the 6x4 row,
8x4 would be 1724.16 x 710.64 = 1,225,257 µm², but **that is inference from the
table's pattern, not a measured value**, and is flagged as such wherever used.

Other calibration facts read from `src/config.json`:

| Item | Value |
|---|---|
| `PL_TARGET_DENSITY_PCT` | **60** (TT's own default) |
| `CLOCK_PERIOD` | 20 ns (50 MHz) |
| `FP_SIZING` | `absolute` |

### 1.2 Hardened template — COMPLETE

The unmodified template was hardened end to end through LibreLane (all 79
flow stages, synthesis → GDS streamout). From `runs/wokwi/final/metrics.json`:

| metric | value |
|---|---|
| `design__die__area` | **31,318.4 µm²** |
| `design__core__area` | **28,941.5 µm²** (92.41% of die) |
| `design__instance__area__stdcell` | 633.226 µm² |
| `design__instance__count__stdcell` | 69 |
| `design__instance__utilization` | 0.0218795 (**2.19%**) |
| `design__instance__area__class:fill_cell` | 28,308.3 µm² over 2309 fill cells |
| `timing__hold__tns`, `design__power_grid_violation__count` | 0, 0 |

Two things fall out of this, and both matter:

**(a) The die area is confirmed.** `design__die__area` = 31,318.4 µm² is exactly
202.08 x 154.98. The §1.1 table is the flow's own geometry, not just a YAML file.

**(b) The die→core margin is *absolute*, not proportional.** The core is inset
by `LEFT/RIGHT_MARGIN_MULT 6` x site width 0.48 = **2.88 µm** on each side and
`TOP/BOTTOM_MARGIN_MULT 1` x site height 3.78 = **3.78 µm** top and bottom:

```
(202.08 - 2x2.88) x (154.98 - 2x3.78) = 196.32 x 147.42 = 28,941.5 µm²
```

which matches `design__core__area` exactly. Because the inset is a fixed number
of microns rather than a percentage, **the core fraction improves with die
size** — 92.41% at 1x1 but **98.49% at 6x4**:

| tiles | die µm² | core µm² | core/die |
|---|---|---|---|
| 1x1 | 31,318.4 | 28,941.5 | 92.41% |
| **6x4** | 916,213.9 | **902,417.2** | 98.49% |
| 8x4 *(inferred die, §1.1)* | 1,225,257.1 | 1,208,172.7 | 98.61% |

§7 uses the **core** areas, which is the right basis for placing standard cells.

> The template's own 2.19% utilization is **not** a density target — it is a
> 69-cell example design sitting in a whole tile. The number to carry forward
> is the die→core relationship, not this utilization.

Local workarounds needed to run the flow here — none affect any area number,
and all are confined to the template checkout and its venv:

* **Toolchain matrix.** The PDK (IHP-Open-PDK dev `2bbec755`, exactly the
  revision `tt-gds-action/install_sg13cmos5l.sh` pins) defines `FILL_CELLS`/
  `DECAP_CELLS` (plural) and deliberately omits welltap/endcap ("There are no
  endcap and welltie cells in ihp-sg13cmos5l"). **LibreLane 2.4.2 requires the
  singular names and rejects this PDK.** The working combination is
  **LibreLane 3.1.0.dev3** (what `tt-gds-action@ihp-cmos5l` pins) in **its own
  nix devshell**, which brings the matching **Yosys 0.66** — LibreLane 3.1's
  `pyosys` scripts call `ys.Pass.call`, absent from the Yosys 0.46 in the
  LibreLane 2.4.2 shell. Mixing a pip LibreLane 3.x into a nix 2.4.2 shell gets
  to flow stage 5 of 80 and then dies there.
* `info.yaml` title/author/description filled in (the template ships them empty
  and the tool refuses to run). **Metadata only; RTL and `config.json` untouched.**
* `cairosvg` and `matplotlib` stubbed in the venv. Both are doc-rendering only
  (`matplotlib` is used solely for `mpl.ticker.EngFormatter` in `doc_utils.py`)
  and neither is on the harden path. They are pip binary wheels that cannot find
  `libstdc++`/`libcairo` inside the nix shell, and forcing a system or older-nix
  library onto `LD_LIBRARY_PATH` either segfaults the interpreter or breaks the
  shell's own KLayout (`CXXABI_1.3.15 not found`). Stubbing is the safe option.
* `yowasp-yosys` shimmed to the real `yosys` on PATH.
* `$PDK_ROOT/ihp-sg13cmos5l/SOURCES` created, as the official installer does.
  Without it the flow completes but the post-run version bookkeeping raises
  `FileNotFoundError`.

Reproduce:

```bash
cd ~/eda/ref/ttihp-verilog-template
NP_LOCATION=~/eda NP_RUNTIME=bwrap ~/eda/nix-portable nix \
  --extra-experimental-features 'nix-command flakes' \
  --extra-substituters https://nix-cache.fossi-foundation.org \
  --extra-trusted-public-keys 'nix-cache.fossi-foundation.org:3+K59iFwXqKsL7BNu6Guy0v+uTlwsxYQxjspXzqLYQs=' \
  develop github:librelane/librelane/3.1.0.dev3 --command bash -c \
  'PDK_ROOT=~/pdk PDK=ihp-sg13cmos5l PATH=$PWD/.shim:$PATH \
   .venv-tt3/bin/python tt/tt_tool.py --harden --ihp --no-docker'
```

## 2. Per-block breakdown, hierarchy preserved

`make area-core` → `build/core_hier.{ys,log,json}`. Local area, excluding
submodules.

| block | cells | µm² | flops | sequential µm² |
|---|---|---|---|---|
| `stt_imem` (32x21) | 1820 | 56,385.92 | 703 | 34,439.13 |
| `stt_palette_load` | 283 | 7,785.44 | 104 | 5,094.84 |
| `stt_datapath` | 519 | 6,968.43 | 52 | 2,547.42 |
| `stt_config` | 130 | 4,363.63 | 65 | 3,184.27 |
| `stt_decode` | 69 | 1,150.25 | 10 | 489.89 |
| `stt_palette` (mux) | 44 | 480.82 | 0 | 0.00 |
| `stt_palette_fixed` (ROM) | 44 | 379.17 | 0 | 0.00 |
| `stt_core` (wiring only) | 0 | 0.00 | 0 | 0.00 |
| **whole-design roll-up** | **2909** | **77,513.66** | **934** | — |

## 3. Flattened total

`make area-core` → `build/core_flat.{ys,log,json}`.

| | cells | µm² | flops | sequential µm² |
|---|---|---|---|---|
| `stt_core`, flattened | 3408 | **77,261.35** | 934 | 45,755.54 (59.2%) |

Flat is 0.33% below the hierarchical roll-up (77,261.35 vs 77,513.66), which
is cross-boundary optimization. **The flat number is the true total.**

**The flop budget reconciles exactly**, which is the main structural check that
the RTL is what `rtl/ISA_NOTES.md` describes:

    703 (imem) + 104 (palette_load) + 10 (decode) + 52 (datapath) + 65 (config)
      = 934 flops, matching core_flat

`stt_config` = `TIMER_W + 1 + 2 + 4*CNT_W + SR_W + 2*NSLOT` = 16+1+2+32+8+6 =
**65**, exactly as measured. `stt_palette_load` = 8 x 13 = **104**, exactly the
loadable-palette bit count required by the ISA. Unit flop
(`sg13cmos5l_dfrbpq_1`) = **48.9888 µm²**; 934 x 48.9888 = 45,755.5 µm²,
matching the reported sequential area.

---

## 4. The headline: the instruction memory dominates

**`stt_imem` is 56,398.77 of 77,261.35 µm² — 73.0% of one state machine.**
All the decode, palette, datapath and config logic together is 20,862.58 µm².

Consequently the imem storage decision, not the decode logic, sets how many
state machines fit on the die. That is what §5 is about.

---

## 5. Instruction memory variants

Program size: a row is 21 bits (`rtl/ISA_NOTES.md` §1).

* 32 rows x 21 = **672 bits**
* 64 rows x 21 = **1344 bits** (the "~1.3 kbit" figure)

### 5.1 Variant 1 — flops (the `memory_map` baseline)

`make area-imem` → `build/imem32.*`, `build/imem64.*`.

| rows | bits | cells | flops | µm² | **µm²/bit** |
|---|---|---|---|---|---|
| 32 | 672 | 1819 | 703 | 56,398.77 | **83.93** |
| 64 | 1344 | 3563 | 1376 | 110,632.74 | **82.32** |

Scaling is essentially linear (2x rows → 1.96x area), so there is no economy
of scale to exploit by going deeper.


### 5.1b What one more row bit actually costs — the number for the freeze

`make area-roww`. 32-row `stt_imem`, row width swept.

| ROW_W | cells | flops | µm² | delta per bit |
|---|---|---|---|---|
| 20 | 1798 | 670 | 53,876.64 | — |
| 21 | 1819 | 703 | 56,398.77 | +2,522.13 |
| 22 | 1948 | 736 | 59,120.33 | +2,721.56 |
| 24 | 2112 | 802 | 64,347.51 | +2,613.59 (avg of 2) |

Flop counts go 670 → 703 → 736 → 802, i.e. exactly **33 flops per row bit**
(32 array rows + 1 bit of the load staging register), which confirms the
structure.

> **Measured cost of one row bit: 2,617.72 µm²** — `(64,347.51 − 53,876.64) / 4`.
>
> A flop-count-only estimate gives 33 x 48.9888 = 1,616.6 µm² and is **1.62x too
> low**; the rest is the read mux and load-path logic that widens with the row.
> This corrects the estimate given earlier in this study.

In the currency that matters for the encoding decision:

* **1 row bit ≈ 2.42x the entire configurable bit stuffer** (1,079.57 µm²).
* **The whole 16-bit CRC/LFSR unit costs 1.28 row bits** (3,350.59 µm²).

So if adding the CRC unit lets you drop even **two** bits from the row, it pays
for itself and hands back area. That is the trade to evaluate before freezing.

### 5.2 Variant 2 — DFFRAM latch array

**A macro at our sizes cannot be built for cmos5l with the current DFFRAM.
This is the "stop and ask" the task called for; the question is in §9.**

What the DFFRAM checkout (`DFFRAM.librelane`) actually supports on cmos5l:

* `platforms/ihp-sg13cmos5l/sg13cmos5l_stdcell/tech.yml` states it outright:
  *"Only the `cfgmem_ihp*` building blocks are ported; see
  `block_definitions.v`."*
* `models/cfgmem_ihp/config.yml` pins that block to a single geometry —
  `widths: [32]`, `counts: [16]`, placer `IhpCfgMem_16`. **16 x 32 only.**
* `block_definitions.v` for cmos5l defines 17 modules whose only storage
  element is `CFG_WORD`; sky130's has 23 and includes the generic RAM word
  blocks.
* The generic `ram` block *would* cover us — `counts: [8, 32, 128, …]`,
  `widths: [8, 16, 24, 32, …]`, so 32x24 is a legal size — but it is **not
  ported to cmos5l**, only to sky130/gf180/sg13g2.

So neither 32x21 nor 64x21 is buildable: 32x21 would need the unported `ram`
block (rounded to 32x24), and 64 is not even in the generic block's `counts`.

**What we do have is a real, measured cmos5l DFFRAM data point** — the
prebuilt `CFGMEM_IHP16` macro from `kdp1965/ihp-um-janestreet-prism`
(`macros/CFGMEM_IHP16/`), built by exactly this DFFRAM for exactly this PDK:

| | value | source |
|---|---|---|
| macro footprint | 331.20 x 86.94 µm = **28,794.5 µm²** | `CFGMEM_IHP16.lef` `SIZE` |
| organisation | `Di0[32]`, `Do0[32]`, `A0[4]`, `WROW[16]` → 16 x 32 | LEF pins |
| capacity | **512 bits** | 512 x `sg13cmos5l_dlhq_1` counted in `CFGMEM_IHP16.nl.v` |
| **µm²/bit** | **56.24** | 28,794.5 / 512 |

The storage cell is a `dlhq_1` latch at **30.84 µm²** against the `dfrbpq_1`
flop's **48.9888 µm²** — the bit cell itself is **1.59x smaller**. Inside the
macro, 512 x 30.84 = 15,790.1 µm² of latch sits in a 28,794.5 µm² footprint,
i.e. the macro packs at **54.8%**.

> **Caveat on using 56.24 µm²/bit for our sizes.** It is measured at 16x32, not
> at 32x21 or 64x21. A 21-bit-wide array wastes 11 of every 32 columns unless
> the block is re-parameterised, and per-bit overhead generally improves with
> depth. Treating 56.24 as our number assumes it scales, which is exactly what
> building at our size would have checked. It is used in §5.4 as the best
> available cmos5l measurement, not as a measurement of our design.

### 5.3 Variant 3 — IHP SRAM macro (for the record only)

Inventory of `libs.ref/sg13cmos5l_sram/lef/`, sizes read from LEF `SIZE`:

| macro | µm² | organisation | bits |
|---|---|---|---|
| `RM_IHPSG13_1P_64x16_c2` | 15,240.4 | 64 x 16 | 1024 |
| `RM_IHPSG13_1P_256x8_c3_bm_bist` | 17,546.9 | 256 x 8 | 2048 |
| `RM_IHPSG13_2P_64x22_c2_bm_bist` | 39,383.9 | 64 x 22 | 1408 |
| `RM_IHPSG13_1P_64x64_c2_bm_bist` | 50,489.1 | 64 x 64 | 4096 |

**The smallest available depth is 64.** A 21-bit row does not fit a 16-bit
macro, so the single-port option is two `64x16` side by side = 64 x 32 =
2048 bits for 2 x 15,240.4 = **30,480.8 µm²**.

| config | bits used | bits provided | µm² | µm²/bit | overshoot |
|---|---|---|---|---|---|
| 64 rows, 2x `1P_64x16` | 1344 | 2048 | 30,480.8 | 22.68 | 1.52x |
| 32 rows, 2x `1P_64x16` | 672 | 2048 | 30,480.8 | 45.36 | **3.05x** |
| 64 rows, 1x `2P_64x22` | 1344 | 1408 | 39,383.9 | 29.30 | 1.05x |

At 32 rows the depth floor alone wastes half the macro; combined with the
21-into-32-bit width waste that is a **3.05x** overshoot on our ~0.7 kbit.
At 64 rows it is 1.52x.

**Not integrated, as instructed.** The Tiny Tapeout single-layer PDN cannot
reach these macros' Metal4 power pins without custom flow steps — the prism
repo confirms this and works around it with an `ExtendPowerStripes` LibreLane
plugin that draws tile stripes across each macro's pin columns. That is out of
scope here.

### 5.4 Comparing the three fairly

These numbers are **not** measured the same way and must not be put in one
column naively:

* flop imem **83.93 µm²/bit** — Yosys `stat`, standard cells only.
* DFFRAM **56.24 µm²/bit** and SRAM **22.68 µm²/bit** — LEF `SIZE`, real
  placed-and-routed footprints including fill, decap and antenna cells.

To compare, the flop figure has to be inflated to a placement density. At the
template's own default (`PL_TARGET_DENSITY_PCT` 60):

| variant | µm²/bit (comparable) | vs flops |
|---|---|---|
| flops, at 60% density | 83.93 / 0.60 = **139.88** | 1.00x |
| DFFRAM latch macro | **56.24** | **2.49x smaller** |
| SRAM 2x `1P_64x16`, 64 rows | **22.68** | **6.17x smaller** |

> Both macro rows are measured at the macro's own geometry, not ours: DFFRAM at
> 16x32 (§5.2) and SRAM at 64x32 with 704 of 2048 bits unused at 64 rows (§5.3).
> Neither is a measurement of a 32x21 or 64x21 array. The flop row is the only
> one measured at our actual size.

**Access pattern.** Written once at load, read every cycle, mostly sequential
with short-range branches. That suits all three. The real constraint is the
asynchronous read in `stt_imem` (§0): a synchronous macro needs an added
pipeline stage, which costs a cycle of branch latency the ISA does not
currently model.

---

## 6. Optional units, priced before freezing the row width

`make area-extras`.

| unit | cells | flops | µm² | as % of one SM |
|---|---|---|---|---|
| 16-bit programmable-polynomial CRC/LFSR | 198 | 33 | **3,350.59** | 4.3% |
| configurable bit stuffer (insert/remove after N) | 64 | 11 | **1,079.57** | 1.4% |
| **both** | 262 | 44 | **4,430.16** | **5.7%** |

Both are cheap relative to the imem, and both flop counts are fully accounted
for in the RTL:

* CRC: `poly`[16] + `state`[16] + `reflect`[1] = **33**. Galois form with a
  loadable polynomial and a selectable bit order, so it covers both reflected
  (USB CRC5/CRC16) and CCITT-style CRCs; narrower CRCs run in the low bits
  with the polynomial zero-extended.
* Bit stuffer: `n_cfg`[4] + `mode_insert` + `mode_ones` + `run`[4] +
  `last_bit` = **11**.

**Affordability:** together they add 5.7% to one SM — roughly one-eighteenth of
what a single 32-row flop imem costs. If they remove the need for `crcstep`
palette entries or open-coded stuffing loops, they very likely pay for
themselves in rows. They are not what threatens the tile budget.

---

## 7. Fixed cost vs per-state-machine cost

Decode, datapath and imem replicate per SM. Only the **fixed** palette is
shareable, and only if SMs can read one ROM:

| | µm² |
|---|---|
| shareable: `stt_palette_fixed` + `stt_palette` mux | **859.99** |
| per-SM: everything else | **76,401.36** |

> The 8 loadable palette entries (`stt_palette_load`, 7,785.44 µm², 104 flops)
> are **not** shareable if SMs run different programs — that is the whole point
> of their being per-program. They are counted per-SM above.

The shareable fraction is only **1.1%** of a core. **Sharing the fixed palette
buys almost nothing.** The per-SM cost is what matters, and it is dominated by
the imem.

### How many SMs fit

Using per-SM 76,401.36 µm² and 859.99 µm² shared, against the **core** areas
derived from the hardened template in §1.2 (core, not die — the die includes
the margins that no standard cell can use):

| die | core µm² | density | usable µm² | **SMs** |
|---|---|---|---|---|
| 6x4 | 902,417 | 50% | 451,209 | **5.89** |
| 6x4 | 902,417 | 60% (TT default) | 541,450 | **7.08** |
| 8x4 *(inferred die, §1.1)* | 1,208,173 | 50% | 604,086 | **7.90** |
| 8x4 *(inferred die, §1.1)* | 1,208,173 | 60% (TT default) | 724,904 | **9.48** |

**Going 6x4 → 8x4 adds about two more SMs** (+2.01 at 50%, +2.40 at 60%).

> **One remaining bias, and it is in the optimistic direction.** `stat` area
> excludes the clock tree, fill and tap cells, and all routing (§0). The
> hardened template shows how large that gap can be: 69 standard cells of
> 633.226 µm² needed 2309 fill cells covering 28,308.3 µm² to fill its tile.
> Fill is not *extra* area — it occupies whatever the design does not — but a
> real design's clock tree and routing congestion are, and they are not in any
> per-SM number here.
>
> The density column is doing that work: at `PL_TARGET_DENSITY_PCT` 60 there is
> 40% slack for routing, CTS buffers and fill. That is TT's own default and the
> reason to prefer the 60% row. Treat **6 SMs at 6x4 and 8 at 8x4** as the
> planning number, and the 60% rows as the optimistic case.

Reproduce: `python3 scripts/summarize_area.py build --tile-um2 902417 --density 0.6`

---

## 8. What this means for freezing the encoding

1. **The imem is the whole ballgame** — 73% of an SM. On the best cmos5l
   measurement available, a DFFRAM latch array is worth ~2.5x on those bits
   (§5.4). Applied to the whole imem that is roughly **6 SMs → 9** at 6x4/60%,
   which is the single largest lever in this study. Decide it before freezing
   the row width, because it changes what a row bit costs.
2. **Row width is expensive at 32 rows.** A measured **2,617.72 µm² per row
   bit** (§5.1b) — 2.42x the whole bit stuffer. Conversely the 16-bit CRC unit
   costs only 1.28 row bits, so it pays for itself if it saves two.
3. **The optional units are affordable** (§6) — 5.7% combined. Width pressure
   from adding them is a better trade than it looks, *provided* they remove
   rows or palette entries.
4. **Sharing the fixed palette is not a lever** (1.1%). Do not complicate the
   architecture for it. The in-core FIFOs *are* a lever: 15.1% per SM at depth 8
   (Appendix B), and they are shareable.
5. **The die is bigger than the announcement implies.** The real cmos5l 6x4 is
   **0.916 mm²**, 1.31x the "~0.7 mm²" figure, and 98.49% of it is usable core
   (§1.1, §1.2). Both were verified by hardening the template. That is worth
   roughly two extra SMs relative to planning against 0.7 mm².

---

## 9. The one open question

**Do we need DFFRAM's generic `ram` block ported to cmos5l, or can we live with
tiling the fixed 16x32 block?**

§5.2 establishes that DFFRAM currently ports only `cfgmem_ihp` to cmos5l, fixed
at 16 x 32, so 32x21 and 64x21 cannot be built directly. But the existing
`CFGMEM_IHP16` can be *tiled*, and that turns out to be good enough to matter.

Comparing like for like — both sides as **real placed footprints**, so the flop
imem is inflated from `stat` to the template's 60% density (§5.4):

| option | µm² | µm²/bit (used) | vs flops |
|---|---|---|---|
| 32x21 flops (`stat` 56,398.77 @ 60%) | 93,998 | 139.88 | 1.00x |
| 32x21 as 2x `CFGMEM_IHP16` | 57,589 | 85.70 | **1.63x smaller** |
| 64x21 as 4x `CFGMEM_IHP16` | 115,178 | 85.70 | **1.60x smaller** |
| 32x**32** as 2x `CFGMEM_IHP16` | 57,589 | 56.24 | **2.49x smaller** |

Tiling wastes 11 of every 32 columns at a 21-bit row (`56.24 / (21/32) =
85.70`), which is why the 21-bit rows land at 85.70 rather than 56.24. Even so,
**tiling the existing macro already saves ~36,400 µm² per SM, about 39% of the
imem's real footprint**, with no DFFRAM work at all.

So, in increasing cost:

1. **Tile `CFGMEM_IHP16` at 21 bits.** No DFFRAM work. 1.63x on the imem.
2. **Widen the row to 32 bits and tile.** Also no DFFRAM work, and the column
   waste disappears: 2.49x. This reframes the row-width question entirely — at
   32 bits wide the marginal row bit is *free up to the 33rd*, which inverts
   §5.1b's 2,617.72 µm²/bit and makes the CRC/bit-stuffer encoding decisions in
   §6 and §8 much cheaper.
3. **Port the generic `ram` block** (RAM word blocks in `block_definitions.v`
   plus a placer class) for arbitrary 32x24 / 128x24 geometries. Most work; only
   worth it if neither of the above fits.

I have not implemented any of these — they are architecture changes, and this
task was scoped to area characterization. **Option 2 is what I would evaluate
first**, and it is a row-encoding decision, so it belongs in the freeze.

> Caveat carried from §5.2: 56.24 µm²/bit is measured at 16x32. Tiling assumes
> it holds per macro instance, which is reasonable (each tile *is* that macro)
> but adds inter-macro routing and the §5.3 PDN problem — the TT single-layer
> PDN cannot reach Metal4 macro power pins without the `ExtendPowerStripes`-style
> plugin that prism uses. **That integration cost is real and is not priced
> here.**

---
## Appendix A — Ambiguity A1: TIMER_W sweep

`make area-timer`. Flattened `stt_core` at each width.

| TIMER_W | cells | flops | µm² | delta vs 16 |
|---|---|---|---|---|
| 8 | 3254 | 918 | 75,532.07 | −1,645.28 (−2.13%) |
| 12 | 3331 | 926 | 76,497.37 | −679.98 (−0.88%) |
| 16 | 3406 | 934 | 77,177.36 | 0 |
| 20 | 3478 | 942 | 78,351.24 | +1,173.88 (+1.52%) |
| 24 | 3559 | 950 | 79,246.15 | +2,068.79 (+2.68%) |

Flop counts confirm the structure: `TIMER_W` appears twice (the reload
constant in `stt_config` and the counter in `stt_datapath`), so **2 flops per
timer bit**, exactly as the 918 → 950 progression shows.

**Measured marginal cost: (79,246.15 − 75,532.07) / 16 = 232.13 µm² per timer
bit.** A flop-count-only estimate gives 2 x 48.9888 = 97.98 µm²/bit and is
therefore **2.4x too low** — the compare/decrement logic scales with width too.
This is why the sweep was measured rather than estimated.

> Baseline for this table is `core_timer16`, **not** `core_flat`. They are
> logically identical but differ by 84 µm² (0.11%), because `-chparam` renames
> the top into a `$paramod` and changes ABC's tie-breaking. Sweep points are
> comparable to each other; comparing them to `core_flat` is not valid at that
> resolution.

**Sizing guidance:** at the template's 50 MHz, a divider for 9600 baud is
50e6/9600 = 5208, needing 13 bits. `TIMER_W=16` covers down to ~763 baud and
costs 2.68% less than 24 and 2.13% more than 8. Still open pending your target
clock and slowest required baud.

## Appendix B — Ambiguity A6: in-core TX/RX FIFOs

`make area-fifo`. `stt_core_fifo` = `stt_core` plus a TX and an RX
`stt_fifo` (flop storage, head/tail pointers, level counter), with the host
side of both brought to top-level ports.

| FIFO depth | cells | flops | µm² | delta vs no in-core FIFO |
|---|---|---|---|---|
| none (`core_flat`) | 3408 | 934 | 77,261.35 | — |
| 2 | 3509 | 974 | 80,368.81 | +3,107.46 (+4.0%) |
| 4 | 3685 | 1012 | 83,352.86 | +6,091.51 (+7.9%) |
| 8 | 3884 | 1082 | 88,901.67 | +11,640.32 (+15.1%) |

The competition description prescribes no interface, but Tiny Tapeout does:
the die boundary is ~8 in / 8 out / 8 bidirectional plus clock and reset, with
no host bus and no external memory. So the bytes that `load` pops and `push`
writes must be buffered **somewhere on this die** — in `isa_bench` they come
from `World.tx_fifo`, an unbounded Python deque, which is free in a model and
not free in silicon.

**This delta is the per-SM cost of putting that buffering inside each state
machine.** One shared host-side FIFO block saves it for every SM after the
first. At depth 8 that is 11,640 µm² per SM — about 15% of a core, or a third
of an SM's worth of area across three SMs. **Recommendation: share it**, unless
per-SM back-pressure independence turns out to be needed.

## Appendix C — Frozen ISA assumptions

Per your decision, the remaining ambiguities in `rtl/ISA_NOTES.md` are frozen
at their defaults for this study:

| # | Frozen as |
|---|---|
| A2 | `CNT_W = 8` (follows the model's `0xFF` mask) |
| A3 | palette entries 18–23 = the in-sample six |
| A4 | 32 rows implemented; row 31 reachable only by fall-through (`RET`=31) |
| A5 | test codes 10–15 → false; pin op 7 → hold; `d0`/`d1` on a single slot → hold |
| A7 | loadable palette shares the row array's serial shift-in chain |
| A8 | `SR_W = 8` |

A1 (`TIMER_W`) is measured in Appendix A and remains open pending a clock/baud
target. A6 is measured in Appendix B.
