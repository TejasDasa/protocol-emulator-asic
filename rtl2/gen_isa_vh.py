"""Generate rtl2/stt_isa.vh from spec/isa.json.

The decode constants are not typed by hand for the same reason the encoding
tables in docs/SPEC.md are not: a hand-copied constant is a silent divergence
waiting to happen. `make check` regenerates this and fails on any difference.

Run:  python3 gen_isa_vh.py [--check]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = json.load(open(os.path.join(HERE, "..", "spec", "isa.json")))
OUT = os.path.join(HERE, "stt_isa.vh")


def w(n):
    """Verilog width needed to hold codes 0..n-1."""
    return max(1, (n - 1).bit_length())


def main():
    L = []
    L.append("// GENERATED from spec/isa.json by rtl2/gen_isa_vh.py -- do not edit.")
    L.append("// `make check` regenerates this and fails if it differs.")
    L.append("`ifndef STT_ISA_VH")
    L.append("`define STT_ISA_VH")
    L.append("")
    L.append(f"`define STT_ROW_W   {SPEC['row_width']}")
    L.append(f"`define STT_ROWS    {SPEC['max_rows']}")
    L.append(f"`define STT_ADDR_W  {w(SPEC['max_rows'])}")
    L.append(f"`define STT_RET     8'd{SPEC['ret_code']}")
    L.append("")

    L.append("// ---- row fields: [msb:lsb] ----")
    for f in SPEC["fields"]:
        hi = f["lsb"] + f["width"] - 1
        L.append(f"`define STT_F_{f['name'].upper()}  {hi}:{f['lsb']}")
    L.append("")

    L.append("// ---- test codes ----")
    for t in SPEC["tests"]:
        L.append(f"`define STT_T_{t['name'].upper():<7} 4'd{t['code']}")
    L.append("")

    L.append("// ---- branch modes ----")
    for m in SPEC["branch_modes"]:
        L.append(f"`define STT_M_{m['name']:<7} 2'd{m['code']}")
    L.append("")

    L.append("// ---- pin slots ----")
    for s in SPEC["pin_slots"]:
        L.append(f"`define STT_SLOT_{s['name'].upper():<6} 2'd{s['code']}")
    L.append("")

    L.append("// ---- pin ops ----")
    for p in SPEC["pin_ops"]:
        L.append(f"`define STT_P_{p['name'].upper():<5} 3'd{p['code']}")
    L.append("")

    L.append("// ---- action groups: one `define per (group, choice) ----")
    for g in SPEC["action_groups"]:
        gw = w(len(g["choices"]))
        L.append(f"// group {g['name']}: {gw} bits at row bit {g['lsb']} of the action field")
        L.append(f"`define STT_AW_{g['name'].upper()} {gw}")
        for c in g["choices"]:
            acts = "_".join(a.upper() for a in c["actions"]) or "NONE"
            L.append(f"`define STT_A{g['name'].upper()}_{acts:<12} {gw}'d{c['code']}")
        L.append("")

    L.append("`endif")
    text = "\n".join(L) + "\n"

    if "--check" in sys.argv:
        cur = open(OUT).read() if os.path.exists(OUT) else ""
        if cur != text:
            print("FAIL: rtl2/stt_isa.vh is stale. Regenerate with "
                  "`python3 rtl2/gen_isa_vh.py`.")
            return 1
        print(f"OK: rtl2/stt_isa.vh matches spec/isa.json "
              f"({len(SPEC['tests'])} tests, {len(SPEC['pin_ops'])} pin ops, "
              f"{len(SPEC['action_groups'])} action groups).")
        return 0

    open(OUT, "w").write(text)
    print(f"wrote {OUT} ({len(L)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
