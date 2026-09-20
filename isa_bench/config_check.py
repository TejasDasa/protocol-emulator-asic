"""Gate: the encoder must reject configuration outside the range SPEC states.

Every one of the sixteen configuration fields in docs/SPEC.md section 2 and
section 9 now carries a valid range. Four of them did not until formal
verification needed a precondition on one to prove anything and a sweep of the
rest (rtl2/formal/config_sweep.v) found the others:

  sr_width    outside 1-8 the serial bit is an out-of-range select, UNDEFINED,
              and it reaches a pin
  P           P=0 never ticks within P cycles; P=1 with `thalf` reloads 65535
  fill        the fourth encoding of a 2-bit field is unassigned
  crc16_width outside 1-16 the mask and the feedback tap disagree

Hardware stays permissive -- there is no trap, and adding one costs rows and
area for a case no program reaches. The encoder is strict. That division is
the one SttProgram already uses for d0/d1 on a single slot.

Checked in BOTH directions: every rejection must fire, and every reference
program must still build. A validator that never fires is worth nothing, and
this repository has already shipped one of those (`sharedunits.py`).
"""
import contextlib
import io

from stt import Row, SttCore, SttProgram

OK_PROG = SttProgram([Row("A", "always", "A", act=["shift"])])
HALF_PROG = SttProgram([Row("A", "always", "A", act=["thalf"])])
SLOTS = [("a", "pp"), ("b", "pp"), ("c", "od")]


def base(**kw):
    args = dict(prog=OK_PROG, slots=SLOTS, ins=("x", "y"), period=16)
    args.update(kw)
    return SttCore(**args)


def expect_raise(what, fn):
    try:
        fn()
    except ValueError as e:
        print(f"  ok   rejected {what}")
        print(f"         {str(e).splitlines()[0][:96]}")
        return True
    print(f"  FAIL accepted {what}")
    return False


def expect_ok(what, fn):
    try:
        fn()
    except Exception as e:
        print(f"  FAIL rejected a legal configuration: {what}: {e}")
        return False
    print(f"  ok   accepted {what}")
    return True


def main():
    ok = True
    print("=== out of range must be rejected ===")
    for v in (0, 9, 15, -1):
        ok &= expect_raise(f"sr_width={v}", lambda v=v: base(sr_width=v))
    for v in (0, 0x10000):
        ok &= expect_raise(f"period={v}", lambda v=v: base(period=v))
    ok &= expect_raise("period=1 with a thalf row",
                       lambda: base(prog=HALF_PROG, period=1))
    for v in (0, 17, 31):
        ok &= expect_raise(f"crc16_width={v}", lambda v=v: base(crc16_width=v))
    ok &= expect_raise("stuff_n=16", lambda: base(stuff_n=16))
    ok &= expect_raise("crc16_poly=0x10000", lambda: base(crc16_poly=0x10000))
    ok &= expect_raise("c2load=256", lambda: base(c2load=256))
    ok &= expect_raise("loadk=256", lambda: base(loadk=256))
    ok &= expect_raise("cload=(8, 0, 256)", lambda: base(cload=(8, 0, 256)))
    ok &= expect_raise("cload with two entries", lambda: base(cload=(8, 0)))
    ok &= expect_raise("fill='in1'", lambda: base(fill="in1"))
    ok &= expect_raise("fill=2 (the code, not the name)", lambda: base(fill=2))
    ok &= expect_raise("shift='up'", lambda: base(shift="up"))
    ok &= expect_raise("slot mode 'tri'",
                       lambda: base(slots=[("a", "tri")]))
    ok &= expect_raise("init_pins too short",
                       lambda: base(init_pins=[0, 1]))
    ok &= expect_raise("stuff_slots names a slot that does not exist",
                       lambda: base(stuff_slots=(5,)))

    print("\n=== the edges of every range must be accepted ===")
    for v in (1, 8):
        ok &= expect_ok(f"sr_width={v}", lambda v=v: base(sr_width=v))
    for v in (1, 0xFFFF):
        ok &= expect_ok(f"period={v}", lambda v=v: base(period=v))
    ok &= expect_ok("period=1 with no thalf row", lambda: base(period=1))
    ok &= expect_ok("period=2 with a thalf row",
                    lambda: base(prog=HALF_PROG, period=2))
    for v in (1, 16):
        ok &= expect_ok(f"crc16_width={v}", lambda v=v: base(crc16_width=v))
    for v in (0, 15):
        ok &= expect_ok(f"stuff_n={v}", lambda v=v: base(stuff_n=v))
    for v in ("0", "1", "in0"):
        ok &= expect_ok(f"fill={v!r}", lambda v=v: base(fill=v))

    print("\n=== every reference program must still build ===")
    # Every reference protocol, built and run through its own bench entry
    # point, so a range that is too tight fails here rather than in CI.
    with contextlib.redirect_stdout(io.StringIO()):
        import bench
        import jtag_bench
        runs = [("uart_tx", bench.run_uart_tx), ("uart_rx", bench.run_uart_rx),
                ("spi", bench.run_spi), ("i2c", bench.run_i2c),
                ("usb", bench.run_usb)]
        built, why = True, ""
        try:
            for _name, fn in runs:
                fn("STT", 32)
            jtag_bench.run_jtag(32)
        except Exception as e:      # noqa: BLE001 - reported, not swallowed
            built, why = False, f"{type(e).__name__}: {e}"
    if built:
        print("  ok   every benchmark builds under the new checks")
    else:
        print(f"  FAIL a reference program was rejected: {why}")
        ok = False

    print()
    if ok:
        print("OK: configuration outside the stated range is rejected at "
              "construction, and every legal value is accepted")
        return 0
    print("FAIL: a configuration check did not behave as stated")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
