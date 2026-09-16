"""Generate floorplan/config.json: NSM state machines, 2 CFGMEM_IHP16 macros each,
on the measured 6x4 Tiny Tapeout die.

Geometry is not free here. Two constraints come from pdn_test/README.md, both
derived from artifacts rather than copied:

  * macro x must sit on a 44.96 um grid at offset 45.43, because the PDN has a
    single vertical Metal4 layer and the macro's own VPWR/VGND pin columns are
    on that pitch. Off-grid and the stripes miss the pins.
  * macro y must be a multiple of the 3.78 um standard-cell row height, or the
    macro does not sit on a site row.

The macro is 331.20 x 86.94. Three fit across the 1283.52 um core if the column
pitch is rounded UP to the next multiple of the stripe pitch: 331.20 / 44.96 =
7.37, so 8 x 44.96 = 359.68. Three columns reach 45.43 + 2*359.68 + 331.20 =
1095.99, inside the core with 187 um to spare. Four would need 1455.67.

Each state machine's two macros are stacked in the same column, 79.38 um apart,
so its logic can place beside its own memory. Two state machines per column,
three columns: NSM = 6.

Run:  python3 gen_config.py [NSM]   -> writes config.json
"""
import json
import re
import sys

NSM = int(sys.argv[1]) if len(sys.argv) > 1 else 6


# ---------------------------------------------------------------- the top
# stt_chip_cfgmem.v is GENERATED from rtl/stt_chip.v rather than kept as a
# second copy, so the floorplan cannot drift from the module the area study
# measures. The only edits are the module name, the core instantiated, and NSM.
HEADER = open("chip_header.txt").read()


def gen_top(nsm):
    src = open("../rtl/stt_chip.v").read()
    body = src.split("\n", 2)[2]          # drop the 2-line original title comment
    body = body.replace("module stt_chip #(", "module stt_chip_cfgmem #(", 1)
    n = body.count("stt_core #(")
    assert n == 1, f"expected 1 stt_core instantiation in rtl/stt_chip.v, found {n}"
    body = body.replace("stt_core #(", "stt_core_cfgmem #(", 1)
    body, k = re.subn(r"parameter NSM {8}= \d+", f"parameter NSM        = {nsm}", body, count=1)
    assert k == 1, "could not set the NSM default"
    open("stt_chip_cfgmem.v", "w").write(HEADER + body)
    return body.count("\n")


# --- die, from the hardened TT template at tiles: "6x4" (docs/area-study.md 1.3)
DIE_W, DIE_H = 1289.28, 710.64
CORE_X0, CORE_Y0 = 2.88, 3.78
CORE_W, CORE_H = 1283.52, 703.08

# --- macro, from macro/CFGMEM_IHP16.lef
MACRO_W, MACRO_H = 331.20, 86.94

# --- PDN grid, from pdn_test/README.md "The geometry constraint"
VPITCH = 44.96
X0 = 45.43                      # first on-grid x that clears the core edge
ROW_H = 3.78                    # standard cell row height; macro y must be a multiple

COL_PITCH = VPITCH * 8          # 359.68: smallest multiple of VPITCH >= MACRO_W
COLS = [X0 + i * COL_PITCH for i in range(3)]

# --- y: 4 macros per column, gaps in whole rows, balanced top and bottom
#     gaps below / between-a-pair / between-SMs / between-a-pair / above
GAPS = [13, 21, 26, 21, 13]     # in rows of 3.78 um; sum*3.78 = 355.32 = slack
YS = []
y = CORE_Y0
for i in range(4):
    y += GAPS[i] * ROW_H
    YS.append(round(y, 2))
    y += MACRO_H
assert abs((y + GAPS[4] * ROW_H) - (CORE_Y0 + CORE_H)) < 0.01, y
for v in YS:
    assert abs(v / ROW_H - round(v / ROW_H)) < 1e-6, f"y {v} off the row grid"
for x in COLS:
    assert abs((x - X0) / VPITCH - round((x - X0) / VPITCH)) < 1e-6, f"x {x} off grid"
assert COLS[-1] + MACRO_W <= CORE_X0 + CORE_W, "columns overflow the core"

instances = {}
for sm in range(NSM):
    col = COLS[sm // 2]
    lo = (sm % 2) * 2           # SM 0 gets y[0],y[1]; SM 1 gets y[2],y[3]
    for t in range(2):
        instances[f"g_sm[{sm}].u_core.u_imem.g_tile[{t}].u_tile"] = {
            "location": [round(col, 2), YS[lo + t]],
            "orientation": "N",
        }

cfg = {
    "DESIGN_NAME": "stt_chip_cfgmem",
    "VERILOG_FILES": ["dir::" + f for f in [
        "../rtl/stt_decode.v", "../rtl/stt_palette.v", "../rtl/stt_datapath.v",
        "../rtl/stt_imem_cfgmem.v", "../rtl/stt_core_cfgmem.v",
        "../rtl/stt_fifo.v", "../rtl/stt_hostbuf.v", "../rtl/stt_iomux.v",
        "../rtl/crc_lfsr16.v", "../rtl/bit_stuffer.v",
        "stt_chip_cfgmem.v",
    ]],
    "VERILOG_INCLUDE_DIRS": ["dir::../rtl"],
    "CLOCK_PORT": "clk",
    "CLOCK_PERIOD": 20,                      # 50 MHz
    "FP_SIZING": "absolute",
    "DIE_AREA": f"0 0 {DIE_W} {DIE_H}",
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
    "FP_MACRO_HORIZONTAL_HALO": 2.0,
    "FP_MACRO_VERTICAL_HALO": 0.48,
    "PL_TARGET_DENSITY_PCT": 60,
    # Congestion is one of the things this run is for, so do NOT allow it.
    "GRT_ALLOW_CONGESTION": 0,
    "RUN_KLAYOUT_XOR": 0,
    "RUN_KLAYOUT_DRC": 0,
    "RUN_MAGIC_DRC": 0,
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

lines = gen_top(NSM)
json.dump(cfg, open("config.json", "w"), indent=2)
print(f"NSM={NSM}  macros={len(instances)}  top regenerated from ../rtl/stt_chip.v ({lines} lines)")
print(f"  columns x: {[round(c,2) for c in COLS]}  (pitch {COL_PITCH}, "
      f"right edge {round(COLS[-1]+MACRO_W,2)} of {CORE_X0+CORE_W})")
print(f"  rows    y: {YS}  (macro height {MACRO_H})")
print(f"  macro area: {len(instances)} x {round(MACRO_W*MACRO_H,2)} = "
      f"{round(len(instances)*MACRO_W*MACRO_H,2)} um2 of "
      f"{round(CORE_W*CORE_H,2)} um2 core "
      f"({100*len(instances)*MACRO_W*MACRO_H/(CORE_W*CORE_H):.1f}%)")
