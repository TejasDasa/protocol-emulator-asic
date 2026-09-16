"""Shared-unit reachability: what it costs in encoding space to drive
crc_lfsr16 and bit_stuffer from a row.

Background.  Four blocks were priced into the fixed budget in
docs/area-study.md and argued for on capability grounds in
docs/row-format-decision.md: crc_lfsr16, bit_stuffer, stt_hostbuf, stt_iomux.
Only two of them are unreachable, and this file is about those two.

stt_hostbuf and stt_iomux ARE reachable and always were: read the
instantiations in rtl/stt_chip.v.  hostbuf's control inputs are tx_pop /
rx_push / tx_ne, which are exactly the `load`, `push` actions and the `fifo`
test; iomux's are sm_out / sm_oe / sm_in, which are every pin op and the in0 /
in1 tests.  Their remaining inputs (host byte port, pin-assignment registers)
are host-side configuration, loaded over the serial chain that already exists.

crc_lfsr16 and bit_stuffer are the real gap.  In rtl/stt_chip.v their control
inputs are tied to raw ui_in / uio_in bits and their outputs reach nothing a
row can read.  That wiring exists only to satisfy the area harness rule that
every input be driven; it is not an architecture.  No row field reaches them.

This file answers one question and does not decide anything: if a row needs to
drive them, how many codes does that take, and are those codes free in the
frozen 32-bit row?  It proves the answer instead of asserting it, by applying
the amendment to the live encoder and re-encoding every benchmark.

Run:  python3 sharedunits.py   -> prints the tables, writes sharedunits.json
"""
import io
import json
import contextlib

_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):        # gensweep sweeps on import
    import stt
    import rowenc
    import rowformat
    from gensweep import BENCH, SRC
    from rowformat import Format

# --------------------------------------------------------------- the ask
#
# Every control input of the two units, taken from the module port lists in
# rtl/crc_lfsr16.v and rtl/bit_stuffer.v, classified into what a row has to be
# able to say and what is a per-program constant the existing serial config
# chain can carry.
#
# (unit, port, where it has to live, note)
CONTROL = [
    ("crc_lfsr16", "poly_in/poly_we",       "config", "polynomial is a per-program constant"),
    ("crc_lfsr16", "reflect_in/reflect_we", "config", "bit order is a per-program constant"),
    ("crc_lfsr16", "seed_ones",             "config", "seed value is a per-program constant"),
    ("crc_lfsr16", "seed",                  "ROW",    "frame boundary: reset the register"),
    ("crc_lfsr16", "en (as a step enable)", "ROW",    "advance by one data bit, on the rows that carry data"),
    ("crc_lfsr16", "data_bit",              "config", "source is srbit, same as the per-SM CRC5"),
    ("crc_lfsr16", "crc_bit (readback)",    "ROW",    "shift the residue out onto a pin"),
    ("bit_stuffer", "n_in/n_we",            "config", "run length is a per-program constant"),
    ("bit_stuffer", "mode_insert/mode_ones","config", "direction and counting rule are per-program constants"),
    ("bit_stuffer", "flush",                "ROW",    "frame boundary: clear the run counter"),
    ("bit_stuffer", "in_valid/in_bit",      "config", "per-slot route bit: slot output passes through the stuffer"),
    ("bit_stuffer", "in_ready (backpressure)", "ROW", "an insert stalls the producer for one bit; the program must see it"),
]

# The amendment.  Each new code is APPENDED to its field's existing code list,
# which is what makes the freeze survive: no existing code index moves.
AMENDMENT = [
    ("act_xx",  "crc16rst",  "seed the shared CRC16 (frame boundary)"),
    ("act_xx",  "crc16step", "advance the shared CRC16 by srbit"),
    ("act_xx",  "stuffrst",  "flush the bit stuffer's run counter (frame boundary)"),
    ("pin_op",  "crcb",      "drive the slot from the shared CRC16 serial bit, advancing it"),
    ("test",    "stall",     "true while the bit stuffer is inserting and not accepting a bit"),
]


def free_space():
    """Unused codes in every field of the frozen 32-bit row."""
    rows = []
    rows.append(("test", 4, len(rowenc.TESTS)))
    rows.append(("mode", 2, 4))
    rows.append(("pin_slot", 2, len(rowformat.SLOTS)))
    rows.append(("pin_op", 3, len(rowformat.PINOPS)))
    for name, choices in rowenc.GROUPS:
        rows.append((f"act_{name}", rowenc.bits_for(len(choices)), len(choices)))
    out = []
    for name, w, used in rows:
        cap = 1 << w
        out.append(dict(field=name, bits=w, used=used, cap=cap, free=cap - used))
    return out


def show_free(tag, fs):
    print(f"\n  {tag}")
    print(f"    {'field':9} {'bits':>4} {'used':>5} {'cap':>4} {'free':>5}")
    for r in fs:
        flag = "  <- FULL" if r["free"] == 0 else ""
        print(f"    {r['field']:9} {r['bits']:>4} {r['used']:>5} {r['cap']:>4} {r['free']:>5}{flag}")
    print(f"    {'total free':9} {'':>4} {'':>5} {'':>4} "
          f"{sum(r['free'] for r in fs):>5}")


def encode_all():
    """Encode every benchmark with the frozen 32-bit format.  Returns the
    packed words, so two runs can be compared literally."""
    out = {}
    for b in BENCH:
        prog = SRC[b](32)[1]
        res = Format("single5", "grouped", tgt_bits=8).encode(prog)
        out[b] = dict(words=list(res["packed"]), width=res["row_width"],
                      bits=res["bits"])
    return out


def apply_amendment():
    """Append the new codes in place.  rowformat imported GROUPS and TESTS by
    reference, so growing the lists is enough; the field widths are recomputed
    from len() at encode time."""
    groups = dict(rowenc.GROUPS)
    for field, name, _ in AMENDMENT:
        if field.startswith("act_"):
            groups[field[4:]].append((name,))
            rowenc.ACTS.append(name)
            stt.ACTS_V2_EXTRA.append(name)
        elif field == "pin_op":
            rowformat.PINOPS.append(name)
            stt.PINOPS_V2.add(name)
        elif field == "test":
            rowenc.TESTS.append(name)      # APPENDED, not re-sorted: see below
            stt.TESTS_V2.add(name)


def main():
    print("=" * 72)
    print("Shared-unit reachability: encoding cost of driving crc_lfsr16 and")
    print("bit_stuffer from a row in the frozen 32-bit format.")
    print("=" * 72)

    print("\n--- 1. what each unit's control needs, from its port list ---")
    print(f"\n  {'unit':12} {'port':26} {'lives in':8}  note")
    for unit, port, where, note in CONTROL:
        print(f"  {unit:12} {port:26} {where:8}  {note}")
    n_row = sum(1 for c in CONTROL if c[2] == "ROW")
    n_cfg = len(CONTROL) - n_row
    print(f"\n  {n_cfg} of {len(CONTROL)} controls are per-program constants "
          f"-> existing serial config chain, 0 row bits")
    print(f"  {n_row} need a row to be able to say them")

    before = free_space()
    show_free("2. free codes in the frozen row, BEFORE", before)

    print("\n--- 3. the amendment: one code each, all appended ---")
    print(f"\n  {'field':9} {'new code':11} meaning")
    for field, name, meaning in AMENDMENT:
        print(f"  {field:9} {name:11} {meaning}")

    base = encode_all()
    apply_amendment()
    after_enc = encode_all()

    print("\n--- 4. does the freeze survive?  re-encode every benchmark ---")
    print(f"\n  {'bench':9} {'rows':>5} {'width':>6} {'bits':>6}  identical to pre-amendment")
    all_same = True
    for b in BENCH:
        same = base[b]["words"] == after_enc[b]["words"] and \
               base[b]["width"] == after_enc[b]["width"]
        all_same &= same
        print(f"  {b:9} {len(after_enc[b]['words']):>5} {after_enc[b]['width']:>6} "
              f"{after_enc[b]['bits']:>6}  {'yes' if same else 'NO'}")
    print(f"\n  every benchmark bit-identical: {all_same}")
    widths = {r["width"] for r in after_enc.values()}
    print(f"  row widths after the amendment: {sorted(widths)}")

    after = free_space()
    show_free("5. free codes AFTER", after)

    over = [r for r in after if r["free"] < 0]
    print(f"\n  fields overflowed by the amendment: "
          f"{[r['field'] for r in over] if over else 'none'}")

    print("\n--- 6. what the amendment uses up ---")
    bmap = {r["field"]: r for r in before}
    for r in after:
        b = bmap[r["field"]]
        if r["used"] != b["used"]:
            print(f"  {r['field']:9} {b['used']} -> {r['used']} of {r['cap']}"
                  f"   free {b['free']} -> {r['free']}"
                  + ("   now FULL" if r["free"] == 0 else ""))

    print("\n--- 7. residual cost: act_xx and pin_op are now full ---")
    contention(before)

    json.dump(dict(control=CONTROL, amendment=AMENDMENT,
                   free_before=before, free_after=after,
                   row_widths=sorted(widths),
                   benchmarks_bit_identical=all_same,
                   fields_overflowed=[r["field"] for r in over]),
              open("sharedunits.json", "w"), indent=1)
    print("\nwrote sharedunits.json")
    return 0 if (all_same and not over) else 1



def contention(before_free):
    """The amendment costs no bits, but it fills two fields, so its new codes
    are mutually exclusive with the codes already there.  A row that wants both
    has to become two rows.  Measure how contended those two fields already are
    in the programs we have."""
    print(f"\n  {'bench':9} {'rows':>5} {'act_xx used':>12} {'pin_op used':>12}")
    tot = dict(rows=0, xx=0, po=0)
    for b in BENCH:
        prog = SRC[b](32)[1]
        lay = rowenc.best_order(prog.rows)
        xx = po = 0
        for x in lay:
            r = x["row"]
            if rowenc.encode_actions_grouped(r.act)[4]:
                xx += 1
            if any(op != "hold" for op in r.pins.values()):
                po += 1
        n = len(lay)
        tot["rows"] += n; tot["xx"] += xx; tot["po"] += po
        print(f"  {b:9} {n:>5} {xx:>12} {po:>12}")
    print(f"  {'TOTAL':9} {tot['rows']:>5} {tot['xx']:>12} {tot['po']:>12}")
    px = 100.0 * tot["xx"] / tot["rows"]
    pp = 100.0 * tot["po"] / tot["rows"]
    print(f"\n  act_xx is already non-zero on {tot['xx']}/{tot['rows']} rows ({px:.1f}%).")
    print( "  A row wanting crc16step together with call, crcrst or crcstep must")
    print( "  split into two rows; that is the whole residual cost of filling act_xx.")
    print(f"\n  pin_op is non-zero on {tot['po']}/{tot['rows']} rows ({pp:.1f}%), but crcb")
    print( "  REPLACES a slot write rather than competing with one, so act of filling")
    print( "  pin_op costs nothing today; it only forecloses a future ninth pin op.")


if __name__ == "__main__":
    raise SystemExit(main())
