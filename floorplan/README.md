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
