"""Generate floorplan/config.json: NSM state machines, 2 CFGMEM_IHP16 macros each,
on the measured 6x4 Tiny Tapeout die.

Usage: gen_config.py [NSM] [DENSITY] [HHALO] [VHALO] [LAYOUT]
       LAYOUT is "interleaved" (default) or "grouped".

Geometry is not free here. Three constraints, all derived from artifacts rather
than assumed:

  * macro x must sit on a 44.96 um grid at offset 45.43. The PDN has a single
    vertical Metal4 layer and the macro's own VPWR/VGND pin columns are on that
    pitch; off-grid, the stripes miss the pins (pdn_test/README.md).
  * macro y must be a multiple of the 3.78 um standard-cell row height.
  * the IO margin multipliers must match the hardened TT template, or the core
    silently shrinks. See CORE below.

CORE. LibreLane's defaults are BOTTOM/TOP_MARGIN_MULT 4 and LEFT/RIGHT 12; the
hardened TT template uses 1 and 6. The multipliers are in site units (3.78 um
rows, 0.48 um sites), so the defaults inset the core by 4*3.78 = 15.12 um top
and bottom and 12*0.48 = 5.76 um left and right, against the template's 3.78 and
2.88. That is 1277.76 x 680.40 = 869,369 um2 instead of 1283.52 x 703.08 =
902,417 um2 -- a 3.7% loss, and 22.68 um of vertical routing channel, in a run
that failed on local routing congestion. Measured from the ROW statements of
both floorplan DEFs, not inferred. We set the template's values.

LAYOUT. "interleaved" spreads the four macro rows through the core with logic
between them, so each machine's logic sits beside its own memory. "grouped"
packs all four rows into one contiguous block at the top with a single clear
logic region below. The second exists because the macros block Metal1-3 under
their footprint and Metal4 is the PDN layer, so there is effectively nowhere to
route above a macro: interleaving forces signals to cross four macro shadows,
grouping leaves clear channels.

The macro is 331.20 x 86.94. Three fit across the 1283.52 um core once the
column pitch is rounded UP to the next multiple of the stripe pitch (331.20 /
44.96 = 7.37, so 8 x 44.96 = 359.68). Three columns reach 45.43 + 2*359.68 +
331.20 = 1095.99; four would need 1455.67.
"""
import json
import re
import sys

NSM     = int(sys.argv[1]) if len(sys.argv) > 1 else 6
# Global placement target density. The first 6-SM run used 60, the TT template
# value, while the design sits at ~58% instance utilization once the 12 macros
# are counted -- leaving the placer almost no room to spread.
DENSITY = int(sys.argv[2]) if len(sys.argv) > 2 else 60
# Keep-out around each macro. Metal1-3 are blocked under the footprint, so cells
# packed against a macro edge can only reach Metal4, which carries the PDN.
HHALO   = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
VHALO   = float(sys.argv[4]) if len(sys.argv) > 4 else 0.48
LAYOUT  = sys.argv[5] if len(sys.argv) > 5 else "interleaved"
# The sweep runs with congestion disallowed so a bad point fails in 3 minutes
# instead of grinding through detailed routing. The FINAL run of a chosen point
# sets this, because a global-routing overflow of 1 GCell out of 355,982 at 28%
# usage is noise that detailed routing resolves -- and route__drc_errors after
# detailed routing, not GRT overflow, is the gate that decides submittability.
ALLOW   = int(sys.argv[6]) if len(sys.argv) > 6 else 0
SIGNOFF = int(sys.argv[7]) if len(sys.argv) > 7 else 0
# Which RTL tree. "C" is rtl/, the 21-bit palette format this floorplan study
# was built on; "D" is rtl2/, the implementation of the frozen row format and
# of docs/SPEC.md. C remains selectable because every physical result on record
# was measured with it, and a comparison is only a comparison if the old point
# can still be reproduced.
TREE    = sys.argv[8].upper() if len(sys.argv) > 8 else "C"
assert TREE in ("C", "D"), TREE
# Post-global-route design repair. Off by default, because every result on
# record was measured without it. The slew and capacitance violations sit on
# u_imem.do_tile -- the CFGMEM macro output driving the asynchronous read mux
# (SPEC section 12), whose real load only exists after routing -- so this is the
# pass that could buffer them. It can also move timing in either direction,
# which is why it is a separate switch and a separate run.
REPAIR  = int(sys.argv[9]) if len(sys.argv) > 9 else 0
assert LAYOUT in ("interleaved", "grouped"), LAYOUT

# ---------------------------------------------------------------- the top
# stt_chip_cfgmem.v is GENERATED from rtl/stt_chip.v rather than kept as a
# second copy, so the floorplan cannot drift from the module the area study
# measures. The only edits are the module name, the core instantiated, and NSM.
def gen_top(nsm):
    src = open("../rtl/stt_chip.v").read()
    body = src.split("\n", 2)[2]          # drop the 2-line original title comment
    body = body.replace("module stt_chip #(", "module stt_chip_cfgmem #(", 1)
    n = body.count("stt_core #(")
    assert n == 1, f"expected 1 stt_core instantiation in rtl/stt_chip.v, found {n}"
    body = body.replace("stt_core #(", "stt_core_cfgmem #(", 1)
    body, k = re.subn(r"parameter NSM {8}= \d+", f"parameter NSM        = {nsm}",
                      body, count=1)
    assert k == 1, "could not set the NSM default"
    open("stt_chip_cfgmem.v", "w").write(open("chip_header.txt").read() + body)
    return body.count("\n")


# --- die, from the hardened TT template at tiles: "6x4" (docs/area-study.md 1.3)
DIE_W, DIE_H = 1289.28, 710.64
ROW_H, SITE_W = 3.78, 0.48
BOT_MULT, TOP_MULT, LR_MULT = 1, 1, 6          # the TT template's values
CORE_X0 = LR_MULT * SITE_W                     # 2.88
CORE_Y0 = BOT_MULT * ROW_H                     # 3.78
CORE_W  = DIE_W - 2 * CORE_X0                  # 1283.52
CORE_H  = DIE_H - CORE_Y0 - TOP_MULT * ROW_H   # 703.08

# --- macro, from macro/CFGMEM_IHP16.lef
MACRO_W, MACRO_H = 331.20, 86.94

# --- PDN grid, from pdn_test/README.md "The geometry constraint"
VPITCH = 44.96
# The macro x origin is DERIVED, not chosen. What has to land on the tile stripe
# grid is the macro's VPWR/VGND PIN COLUMNS, not its origin -- the plugin draws
# a full-height stripe on each pin column, and a stripe that coincides with no
# tile stripe gets no rail vias and is electrically isolated. PSM then reports
# it (PSM-0038) and IRDropReport fails (PSM-0069).
#
# X0 = 45.43 was carried over from pdn_test, whose core origin differs. On this
# 6x4 die with margins 1/1/6/6 it puts every pin column 2.88 um -- exactly
# CORE_X0 -- off the grid, which is what made 10 macros fail where 2 passed.
# The plugin prints "pin column at x=... is 2.880 um off the nearest tile
# stripe" for all 24, and that message went unread for two configurations.
TILE_X0  = 53.99                # pdngen's first vertical stripe on this die
PIN_OFF  = 11.44                # first VPWR pin, macro-relative (CFGMEM_IHP16.lef)
X0 = round(TILE_X0 - PIN_OFF, 2)          # 42.55
COL_PITCH = VPITCH * 8          # 359.68: smallest multiple of VPITCH >= MACRO_W
COLS = [X0 + i * COL_PITCH for i in range(3)]

# --- y placement
def rows_to(um):
    """Snap a gap to whole standard-cell rows."""
    return round(um / ROW_H) * ROW_H

if LAYOUT == "interleaved":
    # gaps below / within a pair / between machines / within a pair / above,
    # in whole rows, summing to the slack
    GAPS = [13, 21, 26, 21, 13]
    YS, y = [], CORE_Y0
    for i in range(4):
        y += GAPS[i] * ROW_H
        YS.append(round(y, 2))
        y += MACRO_H
    assert abs((y + GAPS[4] * ROW_H) - (CORE_Y0 + CORE_H)) < 0.01, y
else:
    # one contiguous block at the top, a single row of clearance between macro
    # rows, and one clear logic region filling everything below it
    GAP = ROW_H
    BLOCK_H = 4 * MACRO_H + 3 * GAP
    top = CORE_Y0 + CORE_H - ROW_H                  # leave one row above
    y0 = rows_to(top - BLOCK_H)
    YS = [round(y0 + i * (MACRO_H + GAP), 2) for i in range(4)]
    assert YS[0] > CORE_Y0, YS
    LOGIC_BAND = YS[0] - CORE_Y0

for v in YS:
    assert abs(v / ROW_H - round(v / ROW_H)) < 1e-6, f"y {v} off the row grid"
    assert v >= CORE_Y0 and v + MACRO_H <= CORE_Y0 + CORE_H, f"macro y {v} outside core"
for x in COLS:
    assert abs((x - X0) / VPITCH - round((x - X0) / VPITCH)) < 1e-6, f"x {x} off grid"
# The assertion that actually matters: every macro POWER PIN COLUMN must land on
# a tile stripe. Checking the macro origin alone is what let a 2.88 um offset
# through -- the origin was on its own grid, just not on pdngen's.
for x in COLS:
    for k in range(8):
        pin = x + PIN_OFF + k * VPITCH
        off = abs((pin - TILE_X0) / VPITCH - round((pin - TILE_X0) / VPITCH)) * VPITCH
        assert off < 1e-3, (
            f"macro at x={x}: power pin column {pin:.2f} is {off:.3f} um off the "
            f"tile stripe grid ({TILE_X0} + k*{VPITCH}). The stripe drawn on it "
            f"would get no rail vias and PSM would report it unconnected.")
assert COLS[-1] + MACRO_W <= CORE_X0 + CORE_W, "columns overflow the core"

# rtl2 puts two more levels of hierarchy above the machine: the TT wrapper and
# the array. The macro geometry is identical either way -- 2 CFGMEM_IHP16 per
# machine, same footprint, same grid -- only the instance path changes.
PREFIX = "u_chip.u_array." if TREE == "D" else ""
INST   = "u_sm" if TREE == "D" else "u_core"

instances = {}
for sm in range(NSM):
    col = COLS[sm // 2]
    lo = (sm % 2) * 2           # machine 0 gets y[0],y[1]; machine 1 gets y[2],y[3]
    for t in range(2):
        instances[f"{PREFIX}g_sm[{sm}].{INST}.u_imem.g_tile[{t}].u_tile"] = {
            "location": [round(col, 2), YS[lo + t]],
            "orientation": "N",
        }

SRC_C = ["../rtl/stt_decode.v", "../rtl/stt_palette.v", "../rtl/stt_datapath.v",
         "../rtl/stt_imem_cfgmem.v", "../rtl/stt_core_cfgmem.v",
         "../rtl/stt_fifo.v", "../rtl/stt_hostbuf.v", "../rtl/stt_iomux.v",
         "../rtl/crc_lfsr16.v", "../rtl/bit_stuffer.v",
         "stt_chip_cfgmem.v"]
SRC_D = ["../rtl2/cfgmem_ihp16_bb.v", "../rtl2/stt_config.v",
         "../rtl2/stt_imem_cfgmem.v", "../rtl2/stt_core.v",
         "../rtl2/stt_top_cfgmem.v", "../rtl2/stt_array.v",
         "../rtl2/stt_fifo.v", "../rtl2/stt_hostbuf.v",
         "../rtl2/stt_hostport.v", "../rtl2/stt_iomux.v",
         "../rtl2/stt_chip.v", "../rtl2/tt_um_stt.v"]

cfg = {
    "DESIGN_NAME": "tt_um_stt" if TREE == "D" else "stt_chip_cfgmem",
    "VERILOG_FILES": ["dir::" + f for f in (SRC_D if TREE == "D" else SRC_C)],
    "VERILOG_INCLUDE_DIRS": ["dir::../rtl2" if TREE == "D" else "dir::../rtl"],
    "VERILOG_DEFINES": (["IMEM_MACRO", f"STT_NSM={NSM}"] if TREE == "D" else []),
    "CLOCK_PORT": "clk",
    "CLOCK_PERIOD": 20,                      # 50 MHz
    "FP_SIZING": "absolute",
    "DIE_AREA": f"0 0 {DIE_W} {DIE_H}",
    # match the hardened TT template; LibreLane's defaults (4/4/12/12) cost
    # 33,048 um2 of core and 22.68 um of vertical routing channel
    "BOTTOM_MARGIN_MULT": BOT_MULT,
    "TOP_MARGIN_MULT": TOP_MULT,
    "LEFT_MARGIN_MULT": LR_MULT,
    "RIGHT_MARGIN_MULT": LR_MULT,
    "MACROS": {"CFGMEM_IHP16": {
        "gds": ["dir::macro/CFGMEM_IHP16.gds"],
        "lef": ["dir::macro/CFGMEM_IHP16.lef"],
        "nl": ["dir::macro/CFGMEM_IHP16.nl.v"],
        "spef": {"nom_*": ["dir::macro/CFGMEM_IHP16.nom.spef"]},
        "lib": {"*": ["dir::macro/CFGMEM_IHP16__nom_typ_1p20V_25C.lib"]},
        "instances": instances,
    }},
    "VDD_PIN": "VPWR",
    "GND_PIN": "VGND",
    "RT_MAX_LAYER": "Metal4",
    "PDN_VERTICAL_LAYER": "Metal4",
    "PDN_HORIZONTAL_LAYER": "TopMetal1",
    "PDN_RAIL_LAYER": "Metal1",
    "PDN_RAIL_WIDTH": 0.44,
    "PDN_CONNECT_MACROS_TO_GRID": True,
    "PDN_CORE_RING": False,
    "PDN_VPITCH": VPITCH,
    "PDN_VSPACING": 3.52,
    "PDN_VWIDTH": 2.1,
    "PDN_VOFFSET": 6.15,
    "PDN_MULTILAYER": 0,
    "FP_MACRO_HORIZONTAL_HALO": HHALO,
    "FP_MACRO_VERTICAL_HALO": VHALO,
    "PL_TARGET_DENSITY_PCT": DENSITY,
    # Congestion is one of the things this run is for, so do NOT allow it.
    "GRT_ALLOW_CONGESTION": ALLOW,
    "RUN_KLAYOUT_XOR": 0,
    # The plugin never writes the ODB annotation for the stripes it adds, so
    # PSM-0069 fails on VPWR connectivity even though the geometry is verified
    # covered (verify_macro_power.py). Disabling it is what lets streamout, the
    # signoff DRC and LVS run at all; the geometric check stands in for it.
    # SIGNOFF: 0 = IR drop only (the default sweep), 1 = signoff DRC/LVS with
    # IR drop OFF, which is how signoff was reached while PSM-0069 blocked it,
    # 2 = everything on, which is what a fixed PDN annotation should allow.
    "RUN_POST_GRT_DESIGN_REPAIR": bool(REPAIR),
    "RUN_POST_GRT_RESIZER_TIMING": bool(REPAIR),
    "RUN_IRDROP_REPORT": SIGNOFF != 1,
    "RUN_KLAYOUT_DRC": SIGNOFF >= 1,
    "RUN_MAGIC_DRC": SIGNOFF >= 1,
    "RUN_LINTER": 0,
    "meta": {"flow": "Classic",
             "substituting_steps": {
                 "+OpenROAD.GeneratePDN": "Project.ExtendPowerStripes"}},
    "ERROR_ON_PDN_VIOLATIONS": 0,
    # See pdn_test/README.md: the plugin draws the stripes but never writes the
    # ODB iterm annotation, so macro power pins read as disconnected while the
    # geometry says otherwise. verify_macro_power.py is the real gate.
    "ERROR_ON_DISCONNECTED_PINS": 0,
}

lines = gen_top(NSM) if TREE == "C" else 0
json.dump(cfg, open("config.json", "w"), indent=2)

macro_area = len(instances) * MACRO_W * MACRO_H
core_area = CORE_W * CORE_H
print(f"NSM={NSM}  macros={len(instances)}  layout={LAYOUT}  density={DENSITY}%  "
      f"halo={HHALO}/{VHALO}")
print(f"  allow_congestion={ALLOW}  signoff_drc={SIGNOFF}  post_grt_repair={REPAIR}")
print(f"  tree: {TREE} -- " + ("rtl2/, the frozen format, top tt_um_stt"
      if TREE == "D" else f"rtl/, top regenerated from stt_chip.v ({lines} lines)"))
print(f"  core: {CORE_W} x {CORE_H} = {core_area:.0f} um2 "
      f"(margins {BOT_MULT}/{TOP_MULT}/{LR_MULT}/{LR_MULT})")
print(f"  columns x: {[round(c, 2) for c in COLS]}  pitch {COL_PITCH}, "
      f"right edge {round(COLS[-1] + MACRO_W, 2)} of {CORE_X0 + CORE_W}")
print(f"  rows    y: {YS}")
if LAYOUT == "grouped":
    print(f"  contiguous logic region below the block: {LOGIC_BAND:.2f} um tall, "
          f"full width")
print(f"  macro area: {len(instances)} x {MACRO_W * MACRO_H:.2f} = {macro_area:.0f} "
      f"um2 = {100 * macro_area / core_area:.1f}% of core")
