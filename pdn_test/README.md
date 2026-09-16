# PDN integration test: do the CFGMEM macros power on a Tiny Tapeout tile?

**Status: the risk is CONFIRMED REAL. The mitigation is NOT closed.**

This is the reproducible harness for the largest open risk to the row-format
freeze (`docs/row-format-decision.md` §5.1). Both candidate configurations, C
and D, put the instruction memory in tiled `CFGMEM_IHP16` macros, so if those
macros cannot be powered on a TT tile, both collapse to the flop baseline.

## What it builds

One STT state machine (`rtl/stt_core_cfgmem.v` = `stt_core` with
`stt_imem_cfgmem`) on a 2x2 TT tile, with two CFGMEM macros built by our own
DFFRAM run. Every PDN setting is copied verbatim from the hardened TT template
(`runs/wokwi/21-openroad-generatepdn/config.json`).

```bash
# inside the LibreLane 3.1.0.dev3 devshell, PDK_ROOT set
python3 -m librelane --manual-pdk --pdk-root $PDK_ROOT --pdk ihp-sg13cmos5l \
    --scl sg13cmos5l_stdcell config.json          # default TT PDN -> fails
python3 -m librelane ... config_aligned.json      # with the mitigation attempts
```

## Confirmed: the default configuration does not power the macros

`config.json`, TT settings verbatim:

```
[WARNING PDN-0231] u_imem.g_tile[0].u_tile is not connected to any power/ground nets.
[WARNING PDN-0189] Supply pin .../VPWR is not connected to any net.
[INFO ODB-0403] 0 connections made, 0 conflicts skipped.
ERROR: 2 critical disconnected pins found.
```

The macros place correctly (`Successfully placed 2 instances`, 57,589.06 µm²).
`PDN_CONNECT_MACROS_TO_GRID: true` does nothing for them.

**Mechanism.** `PDN_MULTILAYER = False`, so the only stripes are vertical
**Metal4** — the same layer as the macro's VPWR/VGND pins — and pdngen trims its
stripes *around* macros, so no stripe ever crosses a pin. The macro also blocks
Metal1–3 (`OBS`), so nothing below Metal4 can reach them either.

## The geometry constraint, derived from the artifacts

Measured, not copied — and they match `kdp1965/ihp-um-janestreet-prism`
independently, which is a useful cross-check:

| parameter | TT default | required | derived from |
|---|---|---|---|
| `PDN_VPITCH` | 50 | **44.96** | macro VPWR column pitch (55.350 − 10.390) |
| `PDN_VSPACING` | 2 | **3.52** | macro VPWR→VGND centres 5.62 µm, − `VWIDTH` 2.1 |
| macro x | — | **45.43** | stripes measured at 11.91 + 44.96k in the post-pdngen DEF |

Each was confirmed by the error shrinking exactly as predicted: first attempt
reported "2.880 µm off" on both nets; fixing x cleared VPWR and left VGND at
"1.520 µm off" — precisely 5.62 − 4.1. With all three applied:

```
misalignment warnings: 0
[INFO] VPWR: 27 tile stripes kept, 16 full-height stripes added over macro pin columns
[INFO] VGND: 25 tile stripes kept, 14 full-height stripes added over macro pin columns
```

**Macro placement is therefore quantised to a 44.96 µm grid at a fixed offset.**
For 8–9 SMs that is 16–18 macros all needing grid-aligned positions — a
floorplanning constraint none of the area arithmetic accounted for.

## Not closed: two failure modes remain

| attempt | result |
|---|---|
| geometry aligned, no `PDN_MACRO_CONNECTIONS` | stripes drawn over the pins, but the DB connectivity check still reports **2 critical disconnected pins**. The check tests database connectivity, not overlapping shapes. |
| add `PDN_MACRO_CONNECTIONS` | pdngen tries to build a per-macro grid, cannot on a single-layer PDN: `PDN-0232 grid ... does not contain any shapes or vias` → `PDN-0233 Failed to generate full power grid`. `ERROR_ON_PDN_VIOLATIONS: 0` does not suppress it (it is a hard error, not a violation). |

So the physical connection and the logical connection each work only when the
other is absent. prism ships working CFGMEM macros on this PDK, so a working
recipe demonstrably exists — but it is more than these parameters plus the
plugin, and this harness has not reproduced it.

## Next step

Replicate prism's flow *as a whole* rather than parameter-by-parameter: its
`src/config.json`, `flow.py` and `librelane_plugin_prism_pdn.py` together,
against a design of ours. The remaining unknown is whether prism reorders or
replaces steps around `GeneratePDN`, which per-parameter porting cannot reveal.

## Regenerating the inputs

`macro/` (2.6 MB of LEF/GDS/lib/spef/netlist) and the two prism plugin files are
gitignored because both are generated or vendored. To rebuild:

```bash
# the macro, from our own DFFRAM run
cd ~/eda/ref/dffram_lrl
python3 dffram.py --manual-pdk -p ihp-sg13cmos5l -s sg13cmos5l_stdcell -b cfgmem_ihp 16x32
cp products/CFGMEM_IHP16/lef/CFGMEM_IHP16.lef                       <repo>/pdn_test/macro/
cp products/CFGMEM_IHP16/nl/CFGMEM_IHP16.nl.v                       <repo>/pdn_test/macro/
cp products/CFGMEM_IHP16/klayout_gds/CFGMEM_IHP16.klayout.gds       <repo>/pdn_test/macro/CFGMEM_IHP16.gds
cp products/CFGMEM_IHP16/spef/nom/CFGMEM_IHP16.nom.spef             <repo>/pdn_test/macro/
cp products/CFGMEM_IHP16/lib/nom_typ_1p20V_25C/CFGMEM_IHP16__nom_typ_1p20V_25C.lib <repo>/pdn_test/macro/

# the PDN plugin, from prism
cp ~/eda/ref/prism/odb_stripes.py ~/eda/ref/prism/librelane_plugin_prism_pdn.py <repo>/pdn_test/
```
