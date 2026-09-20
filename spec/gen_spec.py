#!/usr/bin/env python3
"""Generate the encoding tables in docs/SPEC.md from spec/isa.json.

Every encoding table in the specification is machine-generated. Prose cannot
adjudicate between two implementations that both claim to follow it, and a
hand-typed table drifts from its source the first time anyone edits one and not
the other. So the tables live between markers:

    <!-- BEGIN GENERATED: tests -->
    ...generated, do not edit...
    <!-- END GENERATED: tests -->

  gen_spec.py            rewrite the blocks in place
  gen_spec.py --check    regenerate into memory and fail if the committed
                         document differs (this is what `make spec-check` runs)
"""
import argparse
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPEC_MD = os.path.join(ROOT, "docs", "SPEC.md")

WARN = "<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->"


def table(head, rows):
    w = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    out = ["| " + " | ".join(str(c).ljust(w[i]) for i, c in enumerate(head)) + " |",
           "|" + "|".join("-" * (x + 2) for x in w) + "|"]
    out += ["| " + " | ".join(str(c).ljust(w[i]) for i, c in enumerate(r)) + " |"
            for r in rows]
    return "\n".join(out)


def bitrange(lsb, width):
    return f"[{lsb}]" if width == 1 else f"[{lsb + width - 1}:{lsb}]"


def blocks(spec):
    b = {}

    b["row-format"] = table(
        ["bits", "width", "field", "meaning"],
        [[bitrange(f["lsb"], f["width"]), f["width"], f"`{f['name']}`", f["description"]]
         for f in spec["fields"]]
    ) + f"\n\nTotal **{spec['row_width']} bits**."

    b["tests"] = table(
        ["code", "name", "true when"],
        [[t["code"], f"`{t['name']}`", t["description"]] for t in spec["tests"]]
    )

    b["branch-modes"] = table(
        ["code", "name", "test true", "test false", "meaning"],
        [[m["code"], f"`{m['name']}`", m["on_true"], m["on_false"], m["description"]]
         for m in spec["branch_modes"]]
    )

    b["pin-slots"] = table(
        ["code", "slot", "meaning"],
        [[s["code"], f"`{s['name']}`", s["description"]] for s in spec["pin_slots"]]
    )

    b["pin-ops"] = table(
        ["code", "op", "single slot", "pair slot (code 3)"],
        [[p["code"], f"`{p['name']}`", p["single"], p["pair"]] for p in spec["pin_ops"]]
    )

    parts = []
    for g in spec["action_groups"]:
        parts.append(f"**Group `{g['name']}`** — row bits "
                     f"{bitrange(spec_field_lsb(spec, g), g['width'])}, "
                     f"group-local {bitrange(g['lsb'], g['width'])}. {g['description']}\n")
        parts.append(table(
            ["code", "actions", "meaning"],
            [[c["code"],
              ", ".join(f"`{a}`" for a in c["actions"]) if c["actions"] else "—",
              c["description"]] for c in g["choices"]]
        ))
        parts.append("")
    b["action-groups"] = "\n".join(parts).rstrip()

    # The forbidden-set rule, derived rather than asserted.
    lines = []
    for g in spec["action_groups"]:
        acts = sorted({a for c in g["choices"] for a in c["actions"]})
        multi = [c["actions"] for c in g["choices"] if len(c["actions"]) > 1]
        rule = (f"at most one of " + ", ".join(f"`{a}`" for a in acts))
        if multi:
            rule += ("; except " +
                     " and ".join("{" + ", ".join(f"`{a}`" for a in m) + "}" for m in multi)
                     + " may appear together")
        lines.append([f"`{g['name']}`", rule])
    total = 1
    for g in spec["action_groups"]:
        total *= len(g["choices"])
    b["action-rule"] = table(["group", "rule"], lines) + (
        f"\n\nAn action set is encodable in one row if and only if it satisfies every "
        f"rule above. That makes **{total}** distinct action sets reachable."
        + "\n\nEvery code in that count is implemented: the wider shared units of "
          "\u00a79 are live, not reserved, so there is no second count."
    )

    b["state"] = table(
        ["state", "width", "reset", "scope", "description"],
        [[f"`{s['name']}`", s["width"], s["reset"], s["scope"], s["description"]]
         for s in spec["state"]]
    )

    b["config"] = table(
        ["item", "description", "valid range", "used by"],
        [[f"`{c['name']}`", c["description"], c["range"],
          ", ".join(f"`{u}`" for u in c["used_by"]) if c["used_by"] else "—"]
         for c in spec["config"]]
    )

    # The section 9 unit configuration had no table at all, which is part of
    # why its ranges went unstated for as long as the rest.
    b["config-units"] = table(
        ["item", "description", "valid range"],
        [[f"`{c['name']}`", c["description"], c["range"]]
         for c in spec["config_units"]]
    )

    b["action-order"] = ("Within a row, actions take effect in this fixed order:\n\n"
                         + " → ".join(f"`{a}`" for a in spec["action_order"]))

    b["next-row-rule"] = (f"**`next` = `{spec['next_row_rule']['rule']}`.**\n\n"
                          + spec["next_row_rule"]["note"])


    pm = spec["pin_map"]
    selw = max(1, (pm["nsm"] * pm["nslot"] - 1).bit_length())
    inw = max(1, (pm["in_capable_pins"] - 1).bit_length())
    drivers = pm["nsm"] * pm["nslot"]
    inputs = pm["nsm"] * pm["nin"]
    b["pin-map"] = table(
        ["group", "width", "pin index", "can drive", "can be read"],
        [[f"`{g['name']}`", g["width"], g["index"],
          "yes" if g["out"] else "no", "yes" if g["in"] else "no"]
         for g in pm["groups"]]
    ) + "\n\nAt **" + str(pm["nsm"]) + " state machines**:\n\n" + table(
        ["quantity", "value", "from"],
        [["drivers to place", f"{drivers}", f"{pm['nsm']} machines x {pm['nslot']} slots"],
         ["output-capable pins", f"{pm['out_capable_pins']}", "`uo_out` + `uio`"],
         ["inputs to source", f"{inputs}", f"{pm['nsm']} machines x {pm['nin']} inputs"],
         ["input-capable pins", f"{pm['in_capable_pins']}", "`ui_in` + `uio`"],
         ["output select field", f"{selw} bits", f"ceil(log2({drivers}))"],
         ["output select chain", f"{pm['out_capable_pins'] * selw} bits",
          f"{pm['out_capable_pins']} pins x {selw} bits"],
         ["input select field", f"{inw} bits", f"ceil(log2({pm['in_capable_pins']}))"],
         ["input select chain", f"{inputs * inw} bits", f"{inputs} inputs x {inw} bits"],
         ["`run` flag", "1 bit", "§11.1"],
         ["host port enable", "1 bit", "§11.2"],
         ["host port pin selects", f"{2 * inw} bits", f"2 pins x {inw} bits"],
         ["**pin-assignment config total**",
          f"**{pm['out_capable_pins'] * selw + inputs * inw + 1 + 1 + 2 * inw} bits**", ""]]
    )

    hp = spec["host_port"]
    b["host-port"] = table(
        ["pin", "direction", "assigned by"],
        [[f"`{p['name']}`", p["dir"], p["assigned_by"]] for p in hp["pins"]]
    ) + f"\n\nOne transaction is **{hp['frame_bits']} clocks** of `host_stb`, MSB first.\n\n" + table(
        ["bits", "field in", "meaning"],
        [[f"`{r['bits']}`", f"`{r['field']}`", r["meaning"]] for r in hp["frame_in"]]
    ) + "\n\n" + table(
        ["bits", "field out", "meaning"],
        [[f"`{r['bits']}`", f"`{r['field']}`", r["meaning"]] for r in hp["frame_out"]]
    )

    b["pin-config-mode"] = table(
        ["pin", "role while `run` = 0"],
        [[f"`{c['pin']}`", c["role"]] for c in pm["config_mode_pins"]]
    )

    lp = spec["load_protocol"]
    b["load-protocol"] = table(
        ["requirement", "rule"],
        [[f"**{r['name']}**", r["rule"]] for r in lp["requirements"]]
    ) + "\n\n" + table(
        ["quantity", "value"],
        [["row width", f"{lp['row_bits']} bits"],
         ["imem depth", f"{lp['rows']} rows"],
         ["tiles", f"{lp['tiles']} x {lp['words_per_tile']} words"],
         ["walk after each row", f"{lp['walk_clocks_per_row']} cycles"],
         ["shift-in per row", f"{lp['row_bits']} cycles"],
         ["**total to load 32 rows**",
          f"**{lp['rows'] * (lp['row_bits'] + lp['walk_clocks_per_row'])} cycles**"]]
    )

    f = spec["fifo"]
    b["fifo"] = table(
        ["property", "value"],
        [["depth", f"{f['depth']} entries"],
         ["width", f"{f['width_bits']} bits"],
         ["scope", "per state machine" if f["per_machine"] else "shared"],
         ["binding case", f["binding_case"]],
         ["host latency at depth "
          f"{f['depth']}", f"{f['host_latency_cycles']} cycles"]]
    )

    return b


def spec_field_lsb(spec, group):
    """Absolute row-bit lsb of an action group."""
    for f in spec["fields"]:
        if f["name"] == "act_" + group["name"]:
            return f["lsb"]
    raise KeyError(group["name"])


def render(text, b):
    out = text
    for name, body in b.items():
        pat = re.compile(
            r"(<!-- BEGIN GENERATED: " + re.escape(name) + r" -->\n).*?"
            r"(<!-- END GENERATED: " + re.escape(name) + r" -->)", re.S)
        if not pat.search(out):
            continue
        out = pat.sub(lambda m: m.group(1) + WARN + "\n\n" + body + "\n\n" + m.group(2),
                      out, count=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed document differs from the source")
    args = ap.parse_args()

    spec = json.load(open(os.path.join(HERE, "isa.json")))
    b = blocks(spec)

    if not os.path.exists(SPEC_MD):
        print(f"ERROR: {SPEC_MD} does not exist", file=sys.stderr)
        return 2
    cur = open(SPEC_MD).read()
    new = render(cur, b)

    present = [n for n in b if f"<!-- BEGIN GENERATED: {n} -->" in cur]
    missing = [n for n in b if n not in present]

    if args.check:
        if cur != new:
            print("FAIL: docs/SPEC.md is out of date with spec/isa.json.")
            d = difflib.unified_diff(cur.splitlines(True), new.splitlines(True),
                                     "committed", "regenerated", n=2)
            sys.stdout.writelines(list(d)[:60])
            print("\nRun `python3 spec/gen_spec.py` and commit the result.")
            return 1
        print(f"OK: docs/SPEC.md matches spec/isa.json ({len(present)} generated blocks).")
        if missing:
            print(f"  note: source has blocks with no marker in the document: "
                  f"{', '.join(missing)}")
        return 0

    open(SPEC_MD, "w").write(new)
    print(f"wrote {len(present)} generated block(s) into docs/SPEC.md: {', '.join(present)}")
    if missing:
        print(f"  note: no marker in the document for: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
