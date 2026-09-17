"""Encode the six reference programs at 32 bits and dump what the RTL needs.

The testbench loads these words into rtl2's imem over the serial path and
configures the core from the same JSON, so the RTL and the Python model start
from identical programs and identical configuration. Anything the RTL needs that
is not in here is a thing the RTL invented.

Run from isa_bench/:  python3 ../rtl2/dump_programs.py
Writes rtl2/programs.json.
"""
import io
import json
import os
import sys
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "isa_bench"))

_b = io.StringIO()
with contextlib.redirect_stdout(_b):
    import programs as P
    import jtag_prog
    import rowenc
    from rowformat import Format
    from stt import ACT_ORDER

PERIOD = 32
# SPEC section 7 allows one pin write per row, so the reference set is the
# single-pin-write variants -- STT_1PIN -- which is what widthsweep.py and the
# section 13 table are measured on. The multi-pin originals in BUILDERS["STT"]
# cannot be encoded at the frozen format and are not reference programs.
BUILDERS = dict(P.STT_1PIN)
BUILDERS["jtag"] = jtag_prog.stt_jtag
ORDER = ["uart_tx", "uart_rx", "spi", "i2c", "usb", "jtag"]

# Field layout of the frozen row, from spec/isa.json. Kept here only to slice
# the packed word back apart for the human-readable dump; the packing itself is
# rowformat's.
FIELDS = [("test", 0, 4), ("mode", 4, 2), ("target", 6, 8),
          ("pin_slot", 14, 2), ("pin_op", 16, 3), ("act_sr", 19, 3),
          ("act_c1", 22, 3), ("act_c2", 25, 2), ("act_tm", 27, 2), ("act_xx", 29, 3)]

MODE_NAME = {0: "WAIT", 1: "BRANCH", 2: "SKIP", 3: "STEP"}
# Which exit the target field feeds, per SPEC section 5.
TARGET_FEEDS = {0: "true", 1: "true", 2: "false", 3: "unused"}

out = {}
ret_on_false = []

for name in ORDER:
    core, prog = BUILDERS[name](PERIOD)
    res = Format("single5", "grouped", tgt_bits=8).encode(prog)
    words = list(res["packed"])
    assert res["row_width"] == 32, res["row_width"]

    rows = []
    for i, w in enumerate(words):
        f = {n: (w >> lsb) & ((1 << wd) - 1) for n, lsb, wd in FIELDS}
        rows.append(f)
        if f["target"] == 255 and TARGET_FEEDS[f["mode"]] == "false":
            ret_on_false.append((name, i, MODE_NAME[f["mode"]]))

    out[name] = dict(
        words=words,
        rows=rows,
        nrows=len(words),
        config=dict(
            period=core.P,
            shift=core.shift,
            fill=core.fill,
            sr_width=core.w,
            cload=list(core.cvals),
            c2load=core.c2val,
            loadk=core.k,
            init_pins=list(core.pinv),
            slots=[[s[0], s[1]] for s in core.slots],
            ins=list(core.ins),
        ),
    )

print(f"{'program':9} {'rows':>5} {'slots':>6} {'ins':>4}  shift  fill   P   sr_w")
for n in ORDER:
    c = out[n]["config"]
    print(f"  {n:9} {out[n]['nrows']:>3} {len(c['slots']):>6} {len(c['ins']):>4}  "
          f"{c['shift']:<6} {c['fill']:<5} {c['period']:>3} {c['sr_width']:>4}")

print(f"\nrows whose TARGET field feeds a FALSE exit and holds 255 (RET): "
      f"{ret_on_false if ret_on_false else 'none'}")
print("  (SPEC section 5 says 255 means return; SttCore only resolves 'ret' on the")
print("   TRUE exit, so such a row would be a spec/model disagreement. None exist.)"
      if not ret_on_false else "  *** DISAGREEMENT: stop and ask ***")

json.dump(out, open(os.path.join(HERE, "programs.json"), "w"), indent=1)
print(f"\nwrote rtl2/programs.json ({sum(o['nrows'] for o in out.values())} rows total)")
