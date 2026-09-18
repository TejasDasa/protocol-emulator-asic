# Patches to the vendored prism PDN plugin

`floorplan/odb_stripes.py` and `floorplan/librelane_plugin_prism_pdn.py` are a
vendored copy of the PDN step from `kdp1965/ihp-um-janestreet-prism`, and are
gitignored for that reason. Changes to them live here as patches, so a change is
reviewable and survives a re-vendor.

Apply with:

    cd floorplan && patch -p0 < patches/<name>.patch

## `odb_stripes-annotate-macro-power.patch`

**Status: does NOT fix `PSM-0069`. Tested and refuted.** Kept because the
annotation it adds is independently correct, and because the negative result is
worth not repeating.

**What it does.** After the step draws its full-height Metal4 stripes, connect
each macro's power `ITerm` to the corresponding special net and mark it special.
The macros genuinely had no such connection: `design__disconnected_pin__count`
was exactly 2 per macro (`VPWR` and `VGND`) and
`design__critical_disconnected_pin__count` exactly 1, scaling with macro count
(2/1 per macro at two macros, 20/10 at ten). The log confirms it runs:

    [INFO] VPWR: 10 macro power pins connected in the database
    [INFO] VGND: 10 macro power pins connected in the database

**What it does not do.** `PSM-0069` still fails. Against the unpatched run:

| | unpatched | patched |
|---|---|---|
| `PSM-0038` unconnected shape | 25 | 25 |
| `PSM-0039` unconnected instance | 0 | 11 |
| `PSM-0069` | fails | fails |

**Why the original theory was wrong.** It assumed the unconnected shapes were
the stripes over macro pin columns. They are not. The 25 unconnected `VPWR`
shapes run from x = 55.82 to x = 1089.90 at the 44.96 µm stripe pitch — every
vertical Metal4 stripe across the whole core — while the macro columns sit at
only x = 45.43, 405.11 and 764.79. So PSM considers the entire stripe network
sourceless, which macro pin annotation cannot address.

**What is actually known.**

* At two macros (`pdn_test`), the same plugin and the same PDN settings give
  `PSM-0040 All shapes on net VPWR are connected` and the flow completes.
* At ten macros, in both configuration C and format D, every vertical stripe is
  reported unconnected and `PSM-0069` fails.
* Signoff DRC is clean and LVS fails only on the two power pins, in both
  formats — reachable by disabling the IR-drop step.

So it is scale-dependent and the mechanism is open. The next thing worth testing
is whether the annotation alone clears the 2 LVS unmatched pins with IR drop
disabled; the patched run quit at IR drop before reaching LVS, so that is
unmeasured.

**Not yet suitable for an upstream report.** A report needs a mechanism, and the
one that was written down turned out to be wrong.
