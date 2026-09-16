#!/usr/bin/env python3
"""Parse a Yosys log, verify the run is valid, and emit the area numbers.

Two hard checks, as required by the task:
  1. dfflibmap must have mapped flops to real sg13cmos5l_ cells.
  2. the cell histogram must contain no leftover $-prefixed cells.
If either fails the area number is invalid and this script exits non-zero.

Yosys `stat -liberty` prints, per module:
      <count> <area|-> <label>
with cell types indented two spaces further than the summary labels, then
    Chip area for module '\\name': <float>
      of which used for sequential elements: <float> (<pct>%)
"""
import argparse
import glob
import json
import re
import sys

MOD_RE = re.compile(r"^=== (.+?) ===\s*$")
ROW_RE = re.compile(r"^(\s+)(\d+)\s+(\S+)\s+(.+?)\s*$")
AREA_RE = re.compile(r"^\s*Chip area for (top )?module '(.+)':\s+([0-9.]+)")
SEQ_RE = re.compile(r"^\s*of which used for sequential elements:\s+([0-9.]+)")

SUMMARY_LABELS = {
    "wires", "wire bits", "public wires", "public wire bits",
    "ports", "port bits", "cells", "submodules", "memories", "memory bits",
    "processes",
}

# sequential cells in sg13cmos5l: dfrbp*, dfrbpq*, sdfrbp*, sdfrbpq*, sdfbbp*
FLOP_RE = re.compile(r"^sg13cmos5l_s?dfr?b\w*$", re.I)
LATCH_RE = re.compile(r"^sg13cmos5l_dl(?!ygate)\w*$", re.I)


def parse(path):
    text = open(path, errors="replace").read()
    idx = text.rfind("Printing statistics.")
    if idx < 0:
        raise SystemExit(f"{path}: no 'Printing statistics.' block -- yosys never reached stat")
    block = text[idx:]

    mods, cur = {}, None
    for line in block.splitlines():
        m = MOD_RE.match(line)
        if m:
            cur = m.group(1).lstrip("\\")
            mods.setdefault(cur, {"stats": {}, "cells": {}, "area": None, "seq_area": None})
            continue
        if cur is None:
            continue

        m = AREA_RE.match(line)
        if m:
            is_top, name, val = bool(m.group(1)), m.group(2).lstrip("\\"), float(m.group(3))
            # "Chip area for top module" appears inside the 'design hierarchy'
            # block and is the whole-design total, not this module's local area.
            tgt = cur if (is_top or name not in mods) else name
            mods[tgt]["area"] = val
            continue
        m = SEQ_RE.match(line)
        if m:
            mods[cur]["seq_area"] = float(m.group(1))
            continue

        m = ROW_RE.match(line)
        if m:
            count, area_s, label = int(m.group(2)), m.group(3), m.group(4).strip()
            if label in SUMMARY_LABELS:
                mods[cur]["stats"][label] = count
            elif label.startswith("$paramod") or label.startswith("\\"):
                pass                       # submodule instance line
            else:
                mods[cur]["cells"][label] = count
                if area_s != "-":
                    mods[cur].setdefault("cell_area", {})[label] = float(area_s)
    return mods


def verify(mods):
    msgs, ok = [], True

    dollar, flops, latches = {}, 0, 0
    for mod, d in mods.items():
        if mod == "design hierarchy":
            continue          # whole-design roll-up; its cells are counted per module
        for cell, n in d["cells"].items():
            if cell.startswith("$"):
                dollar[f"{mod}:{cell}"] = n
            if FLOP_RE.match(cell):
                flops += n
            if LATCH_RE.match(cell):
                latches += n

    if dollar:
        ok = False
        msgs.append(f"FAIL: leftover $-prefixed cells: "
                    + ", ".join(f"{k}={v}" for k, v in sorted(dollar.items())[:8]))
    else:
        msgs.append("OK: no $-prefixed cells in the histogram")

    if flops == 0 and latches == 0:
        ok = False
        msgs.append("FAIL: dfflibmap mapped no flops -- no sg13cmos5l sequential cells found")
    else:
        msgs.append(f"OK: dfflibmap mapped {flops} flop cell(s)"
                    + (f", {latches} latch cell(s)" if latches else ""))
    return ok, msgs, flops, latches


def short(name):
    """$paramod$<hash>\\stt_imem            -> stt_imem
       $paramod\\stt_palette_fixed\\W=..  -> stt_palette_fixed
       stt_core                            -> stt_core"""
    parts = name.split("\\")
    return parts[1] if len(parts) > 1 else parts[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--name", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--comb-ok", action="store_true",
                    help="this design is legitimately combinational; do not "
                         "require dfflibmap to have mapped any flops")
    args = ap.parse_args()

    logs = []
    for pat in args.logs:
        logs.extend(sorted(glob.glob(pat)) or [pat])

    all_ok = True
    for log in logs:
        name = args.name or log.split("/")[-1].rsplit(".", 1)[0]
        mods = parse(log)
        ok, msgs, nflops, nlatch = verify(mods)
        if args.comb_ok and nflops == 0 and nlatch == 0:
            # A purely combinational block has no flops to map. The flop check
            # exists to catch dfflibmap silently failing on a sequential
            # design, not to reject combinational ones.
            ok = True
            msgs = [m.replace("FAIL: dfflibmap mapped no flops -- no sg13cmos5l "
                              "sequential cells found",
                              "OK: no flops, and --comb-ok says that is expected")
                    for m in msgs]
        all_ok &= ok

        print(f"[{name}]")
        for m in msgs:
            print(f"   {m}")
        for mod in sorted(mods, key=lambda m: -(mods[m]["area"] or 0)):
            d = mods[mod]
            fl = sum(n for c, n in d["cells"].items() if FLOP_RE.match(c))
            la = sum(n for c, n in d["cells"].items() if LATCH_RE.match(c))
            a = d["area"]
            astr = "        n/a" if a is None else f"{a:11.2f}"
            print(f"   {short(mod):22} cells={d['stats'].get('cells', 0):6} "
                  f"flops={fl:5} latches={la:4} area={astr} um2")
        if not ok:
            print(f"   -> AREA NUMBERS FOR {name} ARE INVALID")

        if args.json:
            out = {short(mod): {"raw_name": mod,
                                "cells": d["stats"].get("cells", 0),
                                "area_um2": d["area"],
                                "seq_area_um2": d["seq_area"],
                                "flops": sum(n for c, n in d["cells"].items() if FLOP_RE.match(c)),
                                "latches": sum(n for c, n in d["cells"].items() if LATCH_RE.match(c)),
                                "hist": d["cells"]}
                   for mod, d in mods.items()}
            json.dump({"name": name, "log": log, "valid": ok, "modules": out},
                      open(args.json, "w"), indent=1, sort_keys=True)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
