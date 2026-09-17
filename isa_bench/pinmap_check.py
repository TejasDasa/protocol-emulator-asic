"""Gate: the pin-assignment builder must reject assignments that cannot work.

Every case here is checked in BOTH directions -- the valid plan must build, and
the broken one must raise. A validator that never fires is worth nothing, and
this repository has already shipped one of those (`sharedunits.py`).
"""
import contextlib
import io
import sys

from pinmap import PinPlan


def _programs():
    with contextlib.redirect_stdout(io.StringIO()):
        import programs as P
        import jtag_prog
    out = []
    for name in ("uart_tx", "uart_rx", "spi", "i2c"):
        out.append(P.STT_1PIN[name](32)[1])
    out.append(jtag_prog.stt_jtag(32)[1])
    return out


def expect_raise(what, fn):
    try:
        fn()
    except ValueError as e:
        print(f"  ok   rejected {what}")
        print(f"         {str(e).splitlines()[0][:96]}")
        return True
    print(f"  FAIL accepted {what}, which cannot work")
    return False


def main():
    progs = _programs()
    ok = True

    # --- the valid plan builds -------------------------------------------
    good = PinPlan()
    # Open drain must go on uio (8..15); push-pull takes whatever is free.
    # Nine push-pull slots against eight uo_out pins means some land on uio,
    # which is legal -- uio is output-capable too.
    free_od = [p for p in range(8, 16)]
    free_pp = [p for p in range(0, 16)]
    for m, prog in enumerate(progs):
        nsl = 3 if m == 4 else 2
        for s in range(nsl):
            if m == 3:                       # i2c is open drain
                pin = free_od.pop(0)
                good.drive(m, s, pin, od=True)
            else:
                pin = free_pp.pop(0)
                good.drive(m, s, pin)
            if pin in free_pp:
                free_pp.remove(pin)
            if pin in free_od:
                free_od.remove(pin)
    for m in range(5):
        for i in range(2):
            good.read(m, i, m)
    hp = [p for p in free_pp if p >= 8]
    good.host_port(dout_pin=hp[-1], stb_pin=15, din_pin=14)
    v, n = good.chain(progs)
    print(f"  ok   valid plan builds: {n}-bit chain, value 0x{v:x}")

    # --- a program that moves bytes with no host port ----------------------
    def no_host():
        p = PinPlan()
        p.drive(0, 0, 0)
        p.chain(progs)
    ok &= expect_raise("a byte-moving program with no host port", no_host)

    # --- open drain on a uo_out pin ---------------------------------------
    ok &= expect_raise("an open-drain slot on uo_out",
                       lambda: PinPlan().drive(3, 0, 2, od=True))

    # --- two drivers on one pin -------------------------------------------
    def two_drivers():
        p = PinPlan()
        p.drive(0, 0, 4)
        p.drive(1, 0, 4)
    ok &= expect_raise("two drivers on one pin", two_drivers)

    # --- the host port on a pin already driven ----------------------------
    def host_collision():
        p = PinPlan()
        p.drive(0, 0, 9)
        p.host_port(dout_pin=9, stb_pin=15, din_pin=14)
    ok &= expect_raise("the host port on an already-driven pin", host_collision)

    # --- no free output code at all ---------------------------------------
    ok &= expect_raise("16 drivers, which leave no free code for the host",
                       lambda: PinPlan(nsm=16, nslot=1))

    # --- a program that does NOT move bytes needs no host port ------------
    with contextlib.redirect_stdout(io.StringIO()):
        from stt import Row, SttProgram
    quiet = SttProgram([Row("A", "tmr", "B", pins={0: "hi"}),
                        Row("B", "tmr", "A", pins={0: "lo"})])
    PinPlan().drive(0, 0, 0).chain([quiet] + [None] * 4)
    print("  ok   a program that moves no bytes needs no host port")

    print()
    if ok:
        print("OK: the pin-assignment builder rejects every assignment that "
              "cannot work, and accepts the ones that can")
        return 0
    print("FAIL: a broken pin assignment was accepted")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
