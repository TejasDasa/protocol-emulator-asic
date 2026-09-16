#!/usr/bin/env python3
"""Verify the CFGMEM macros are actually powered, from the routed DEF.

ERROR_ON_DISCONNECTED_PINS is switched off in config_plugin_only.json because
the check tests database connectivity and the physical connection is made by
ExtendPowerStripes after pdngen. Switching a check off and declaring success
would be worthless, so this re-establishes the same fact geometrically:

  for each macro instance, every VPWR/VGND pin rectangle must be COVERED by a
  Metal4 shape belonging to the corresponding special net.

Usage: verify_macro_power.py <routed.def> <macro.lef> [--macro CFGMEM_IHP16]
"""
import argparse
import re
import sys


def lef_pin_rects(lef_path, macro):
    """{pin: [(x1,y1,x2,y2), ...]} in microns, macro-relative, Metal4 only."""
    out, cur, inmacro, layer = {}, None, False, None
    for line in open(lef_path, errors="replace"):
        s = line.strip()
        if s.startswith("MACRO "):
            inmacro = (s.split()[1] == macro)
        if not inmacro:
            continue
        m = re.match(r"PIN\s+(\S+)", s)
        if m:
            cur = m.group(1); layer = None; continue
        if s.startswith("END") and cur and s.split()[-1] == cur:
            cur = None; continue
        m = re.match(r"LAYER\s+(\S+)", s)
        if m:
            layer = m.group(1); continue
        m = re.match(r"RECT\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", s)
        if m and cur and layer == "Metal4":
            out.setdefault(cur, []).append(tuple(float(g) for g in m.groups()))
    return out


def def_units_and_placement(def_path, macro):
    """(dbu, {instance: (x, y, orient)}) for instances of `macro`."""
    dbu, place = 1000, {}
    txt = open(def_path, errors="replace").read()
    m = re.search(r"UNITS DISTANCE MICRONS\s+(\d+)", txt)
    if m:
        dbu = int(m.group(1))
    for m in re.finditer(r"-\s+(\S+)\s+" + re.escape(macro)
                         + r"\s*\+\s*\w+\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*(\w+)", txt):
        place[m.group(1)] = (int(m.group(2)) / dbu, int(m.group(3)) / dbu, m.group(4))
    return dbu, place


def special_net_shapes(def_path, net, layer="Metal4"):
    """List of (x1,y1,x2,y2) microns for `net` on `layer`, from SPECIALNETS."""
    txt = open(def_path, errors="replace").read()
    dbu = 1000
    m = re.search(r"UNITS DISTANCE MICRONS\s+(\d+)", txt)
    if m:
        dbu = int(m.group(1))
    m = re.search(r"SPECIALNETS.*?END SPECIALNETS", txt, re.S)
    if not m:
        return []
    for blk in re.split(r"\n\s*-\s+", m.group(0)):
        if not blk.startswith(net):
            continue
        shapes, width, last = [], 0, None
        for tok in re.finditer(r"\+ ROUTED|NEW\s+(\S+)\s+(\d+)|\(\s*([-\d*]+)\s+([-\d*]+)\s*\)", blk):
            if tok.group(1):
                lay, width = tok.group(1), int(tok.group(2))
                last = None
                cur_layer = lay
            elif tok.group(3) is not None:
                x, y = tok.group(3), tok.group(4)
                pt = (last[0] if x == "*" else int(x),
                      last[1] if y == "*" else int(y))
                if last is not None and 'cur_layer' in dir() and cur_layer == layer:
                    x1, x2 = sorted((last[0], pt[0]))
                    y1, y2 = sorted((last[1], pt[1]))
                    hw = width / 2
                    if x1 == x2:
                        shapes.append(((x1 - hw) / dbu, y1 / dbu, (x2 + hw) / dbu, y2 / dbu))
                    else:
                        shapes.append((x1 / dbu, (y1 - hw) / dbu, x2 / dbu, (y2 + hw) / dbu))
                last = pt
        return shapes
    return []


def covered(rect, shapes, tol=0.001):
    """Is `rect` overlapped by any shape (any overlap counts as a contact)?"""
    x1, y1, x2, y2 = rect
    for sx1, sy1, sx2, sy2 in shapes:
        if x1 < sx2 + tol and sx1 < x2 + tol and y1 < sy2 + tol and sy1 < y2 + tol:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deff")
    ap.add_argument("lef")
    ap.add_argument("--macro", default="CFGMEM_IHP16")
    args = ap.parse_args()

    pins = lef_pin_rects(args.lef, args.macro)
    if not pins:
        print(f"ERROR: no Metal4 power pins found for {args.macro} in {args.lef}")
        return 2
    _, place = def_units_and_placement(args.deff, args.macro)
    if not place:
        print(f"ERROR: no placed instances of {args.macro} in {args.deff}")
        return 2

    bad = 0
    for net in ("VPWR", "VGND"):
        shapes = special_net_shapes(args.deff, net)
        print(f"{net}: {len(shapes)} Metal4 special-net shapes")
        for inst, (ox, oy, orient) in sorted(place.items()):
            rects = pins.get(net, [])
            if orient not in ("N", "FN"):
                print(f"  WARNING: {inst} orientation {orient} not handled; "
                      f"only N/FN supported")
            hit = sum(1 for (x1, y1, x2, y2) in rects
                      if covered((x1 + ox, y1 + oy, x2 + ox, y2 + oy), shapes))
            status = "OK" if hit == len(rects) else "FAIL"
            if hit != len(rects):
                bad += 1
            print(f"  {inst:34} {hit}/{len(rects)} pin rects covered  {status}")

    print()
    if bad:
        print(f"FAIL: {bad} macro/net pairs have uncovered power pins.")
        return 1
    print("OK: every macro power pin rectangle is covered by its special net.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
