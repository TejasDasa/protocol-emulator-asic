#!/usr/bin/env python3
"""Report a hard macro's area on BOTH bases, so it can be compared like-for-like.

docs/area-study.md section 0 rule 1: never compare a `stat` number to a LEF
SIZE. A macro's LEF footprint already contains its own fill, decap and antenna
cells at its own utilization; Yosys `stat` never does. Comparing the two is how
this study got the CFGMEM saving wrong twice.

This script emits both, from the macro's own artifacts:

  cell basis   sum over the gate-level netlist of each instance's liberty area,
               EXCLUDING fill/decap/antenna/tap, which are not logic.
               -> directly comparable to `stat -liberty`.
  placed basis the LEF MACRO SIZE.
               -> directly comparable to another placed area, or to a `stat`
                  figure divided by a placement density (a projection).

Usage:
  macro_area.py --lef X.lef --netlist X.nl.v --liberty foo.lib [--bits N]
"""
import argparse
import re
import sys

FILLER = re.compile(r"_(fill|decap|antenna|tap|tie)", re.I)


def liberty_areas(path):
    """cell name -> area, from a liberty file."""
    out, name = {}, None
    with open(path, errors="replace") as f:
        for line in f:
            m = re.match(r"\s*cell \(([^)]+)\)", line)
            if m:
                name = m.group(1)
                continue
            m = re.match(r"\s*area\s*:\s*([0-9.]+)", line)
            if m and name:
                out[name] = float(m.group(1))
                name = None
    return out


def netlist_histogram(path, prefix):
    """cell type -> count, from a gate-level netlist."""
    hist = {}
    pat = re.compile(r"^\s*(" + re.escape(prefix) + r"[A-Za-z0-9_]*)\s")
    with open(path, errors="replace") as f:
        for line in f:
            m = pat.match(line)
            if m:
                hist[m.group(1)] = hist.get(m.group(1), 0) + 1
    return hist


def lef_size(path):
    """(w, h) of the first MACRO ... SIZE in a LEF."""
    with open(path, errors="replace") as f:
        macro = None
        for line in f:
            m = re.match(r"\s*MACRO\s+(\S+)", line)
            if m:
                macro = m.group(1)
            m = re.match(r"\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)", line, re.I)
            if m and macro:
                return macro, float(m.group(1)), float(m.group(2))
    return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lef", required=True)
    ap.add_argument("--netlist", required=True)
    ap.add_argument("--liberty", required=True)
    ap.add_argument("--prefix", default="sg13cmos5l_")
    ap.add_argument("--bits", type=int, default=None,
                    help="storage bits, to report um2/bit on both bases")
    args = ap.parse_args()

    areas = liberty_areas(args.liberty)
    if not any(k.startswith(args.prefix) for k in areas):
        print(f"ERROR: liberty {args.liberty} has no {args.prefix}* cells -- "
              f"wrong library?", file=sys.stderr)
        return 1
    hist = netlist_histogram(args.netlist, args.prefix)
    if not hist:
        print(f"ERROR: no {args.prefix}* instances found in {args.netlist}",
              file=sys.stderr)
        return 1

    logic = filler = 0.0
    ln = fn = 0
    missing = []
    for cell, n in sorted(hist.items(), key=lambda kv: -kv[1]):
        a = areas.get(cell)
        if a is None:
            missing.append(cell)
            continue
        if FILLER.search(cell):
            filler += n * a; fn += n
        else:
            logic += n * a; ln += n
        print(f"  {n:6} x {cell:28} {a:9.4f} = {n*a:11.2f}"
              + ("   [filler]" if FILLER.search(cell) else ""))
    if missing:
        print(f"\nWARNING: not in liberty, area unknown: {', '.join(missing)}")

    name, w, h = lef_size(args.lef)
    placed = w * h if w else None

    print(f"\n  macro                : {name}")
    print(f"  logic cells          : {ln:6}  {logic:11.2f} um2   <- CELL basis")
    print(f"  fill/decap/antenna   : {fn:6}  {filler:11.2f} um2")
    print(f"  all cells            : {ln+fn:6}  {logic+filler:11.2f} um2")
    if placed:
        print(f"  LEF SIZE             : {w} x {h} = {placed:.2f} um2   <- PLACED basis")
        print(f"  logic utilization    : {100*logic/placed:.1f}% of its own footprint")
    if args.bits:
        print(f"\n  {args.bits} storage bits:")
        print(f"    cell   basis: {logic/args.bits:8.2f} um2/bit")
        if placed:
            print(f"    placed basis: {placed/args.bits:8.2f} um2/bit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
