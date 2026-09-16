# Floorplan run: does 6 state machines place, route and meet timing on 6x4?

The last open item before RTL work starts (`docs/row-format-decision.md` §7.1).
`pdn_test/` proved one state machine with two CFGMEM macros places, powers and
passes LVS. This asks the next question: **twelve** macros and six machines on
the real 6x4 die, with each machine's logic placeable beside its own memory.

## What is being hardened, and what that does and does not answer

`stt_chip_cfgmem.v` is generated from `rtl/stt_chip.v` with `stt_core` replaced
by `stt_core_cfgmem`. That is **configuration C**, the 21-bit row with the
palette — the format `rtl/` implements. The frozen format is D and no D RTL
exists (`docs/SPEC.md` §16.2). The substitution is conservative in the direction
that matters:

* the imem is 2 `CFGMEM_IHP16` macros per machine either way — C stores
  21 x 32 = 672 bits, D stores 32 x 32 = 1024, and one macro holds 512 — so
  macro count, geometry and PDN are identical;
* C's per-SM soft logic is *larger* than D's, which is why D fits 9 machines and
  C fits 8. A C floorplan that closes at 6 is a lower bound on D.

It does **not** answer D's own critical paths. C has a palette lookup D does not
and D has an inline 13-bit action decode C does not.

## Geometry

Both constraints are derived in `pdn_test/README.md`, not assumed:

| constraint | value | why |
|---|---|---|
| macro x on a grid | `45.43 + 44.96k` | single-layer Metal4 PDN; the macro's own VPWR/VGND pin columns are on that pitch |
| macro y on a row | multiple of `3.78` | standard-cell row height; the macro is exactly 23 rows tall |

The macro is 331.20 x 86.94. Three fit across the 1283.52 µm core once the
column pitch is rounded up to the next multiple of the stripe pitch
(331.20 / 44.96 = 7.37, so 8 x 44.96 = 359.68). Each machine's two macros are
stacked in one column 79.38 µm apart, two machines per column, three columns.

`gen_config.py` asserts every one of these rather than trusting the arithmetic,
and writes `config.json`. It also regenerates `stt_chip_cfgmem.v` from
`../rtl/stt_chip.v` on every run, so the floorplan cannot drift from the module
the area study measures; the only edits are the module name, the core
instantiated and the `NSM` default.

## Running

```bash
python3 gen_config.py 6      # regenerates stt_chip_cfgmem.v from ../rtl/stt_chip.v and writes config.json
bash run.sh                  # writes run6.log and runs/
python3 report.py runs/RUN_*  # the metrics that decide the question
```

## Environment, which is not obvious and cost an hour

LibreLane and its tools must come from **LibreLane's own upstream devshell**:

```
nix develop github:librelane/librelane
```

Not from `~/eda/ref/dffram`, whose flake pins librelane 2.4.2. Two things break
with 2.4.2: the sg13cmos5l PDK sets `FILL_CELLS` (plural) and 2.4.2 demands
`FILL_CELL`, and its bundled yosys has a pyosys without `Pass.call`. Not from
`~/venv-lrl` either: that is librelane 3.1.0.dev3 on the system Python 3.12,
which has no `tkinter`, and LibreLane needs tkinter to evaluate the PDK's
`config.tcl`. The working combination was recovered from the `COMMANDS` files of
the `pdn_test` run that succeeded, which record the exact store paths.

`NP_RUNTIME=bwrap` is also required; nix-portable's auto-selected `nix` runtime
fails with `setting up a private mount namespace: Operation not permitted`.

## Results

Eight sweep points. Each failing point stops at global routing, because
`GRT_ALLOW_CONGESTION` is 0, and costs about three minutes.

| SMs | layout | density | overflow GCells | usage |
|---|---|---|---|---|
| 6 | interleaved | 60 | 182 | 39.1% |
| 6 | interleaved | 50 | 113 | 37.3% |
| 6 | interleaved | **40** | **42** | 39.5% |
| 6 | interleaved | 30 | 585 | 43.3% |
| 6 | grouped | 50 | 2,017 | 34.5% |
| 6 | grouped | 40 | 1,978 | 35.6% |
| **5** | interleaved | **40** | **1** | **28.0%** |
| 5 | interleaved | 30 | 1 | 30.3% |

**Density has an optimum near 40.** Spreading further made 6 machines worse
(42 → 585 overflow at density 30): past the optimum, spreading only lengthens
wires across the macro shadows.

**Grouping the macros is much worse, not better.** The hypothesis was that one
contiguous macro block would leave clear routing channels, where interleaving
forces signals across four macro shadows. It is ~47x worse. The reason is a
geometry constraint the hypothesis did not account for: only three macro columns
fit across the die, so twelve macros grouped is a block 1,050 µm wide on a
1,283 µm core — not a block with logic around it but a **wall across 82% of the
die**, with one standard-cell row between macro rows and therefore no channel
through it. Interleaving is worse locally and wins decisively, because it leaves
four full-width horizontal channels.

**5 machines reaches 1 overflow GCell of 355,982 resources at 28% usage**, which
is noise rather than congestion, so that point is the one taken to a full signoff
run.

See `docs/row-format-decision.md` §5.5 and §5.5.1 for what this does to the SM
count and why the ceiling binds on routing rather than area.
