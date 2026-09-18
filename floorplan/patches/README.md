# Patches to the vendored prism PDN plugin

`floorplan/odb_stripes.py` and `floorplan/librelane_plugin_prism_pdn.py` are a
vendored copy of the PDN step from `kdp1965/ihp-um-janestreet-prism`, and are
gitignored for that reason. Changes to them live here as patches, so a change is
reviewable and survives a re-vendor.

Apply with:

    cd floorplan && patch -p0 < patches/<name>.patch

## `odb_stripes-annotate-macro-power.patch` — **DO NOT APPLY**

Kept as a record of a negative result. It does not fix `PSM-0069`, and it makes
LVS worse.

**What it does.** After the step draws its full-height Metal4 stripes, connect
each macro's power `ITerm` to the corresponding special net and mark it special.

**Measured effect**, five machines, ten macros, format D:

| metric | pristine | patched |
|---|---|---|
| `design__disconnected_pin__count` | 20 | **0** |
| `design__critical_disconnected_pin__count` | 10 | **0** |
| `design__lvs_net_difference__count` | 0 | **6** |
| `design__lvs_unmatched_net__count` | 0 | **1** |
| `design__lvs_unmatched_pin__count` | 2 | 2 |
| **`design__lvs_error__count`** | **2** | **9** |
| `magic__drc_error__count` | 0 | 0 |
| `PSM-0038` unconnected shapes | 25 | 25 |
| `PSM-0039` unconnected instances | 0 | 11 |
| `PSM-0069` | fails | fails |

So it does exactly what it says — the disconnected-pin counts go to zero — and
that turns out to be the wrong thing to want. Forcing the `ITerm` connection
makes the extracted netlist disagree with the synthesised one, which handles
power specially, so six nets stop matching. Two errors become nine.

**Why it was written, and why that reasoning was wrong.** The disconnected-pin
counts scaled exactly with macro count, which looked like a missing annotation.
The real cause is that the macro power pin columns were 2.88 µm off pdngen's
stripe grid, so the stripes drawn on them connected to nothing. The annotation
papered over the symptom in the database while the metal stayed isolated — which
is why `PSM-0038` did not move.

See `floorplan/gen_config.py`: `X0` is now derived as `TILE_X0 - PIN_OFF` so the
pin columns land on the grid, with an assertion that fails loudly if they ever
do not.

**Nothing here is ready for an upstream report.** The plugin's behaviour was
correct given where the macros were placed, and it printed a warning naming the
misalignment on every affected column. The bug was ours.
