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

---

# RESOLVED: the macros place, power, route and pass LVS

`config_plugin_only.json` closes it. Full flow, 73 stages, exit 0.

| metric | value |
|---|---|
| `design__power_grid_violation__count` | **0** (VPWR 0, VGND 0) |
| `route__drc_errors` | **0** |
| `route__antenna_violation__count` | **0** |
| LVS (`netgen`) | **"Circuits match uniquely."** all 7 LVS counters 0 |
| `design__instance__area__macros` | 57,589.1 µm² |
| `route__wirelength` | 108,081 |

Independently confirmed by `verify_macro_power.py`, which reads the routed DEF
and checks every macro power pin rectangle is covered by Metal4 geometry on the
matching special net:

```
VPWR: 10 Metal4 special-net shapes
  u_imem.g_tile[0].u_tile   8/8 pin rects covered  OK
  u_imem.g_tile[1].u_tile   8/8 pin rects covered  OK
VGND: 10 Metal4 special-net shapes
  u_imem.g_tile[0].u_tile   7/7 pin rects covered  OK
  u_imem.g_tile[1].u_tile   7/7 pin rects covered  OK
```

## The working recipe

1. **`ExtendPowerStripes` plugin** inserted after `OpenROAD.GeneratePDN` via
   `meta.substituting_steps`. Required: pdngen trims its stripes around macros,
   so something must draw them back across the pin columns.
2. **Stripe grid matched to the macro**, all three values derived from the
   artifacts and independently equal to prism's:
   `FP_PDN_VPITCH 44.96`, `FP_PDN_VSPACING 3.52`, macro x on the grid (45.43 here).
3. **Do NOT set `PDN_MACRO_CONNECTIONS`.** This is the part that cost the most
   time. It makes pdngen build a per-macro grid, which on a single-layer PDN is
   necessarily empty *at that moment* — the tile stripes are still trimmed
   around the macros and `ExtendPowerStripes` has not run yet — so pdngen hard
   fails `PDN-0232`/`PDN-0233`. That error cannot be suppressed:
   `ERROR_ON_PDN_VIOLATIONS` lives in `checker.py`, a different step.
4. **`ERROR_ON_DISCONNECTED_PINS = 0`**, and understand exactly what it hides.

## The one caveat, stated precisely

`design__critical_disconnected_pin__count` is still **2** in the final metrics.
The macro power pins are physically connected — same Metal4, overlapping
geometry, confirmed twice — but the plugin never creates the ODB `iterm`-to-net
*annotation* that pdngen would have. So a database-level check still calls them
disconnected while the extracted layout says otherwise.

**LVS is the arbiter and LVS passes**, because LVS extracts geometry rather than
reading the ODB annotation. That is why suppressing the check is defensible here
and would not be if LVS had anything to say. Anyone re-running this should treat
those 2 as expected and check LVS instead.
