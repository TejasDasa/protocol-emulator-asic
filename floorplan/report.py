"""Pull the numbers that decide whether 6 state machines is a submittable design.

Usage: report.py <run_dir>

Reads the final metrics JSON and the STA summaries. Prints nothing it did not
read from a file; a metric that is absent is printed as MISSING rather than
guessed at.
"""
import json
import os
import re
import sys

run = sys.argv[1]

# ---- final metrics ---------------------------------------------------------
final = os.path.join(run, "final", "metrics.json")
if not os.path.exists(final):
    steps = sorted(d for d in os.listdir(run) if os.path.isdir(os.path.join(run, d)))
    cand = [os.path.join(run, d, "metrics.json") for d in reversed(steps)]
    final = next((c for c in cand if os.path.exists(c)), None)
    print(f"(no final/metrics.json; using {final})")
m = json.load(open(final)) if final else {}

GROUPS = [
    ("placement and area", [
        "design__die__area", "design__core__area",
        "design__instance__area", "design__instance__area__macros",
        "design__instance__utilization", "design__instance__count",
        "design__instance__count__macros",
    ]),
    ("power grid", [
        "design__power_grid_violation__count",
        "design__critical_disconnected_pin__count",
        "design__disconnected_pin__count",
    ]),
    ("routing", [
        "route__wirelength", "route__drc_errors",
        "route__antenna_violation__count", "route__congestion__overflow",
    ]),
    ("timing, 50 MHz (CLOCK_PERIOD 20 ns)", [
        "timing__setup__ws", "timing__setup__wns", "timing__setup__tns",
        "timing__hold__ws", "timing__hold__wns", "timing__hold__tns",
        "timing__setup_violation__count", "timing__hold_violation__count",
        "clock__skew__worst", "design__max_slew_violation__count",
        "design__max_cap_violation__count", "design__max_fanout_violation__count",
    ]),
]

for title, keys in GROUPS:
    print(f"\n--- {title} ---")
    for k in keys:
        hits = {kk: v for kk, v in m.items() if kk == k or kk.startswith(k + "__")}
        if not hits:
            print(f"  {k:52} MISSING")
            continue
        for kk in sorted(hits):
            v = hits[kk]
            print(f"  {kk:52} {v}")

# ---- anything that looks like a violation and is non-zero ------------------
print("\n--- every non-zero *violation*/*error* metric ---")
bad = {k: v for k, v in m.items()
       if re.search(r"violation|error|_drc|unmapped|disconnected", k)
       and isinstance(v, (int, float)) and v}
for k in sorted(bad):
    print(f"  {k:52} {bad[k]}")
if not bad:
    print("  none")
