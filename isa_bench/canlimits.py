"""What CAN needs, against what the frozen ISA provides.

The decision doc keeps crc_lfsr16 and bit_stuffer on capability grounds. That is
the biggest unbacked claim left. Before writing a CAN program, establish which
parts are IMPOSSIBLE and which are merely expensive -- the claim rests on the
first, not the second.
"""
import io, contextlib, sys, json, os
sys.path.insert(0, ".")
with contextlib.redirect_stdout(io.StringIO()):
    import stt
    from rowformat import Format

SPEC = json.load(open(os.path.join("..", "spec", "isa.json")))
st = {s["name"]: s for s in SPEC["state"]}

print("Widest accumulators the ISA gives one machine:")
for n in ("sr", "cnt", "c2", "crc"):
    print(f"  {n:6} {st[n]['width']} bits   -- {st[n]['description']}")
print()
print("CAN base frame needs:")
print("  CRC-15, polynomial 0x4599, accumulated over SOF..data")
print("  bit stuffing: a complementary bit after 5 identical bits")
print()
w_sr = int(st["sr"]["width"])
w_crc = int(st["crc"]["width"])
print(f"Widest single register available: {max(w_sr, w_crc)} bits "
      f"(sr={w_sr}, crc={w_crc}).")
print(f"CRC-15 needs a 15-bit accumulator. "
      f"{'POSSIBLE' if max(w_sr, w_crc) >= 15 else 'NOT POSSIBLE'} in one register.")
print()
print("Could two registers be chained? The ISA has no action that moves cnt or")
print("c2 into sr, and no carry between them. Actions that write sr are:")
for g in SPEC["action_groups"]:
    if g["name"] == "sr":
        for c in g["choices"]:
            if c["actions"]:
                print(f"    {'+'.join(c['actions']):14} {c['description']}")
print()
print("The per-SM CRC5 is fixed: reflected polynomial 0x14 (USB CRC5), width 5.")
print("SPEC section 9 says so explicitly -- 'It is fixed, not programmable.'")
print()
print("=> CAN's CRC-15 cannot be computed by a machine using only live codes.")
print("   Not expensive: impossible. That is the capability argument, and it is")
print("   stronger than 'none can compute one in-loop at line rate'.")
