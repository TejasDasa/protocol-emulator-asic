"""Record which encoded field values are actually executed.

tb/coverage.py measures this for the six reference programs. The mutation test
uses the same accounting so the two numbers are comparable: the point of running
mutants is to reach decode paths the reference set never takes, and that claim
should be a measurement rather than an assumption.
"""
import json
import os
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", ".."))
with open(os.path.join(ROOT, "spec", "isa.json")) as _f:
    SPEC = json.load(_f)
FIELDS = {f["name"]: (f["lsb"], f["width"]) for f in SPEC["fields"]}

CAPS = {
    "test": len(SPEC["tests"]),
    "mode": len(SPEC["branch_modes"]),
    "pin_slot": len(SPEC["pin_slots"]),
    "pin_op": len(SPEC["pin_ops"]),
}
for g in SPEC["action_groups"]:
    CAPS["act_" + g["name"]] = len(g["choices"])


class CodeCoverage:
    def __init__(self):
        self.seen = defaultdict(set)

    def record(self, word):
        for f, (lsb, wd) in FIELDS.items():
            if f == "target":
                continue
            self.seen[f].add((word >> lsb) & ((1 << wd) - 1))

    def summary(self):
        hit = sum(len(self.seen[f] & set(range(c))) for f, c in CAPS.items())
        cap = sum(CAPS.values())
        return hit, cap

    def missing(self):
        out = {}
        for f, c in CAPS.items():
            gap = sorted(set(range(c)) - self.seen[f])
            if gap:
                out[f] = gap
        return out
