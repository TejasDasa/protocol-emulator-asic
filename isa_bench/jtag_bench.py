"""Part D benchmark runners for JTAG (and CAN), in the style of bench.py."""
from world import World, Host
from jtag_can import JtagTap
from jtag_prog import stt_jtag

JTAG_TOL = 0.25


def check_errors(w):
    return None if not w.errors else "; ".join(w.errors[:3])


def run_jtag(P, prog_override=None):
    core, prog = stt_jtag(P)
    if prog_override is not None:
        core.p, core.row = prog_override, 0
        prog = prog_override
    data = [0x5A, 0xC3]
    w = World([("tdi", 0), ("tck", 0), ("tms", 1), ("tdo", 1)])
    # TCK half-period is P//2 (the core's timer period), same as SPI's SCK.
    tap = JtagTap("tck", "tms", "tdi", "tdo", dr_value=0x00,
                  tck_nominal=P // 2, tol=JTAG_TOL, setup=1)
    w.devices = [Host([(lambda w: True, lambda w: w.tx_fifo.extend(data))]), tap]
    w.run(core, 400 * P + 4000, lambda w: len(tap.dr_shifted) >= len(data))
    err = check_errors(w)
    got = tap.dr_shifted[:len(data)]
    # the TAP must actually have gone through the capture/shift/update path
    need = {"RunTestIdle", "SelectDR", "CaptureDR", "ShiftDR", "Exit1DR", "UpdateDR"}
    missing = need - tap.visited
    ok = (not err and got == data and not missing)
    detail = err or (f"shifted {[hex(v) for v in got]}"
                     + (f", never reached {sorted(missing)}" if missing else ""))
    return prog, ok, detail, tap


if __name__ == "__main__":
    prog, ok, detail, tap = run_jtag(32)
    print(f"jtag  STT  {'PASS' if ok else 'FAIL'}  rows={len(prog.rows)}  {detail}")
    print(f"  TAP states visited: {len(tap.visited)} -> {sorted(tap.visited)}")
