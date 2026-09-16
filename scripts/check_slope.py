#!/usr/bin/env python3
"""Validity gate: the per-SM flop slope must match a standalone stt_core.

Guards against the instance-merging failure found while building stt_chip:
when every state machine shared one serial load chain, all NSM instances held
identical state and Yosys merged them after `flatten`. The area sweep still
looked clean and linear -- the only visible symptom was the per-SM flop slope
coming out at 754 instead of 934, understating per-SM area by ~2559 um2.

Anything that makes the SMs' contents identical again (a shared load enable, a
tied-off select, a constant programmed into all of them) would silently
reintroduce it, so this is checked rather than remembered.

Exit non-zero if the slope is off by more than --tol flops.
"""
import argparse
import glob
import json
import os
import sys


def load(build):
    runs = {}
    for p in sorted(glob.glob(os.path.join(build, "*.json"))):
        try:
            d = json.load(open(p))
        except (OSError, ValueError):
            continue
        runs[d.get("name", os.path.basename(p)[:-5])] = d
    return runs


def flops_of(run, prefer):
    mods = run["modules"]
    if prefer in mods:
        return mods[prefer]["flops"]
    cands = {k: v for k, v in mods.items() if k != "design hierarchy"}
    if not cands:
        return None
    return max(cands.values(), key=lambda m: m["area_um2"] or 0)["flops"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build", nargs="?", default="build")
    ap.add_argument("--tol", type=int, default=25,
                    help="allowed |slope - reference| in flops (default 25)")
    args = ap.parse_args()

    runs = load(args.build)

    ref_run = runs.get("core_flat")
    if not ref_run or not ref_run.get("valid"):
        print("SKIP: core_flat missing or invalid; run `make area-core`")
        return 0
    ref = flops_of(ref_run, "stt_core")

    chips = sorted((int(n[4:]), r) for n, r in runs.items()
                   if n.startswith("chip") and n[4:].isdigit() and r.get("valid"))
    if len(chips) < 2:
        print("SKIP: need >=2 valid chipN runs; run `make area-chip`")
        return 0

    pts = [(n, flops_of(r, "stt_chip")) for n, r in chips]
    n = len(pts)
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxx = sum(p[0]**2 for p in pts); sxy = sum(p[0]*p[1] for p in pts)
    slope = (n*sxy - sx*sy) / (n*sxx - sx*sx)

    print(f"per-SM flop slope : {slope:.2f}")
    print(f"standalone stt_core: {ref}")
    print(f"difference        : {slope - ref:+.2f} flops (tolerance +/-{args.tol})")
    print("  consecutive deltas: "
          + ", ".join(str(pts[i][1] - pts[i-1][1]) for i in range(1, len(pts))))

    if abs(slope - ref) > args.tol:
        print(f"\nFAIL: per-SM flop slope {slope:.2f} differs from standalone "
              f"stt_core ({ref}) by more than {args.tol} flops.")
        print("Most likely the SM instances are being merged after `flatten` "
              "because they hold identical state -- check that each SM's load "
              "enable is gated by a distinct select (stt_chip: uio_in[7:5]).")
        print("Area numbers from this sweep are INVALID.")
        return 1

    print("\nOK: per-SM flop slope matches standalone stt_core; "
          "instances are not being merged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
