"""Do the six reference programs still encode BIT-IDENTICALLY after the wider
units were implemented? That is what 'the freeze survives' has to mean."""
import io, contextlib, sys, json
sys.path.insert(0, ".")
with contextlib.redirect_stdout(io.StringIO()):
    import programs as P, jtag_prog
    from rowformat import Format
    import rowenc, stt

B = dict(P.STT_1PIN); B["jtag"] = jtag_prog.stt_jtag
print("encoding-table sizes after implementing the reserved codes:")
print(f"  tests   : {len(rowenc.TESTS)}  {rowenc.TESTS}")
from rowformat import PINOPS
print(f"  pin ops : {len(PINOPS)}  {PINOPS}")
for name, ch in rowenc.GROUPS:
    print(f"  act_{name:3}: {len(ch)}")
print()
KNOWN = {"uart_tx": 5, "uart_rx": 8, "spi": 8, "i2c": 22, "usb": 16, "jtag": 25}
print(f"{'program':9} {'rows':>5} {'expected':>9}  words")
bad = 0
for n, b in B.items():
    core, prog = b(32)
    res = Format("single5", "grouped", tgt_bits=8).encode(prog)
    ok = res["rows"] == KNOWN[n] and res["row_width"] == 32
    bad += not ok
    print(f"  {n:9} {res['rows']:>3} {KNOWN[n]:>9}  "
          f"{'ok' if ok else 'ROW COUNT CHANGED'}")
print()
print("Row counts unchanged." if not bad else "FAIL: a reference program moved")

# The row-count check above is too weak on its own: it passes even when every
# WORD changes. Check the codes the spec fixes.
import json, os
SPEC = json.load(open(os.path.join("..", "spec", "isa.json")))
print("\ncode-index check (the freeze is about indices, not row counts):")
bad2 = 0
for t in SPEC["tests"]:
    got = rowenc.TESTS.index(t["name"]) if t["name"] in rowenc.TESTS else None
    ok = got == t["code"]
    bad2 += not ok
    if not ok:
        print(f"  test {t['name']}: spec says {t['code']}, models say {got}  MOVED")
for p in SPEC["pin_ops"]:
    got = PINOPS.index(p["name"]) if p["name"] in PINOPS else None
    ok = got == p["code"]
    bad2 += not ok
    if not ok:
        print(f"  pin op {p['name']}: spec {p['code']}, models {got}  MOVED")
print("  every existing code index unchanged" if not bad2
      else f"  {bad2} code(s) moved -- THE FREEZE IS BROKEN")
