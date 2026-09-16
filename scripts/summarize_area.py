#!/usr/bin/env python3
"""Roll the per-run JSON emitted by check_area.py into the summary tables.

Reads build/*.json (written by `check_area.py --json`) and prints the tables
that docs/area-study.md is built from.  Every number here is either copied
from a Yosys `stat -liberty` line or is plain arithmetic on such numbers;
nothing is estimated.

A run whose JSON says valid=false is printed but its numbers are marked
INVALID and excluded from the totals, per the task rules.
"""
import argparse
import glob
import json
import os
import sys

# Nominal Tiny Tapeout geometry, from the competition announcement:
# 6x4 = 24 tiles ~ 0.7 mm^2.  This is the *nominal* figure, not a measured
# one; --tile-um2 overrides it once the template baseline run gives a real
# number.  Flagged as nominal in every line that uses it.
# superseded by the measured core areas below; kept for reference only
NOMINAL_24_TILE_UM2 = 700_000.0
ROW_W = 21

# 6x4 core: design__core__area from hardening the TT template at tiles "6x4"
# (916,214 die / 902,417 core). Matches the 6x4 DEF row geometry, 2674 sites
# x 0.48 by 186 rows x 3.78, exactly. See docs/area-study.md section 1.3.
CORE_6x4 = 902417.2
# 8x4 has NO DEF template and no tile_sizes entry for cmos5l: this is a
# tile-pitch extrapolation, not a flow result.
CORE_8x4 = 1208172.7


def load(build):
    runs = {}
    for p in sorted(glob.glob(os.path.join(build, "*.json"))):
        try:
            d = json.load(open(p))
        except (OSError, ValueError) as e:
            print(f"warning: cannot read {p}: {e}", file=sys.stderr)
            continue
        runs[d.get("name", os.path.basename(p)[:-5])] = d
    return runs


def top_of(run, prefer):
    """The module that is the run's top: prefer an exact name, else largest."""
    mods = run["modules"]
    if prefer in mods:
        return prefer, mods[prefer]
    cands = {k: v for k, v in mods.items() if k != "design hierarchy"}
    if not cands:
        return None, None
    k = max(cands, key=lambda m: cands[m]["area_um2"] or 0)
    return k, cands[k]


def fmt(v, w=11, p=2):
    return " " * (w - 3) + "n/a" if v is None else f"{v:{w}.{p}f}"


def table(rows, head):
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    line = lambda r: "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)) + " |"
    out = [line(head), "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    out += [line(r) for r in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build", nargs="?", default="build")
    ap.add_argument("--tile-um2", type=float, default=None,
                    help="core um2 to budget against; default is the measured 6x4 core")
    ap.add_argument("--density", type=float, default=0.50)
    args = ap.parse_args()

    runs = load(args.build)
    if not runs:
        print(f"no run JSON found in {args.build}/ -- run `make area` first", file=sys.stderr)
        return 1

    bad = [n for n, d in runs.items() if not d.get("valid", False)]
    print("# Area summary\n")
    print(f"runs found: {', '.join(sorted(runs))}")
    if bad:
        print(f"INVALID runs (excluded from totals): {', '.join(sorted(bad))}")
    print()

    # ---------------------------------------------------- hierarchical break-down
    if "core_hier" in runs and runs["core_hier"].get("valid"):
        mods = runs["core_hier"]["modules"]
        rows = []
        for name in sorted(mods, key=lambda m: -(mods[m]["area_um2"] or 0)):
            if name == "design hierarchy":
                continue
            d = mods[name]
            rows.append([name, d["cells"], fmt(d["area_um2"], 10), d["flops"],
                         fmt(d["seq_area_um2"], 10)])
        print("## stt_core, hierarchy preserved (local area, excludes submodules)\n")
        print(table(rows, ["block", "cells", "um2", "flops", "seq um2"]))
        roll = mods.get("design hierarchy")
        if roll and roll["area_um2"]:
            print(f"\nwhole-design roll-up: {roll['area_um2']:.2f} um2, "
                  f"{roll['flops']} flops")
        print()

    # ---------------------------------------------------------------- flat total
    core_area = None
    if "core_flat" in runs and runs["core_flat"].get("valid"):
        _, d = top_of(runs["core_flat"], "stt_core")
        core_area = d["area_um2"]
        print(f"## stt_core, flattened\n")
        print(f"cells {d['cells']}, flops {d['flops']}, area {core_area:.2f} um2, "
              f"sequential {d['seq_area_um2']:.2f} um2 "
              f"({100*d['seq_area_um2']/core_area:.1f}%)\n")

    # -------------------------------------------------------------- imem per bit
    imem_rows, imem_area = [], {}
    for name, rows_n in (("imem32", 32), ("imem64", 64)):
        if name not in runs or not runs[name].get("valid"):
            continue
        _, d = top_of(runs[name], "stt_imem")
        bits = rows_n * ROW_W
        imem_area[rows_n] = d["area_um2"]
        imem_rows.append([f"flops ({rows_n} rows)", rows_n, bits, d["cells"], d["flops"],
                          f"{d['area_um2']:.2f}", f"{d['area_um2']/bits:.2f}"])
    if imem_rows:
        print("## instruction memory -- variant 1, flop baseline\n")
        print(table(imem_rows, ["variant", "rows", "bits", "cells", "flops", "um2", "um2/bit"]))
        print()

    # ------------------------------------------------------------------- extras
    ex = []
    for name, label in (("crc_lfsr16", "16-bit programmable CRC/LFSR"),
                        ("bit_stuffer", "configurable bit stuffer")):
        if name not in runs or not runs[name].get("valid"):
            continue
        _, d = top_of(runs[name], name)
        ex.append([label, d["cells"], d["flops"], f"{d['area_um2']:.2f}"])
    if ex:
        print("## optional units (priced before freezing the row width)\n")
        print(table(ex, ["unit", "cells", "flops", "um2"]))
        print()

    # ------------------------------------------------- TIMER_W / variant sweeps
    # Baseline is core_timer16, NOT core_flat: passing -chparam renames the top
    # into a $paramod and changes ABC's tie-breaking, which moves the area by
    # ~0.1% with no logic change.  Comparing sweep points to each other is valid;
    # comparing them to core_flat is not.
    sweep = [n for n in runs if n.startswith("core_timer") and n[10:].isdigit()]
    sweep.sort(key=lambda n: int(n[10:]))
    if sweep:
        base = None
        if "core_timer16" in runs and runs["core_timer16"].get("valid"):
            _, bd = top_of(runs["core_timer16"], "stt_core")
            base = bd["area_um2"]
        rows = []
        prev = None
        for n in sweep:
            if not runs[n].get("valid"):
                rows.append([n, "INVALID", "", "", "", ""]); continue
            _, d = top_of(runs[n], "stt_core")
            a = d["area_um2"]
            delta = "" if base is None else f"{a-base:+.2f} ({100*(a-base)/base:+.2f}%)"
            perbit = ""
            if prev is not None:
                pw, pa = prev
                perbit = f"{(a-pa)/(int(n[10:])-pw):.2f}"
            prev = (int(n[10:]), a)
            rows.append(["TIMER_W=" + n[10:], d["cells"], d["flops"], f"{a:.2f}",
                         delta, perbit])
        print("## TIMER_W sweep (A1), baseline core_timer16\n")
        print(table(rows, ["config", "cells", "flops", "um2", "delta vs 16",
                           "um2/bit vs prev"]))
        if len(sweep) >= 2 and base is not None:
            lo, hi = sweep[0], sweep[-1]
            _, dl = top_of(runs[lo], "stt_core")
            _, dh = top_of(runs[hi], "stt_core")
            span = int(hi[10:]) - int(lo[10:])
            print(f"\nmeasured marginal cost over the whole sweep: "
                  f"({dh['area_um2']:.2f} - {dl['area_um2']:.2f}) / {span} bits "
                  f"= {(dh['area_um2']-dl['area_um2'])/span:.2f} um2 per timer bit")
            print("(flops alone account for 2 flops x 48.9888 = 97.98 um2/bit; "
                  "the rest is compare/decrement logic)")
        print()

    fifo = sorted(n for n in runs if n.startswith("core_fifo"))
    if fifo:
        rows = []
        for n in fifo:
            if not runs[n].get("valid"):
                rows.append([n, "INVALID", "", "", ""]); continue
            _, d = top_of(runs[n], "stt_core_fifo")
            delta = "" if core_area is None else f"{d['area_um2']-core_area:+.2f}"
            pct = "" if core_area is None else f"{100*(d['area_um2']-core_area)/core_area:+.1f}%"
            rows.append(["depth " + n[9:], d["cells"], d["flops"],
                         f"{d['area_um2']:.2f}", f"{delta} ({pct})"])
        print("## in-core TX+RX FIFOs (A6), vs core_flat (no in-core FIFO)\n")
        print(table(rows, ["config", "cells", "flops", "um2", "delta vs no-FIFO"]))
        print("\nThis delta is the PER-SM cost of putting the buffering inside each\n"
              "state machine. Moving it to one shared host block saves this much\n"
              "for every SM after the first.")
        print()
    roww = [n for n in runs if n.startswith("roww") and n[4:].isdigit()]
    roww.sort(key=lambda n: int(n[4:]))
    if roww:
        rows, prev = [], None
        for n in roww:
            if not runs[n].get("valid"):
                rows.append([n, "INVALID", "", "", ""]); continue
            _, d = top_of(runs[n], "stt_imem")
            w, a = int(n[4:]), d["area_um2"]
            per = "" if prev is None else f"{(a-prev[1])/(w-prev[0]):+.2f}"
            prev = (w, a)
            rows.append([f"ROW_W={w}", d["cells"], d["flops"], f"{a:.2f}", per])
        print("## row-width sensitivity (32-row imem)\n")
        print(table(rows, ["config", "cells", "flops", "um2", "um2 per row bit"]))
        if len(roww) >= 2:
            lo, hi = roww[0], roww[-1]
            _, dl = top_of(runs[lo], "stt_imem")
            _, dh = top_of(runs[hi], "stt_imem")
            span = int(hi[4:]) - int(lo[4:])
            print(f"\nmeasured: ({dh['area_um2']:.2f} - {dl['area_um2']:.2f}) / {span} "
                  f"= {(dh['area_um2']-dl['area_um2'])/span:.2f} um2 per row bit")
            print("(33 flops/bit = 32 rows + 1 staging bit; flops alone are "
                  "33 x 48.9888 = 1616.6, so the logic is the rest)")
        print()

    # ------------------------------------------- multi-SM chip: fit + solve N
    chips = [(int(n[4:]), runs[n]) for n in runs
             if n.startswith("chip") and n[4:].isdigit() and runs[n].get("valid")]
    chips.sort()
    if len(chips) >= 2:
        pts = []
        rows = []
        prev = None
        for nsm, run in chips:
            _, d = top_of(run, "stt_chip")
            a = d["area_um2"]
            pts.append((nsm, a))
            delta = "" if prev is None else f"{a-prev:.2f}"
            prev = a
            rows.append([nsm, d["cells"], d["flops"], f"{a:.2f}", delta])
        print("## multi-SM chip sweep (stt_chip at the TT boundary)\n")
        print(table(rows, ["NSM", "cells", "flops", "um2", "delta"]))

        n = len(pts)
        sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
        sxx = sum(p[0]*p[0] for p in pts); sxy = sum(p[0]*p[1] for p in pts)
        slope = (n*sxy - sx*sy) / (n*sxx - sx*sx)
        inter = (sy - slope*sx) / n
        my = sy/n
        ssr = sum((a - (inter+slope*k))**2 for k, a in pts)
        sst = sum((a - my)**2 for k, a in pts)
        r2 = 1 - ssr/sst if sst else float("nan")
        print(f"\n  area(N) = {inter:.2f} + N x {slope:.2f} um2   (R^2 = {r2:.6f})")
        print(f"  FIXED  = {inter:.2f} um2   (shared blocks, N-independent part)")
        print(f"  PER_SM = {slope:.2f} um2   (replicated + N-dependent glue)")

        budget = args.tile_um2 or CORE_6x4
        usable = budget * args.density
        nmax = (usable - inter) / slope
        print(f"\n  against {budget:.0f} um2 core at {100*args.density:.0f}% density "
              f"({usable:.0f} usable):")
        print(f"    N = ({usable:.0f} - {inter:.2f}) / {slope:.2f} = {nmax:.2f} "
              f"-> {int(nmax)} SMs")
        print("\n  density each N would need:")
        for k in range(max(1, int(nmax)-2), int(nmax)+3):
            a = inter + k*slope
            print(f"    N={k}: {a:10.0f} um2 = {100*a/budget:5.1f}% of core"
                  + ("   <- planning number" if k == int(nmax) else ""))
        print()

    # --------------------------------------------------------- fixed vs per-SM
    if core_area is not None and "core_hier" in runs and runs["core_hier"].get("valid"):
        mods = runs["core_hier"]["modules"]
        pal = mods.get("stt_palette")
        pal_fixed = mods.get("stt_palette_fixed")
        pal_load = mods.get("stt_palette_load")
        shareable = 0.0
        parts = []
        for nm, m in (("stt_palette_fixed", pal_fixed), ("stt_palette", pal)):
            if m and m["area_um2"]:
                shareable += m["area_um2"]
                parts.append(f"{nm} {m['area_um2']:.2f}")
        per_sm = core_area - shareable
        print("## fixed cost vs per-state-machine cost\n")
        print(f"shareable (fixed palette ROM + its mux): {shareable:.2f} um2  "
              f"[{', '.join(parts)}]")
        if pal_load and pal_load["area_um2"]:
            print(f"  note: stt_palette_load ({pal_load['area_um2']:.2f} um2, "
                  f"{pal_load['flops']} flops) holds the 8 per-program entries and is "
                  f"NOT shareable if SMs run different programs.")
        print(f"per-SM (decode + datapath + imem + loadable palette): {per_sm:.2f} um2")
        print()
        print("  ^ this is the naive split and is SUPERSEDED. It counts only the")
        print("    palette as shared and ignores the host buffering, CRC, stuffer,")
        print("    pin-assignment logic and chip glue. Use the fitted")
        print("    area(N) = FIXED + N x PER_SM from the chip sweep above; run")
        print("    `make area-chip` if that section is missing.")
        print()
    print("NOTE: Yosys `stat` area is standard-cell area only. It excludes the "
          "clock tree, fill and tap cells, and all routing, so it is a lower "
          "bound and is not directly comparable to the tile budget.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
