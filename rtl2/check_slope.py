"""Flop slope gate: N machines must cost exactly N times one machine.

Anything less means synthesis merged instances. That is not hypothetical -- it
happened in the area study, when every machine received the same serial load
stream, ended up holding identical state, and Yosys merged them, understating
the per-machine cost by roughly 180 flops. The per-machine load select of SPEC
section 10 is what prevents it, and this is the check that it still does.

Usage: check_slope.py <synth-log-for-N=1> <synth-log-for-N=5> [...]
Each log must have been produced by run_synth_array.sh with NSM set.
"""
import re
import sys


def flops(path):
    """(NSM, flop count). NSM comes from the file name -- run_synth_array.sh
    writes slope_<N>.log -- because the yosys log echoes enough other numbers
    that scraping it for NSM matched the wrong one."""
    m = re.search(r"slope_(\d+)\.log\Z", path)
    nsm = int(m.group(1)) if m else None
    n = None
    for line in open(path, errors="replace"):
        mm = re.search(r"^\s*(\d+)\s+\S+\s+sg13cmos5l_dfrbpq_1", line)
        if mm:
            n = int(mm.group(1))
    return nsm, n


def main():
    if len(sys.argv) < 3:
        print("usage: check_slope.py <log> <log> [...]")
        return 2
    pts = []
    for p in sys.argv[1:]:
        nsm, n = flops(p)
        if nsm is None or n is None:
            print(f"FAIL: could not read NSM or flop count from {p} "
                  f"(expected a name like slope_5.log)")
            return 1
        pts.append((nsm, n))
    pts.sort()
    base_nsm, base = pts[0]
    per = base / base_nsm
    print(f"  {'NSM':>4} {'flops':>8} {'expected':>9} {'per machine':>12}")
    bad = False
    for nsm, n in pts:
        want = per * nsm
        ok = abs(n - want) < 1e-9
        bad |= not ok
        print(f"  {nsm:>4} {n:>8} {want:>9.0f} {n/nsm:>12.1f}"
              f"{'' if ok else '   <-- NOT LINEAR'}")
    if bad:
        print("FAIL: flop count is not linear in NSM; instances are being merged")
        return 1
    print(f"OK: {per:.0f} flops per machine, exactly linear across "
          f"{', '.join(str(p[0]) for p in pts)} machines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
