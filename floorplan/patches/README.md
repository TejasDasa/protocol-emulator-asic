# Patches to the vendored prism PDN plugin

`floorplan/odb_stripes.py` and `floorplan/librelane_plugin_prism_pdn.py` are a
vendored copy of the PDN step from `kdp1965/ihp-um-janestreet-prism`, and are
gitignored for that reason. Changes to them therefore live here as patches, so
that a fix is reviewable and survives a re-vendor.

Apply with:

    cd floorplan && patch -p0 < patches/<name>.patch

## `odb_stripes-annotate-macro-power.patch`

**What it fixes.** The step draws full-height Metal4 stripes across macro power
pin columns, because the Tiny Tapeout CMOS5L tile has a single-layer PDN and
pdngen trims its stripes around macros. That connects the pins *physically*. It
never tells the database they are connected — pdngen writes that `iterm`-to-net
association itself when it builds a macro grid, and a single-layer PDN cannot
use a macro grid (`pdn_test/README.md`).

**How it shows up.** Every check that reads the database rather than the layout
disagrees with the layout:

| symptom | with 2 macros | with 10 macros |
|---|---|---|
| `design__critical_disconnected_pin__count` | 2 | 10 |
| `design__disconnected_pin__count` | 4 | 20 |
| `OpenROAD.IRDropReport` | passes | **fails `PSM-0069`** |
| `design__lvs_error__count` | 0 | 2, both unmatched pins |

It is exactly one per macro per net, which is the signature: the count scales
with macro count, not with anything about the routing. The preceding warning
names a stripe this step drew, e.g.

    [PSM-0038] Unconnected shape on net VPWR at
    (1089.900um, 3.780um) - (1092.000um, 706.860um), layer: Metal4.

`ERROR_ON_DISCONNECTED_PINS = 0` hides the disconnected-pin count but not
`PSM-0069`, which lives in a different step. With IR-drop analysis disabled the
rest of signoff completes and shows the residue clearly: **signoff DRC clean**
(`magic__drc_error__count` 0, `klayout__drc_error__count` 0) and LVS failing on
**nothing but the two power pins** — `lvs_net_difference` 0,
`lvs_device_difference` 0, `lvs_unmatched_device` 0, `lvs_unmatched_net` 0.
Nothing about the extracted circuit differs. Only the annotation is missing.

**The fix.** After the stripes are drawn, connect each macro's power `ITerm` to
the corresponding special net and mark it special — which is what pdngen would
have done. ~25 lines, no geometry change.

**Upstream.** This belongs in `kdp1965/ihp-um-janestreet-prism`. The evidence
above is a complete report: a passing small case, a failing large one at two
scales, a precise mechanism, and LVS as the arbiter.
