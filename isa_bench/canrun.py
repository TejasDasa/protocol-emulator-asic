"""Run the CAN transmitter against the CanRx receiver and report the row cost.

The row count is the point: the decision document claims the SPEC section 9
wider units buy CAN, and until this runs that claim has nothing behind it.
"""
import sys
from collections import deque

from world import World
from can_prog import stt_can_tx, pack_frame
from jtag_can import CanRx
from rowformat import Format

P = 16          # cycles per CAN bit; the byte-boundary path needs 8


def run_frame(ident, data, period=P, verbose=False):
    core, prog = stt_can_tx(period, dlc=len(data))
    w = World([("can", 1)])                 # pull-up: recessive idle
    rx = CanRx("can", bit_nominal=period)
    w.devices.append(rx)
    payload, bits = pack_frame(ident, data)
    w.tx_fifo = deque(payload)
    frame_bits = 19 + 8 * len(data) + 15 + 13
    limit = (frame_bits + 12) * period + 64
    w.run(core, limit, lambda w: len(rx.frames) > 0)
    return core, prog, w, rx, bits


def check(ident, data):
    core, prog, w, rx, bits = run_frame(ident, data)
    if not rx.frames:
        return False, "no frame decoded"
    f = rx.frames[0]
    want_crc = CanRx.crc15(bits)
    ok = (f.get("id") == ident and f.get("data") == list(data)
          and f.get("dlc") == len(data) and f.get("crc_ok")
          and f.get("crc") == want_crc and not w.errors)
    detail = (f"id=0x{f.get('id', -1):03x} dlc={f.get('dlc')} "
              f"data={[hex(b) for b in f.get('data', [])]} "
              f"crc=0x{f.get('crc', 0):04x} crc_ok={f.get('crc_ok')}")
    if w.errors:
        detail += "  errors: " + "; ".join(w.errors[:3])
    return ok, detail


def stuffing_witness():
    """A frame whose content forces the stuffer to act, so that a pass is
    evidence the hardware stuffer ran rather than evidence it was idle."""
    core, prog, w, rx, bits = run_frame(0x000, [0x00])
    raw, clean = len(rx.raw), len(bits) + 15
    return raw, clean



# --------------------------------------------------------------- controls
# The receiver is a model in this repository, so agreement with the core is
# only worth something if the receiver can also disagree.

def crc15_longdiv(bits):
    """CRC-15 by reducing the whole message polynomial rather than stepping a
    register. A different algorithm on purpose: it is the only reason
    agreement with the core's crc16 unit means anything."""
    G = (1 << 15) | CanRx.CRC_POLY
    val = 0
    for b in bits:
        val = (val << 1) | b
    val <<= 15
    gl = G.bit_length()
    while val.bit_length() >= gl:
        val ^= G << (val.bit_length() - gl)
    return val


class Glitch:
    """Holds the line dominant for part of a bit time, to corrupt a frame in
    flight. Open drain, so driving 0 wins."""

    def __init__(self, net, t0, width):
        self.net, self.t0, self.width = net, t0, width

    def step(self, w):
        on = self.t0 <= w.t < self.t0 + self.width
        w.nets[self.net].drive("glitch", 0 if on else None)


def longest_run(raw):
    best = run = 1
    for i in range(1, len(raw)):
        run = run + 1 if raw[i] == raw[i - 1] else 1
        best = max(best, run)
    return best


def controls():
    ok = True
    _c, _p, _w, _rx, bits = run_frame(0x123, [0xA5])
    a, b = CanRx.crc15(bits), crc15_longdiv(bits)
    print(f"  {'ok ' if a == b else 'FAIL'} CRC-15 register 0x{a:04x} == "
          f"independent polynomial reduction 0x{b:04x}")
    ok &= a == b

    _c, _p, _w, rx, _b = run_frame(0x000, [0x00])
    run = longest_run(rx.raw)
    print(f"  {'ok ' if run <= 5 else 'FAIL'} longest run on the wire in the "
          f"stuffed region: {run} bits (limit 5)")
    ok &= run <= 5

    tries = list(range(6, 34, 4))
    caught = 0
    for k in tries:
        core, prog = stt_can_tx(P, dlc=1)
        w = World([("can", 1)])
        rx = CanRx("can", bit_nominal=P)
        w.devices += [rx, Glitch("can", 64 + k * P + P // 4, P // 2)]
        payload, _bits = pack_frame(0x123, [0xA5])
        w.tx_fifo = deque(payload)
        w.run(core, 90 * P, lambda w: False)
        bad = bool(w.errors) or (rx.frames and not rx.frames[0].get("crc_ok")) \
            or not rx.frames
        caught += bool(bad)
    print(f"  {'ok ' if caught == len(tries) else 'FAIL'} corrupted frames "
          f"rejected: {caught}/{len(tries)} glitch positions produced an error")
    ok &= caught == len(tries)
    return ok


def main():
    core, prog = stt_can_tx(P, dlc=1)
    r = Format("single5", "grouped", tgt_bits=8).encode(prog)
    print(f"CAN 2.0A transmitter: {len(prog.rows)} rows, "
          f"{r['row_width']}-bit rows")
    print(f"  fits in 32 rows: {len(prog.rows) <= 32}")
    print()
    cases = [(0x123, [0xA5]), (0x000, [0x00]), (0x7FF, [0xFF]),
             (0x2AA, [0x0F, 0xF0]), (0x555, [0xDE, 0xAD, 0xBE, 0xEF])]
    allok = True
    for ident, data in cases:
        ok, detail = check(ident, data)
        allok &= ok
        print(f"  {'ok ' if ok else 'FAIL'} id=0x{ident:03x} "
              f"dlc={len(data)}: {detail}")
    print()
    raw, clean = stuffing_witness()
    print(f"  stuffing witness (id 0x000, data 0x00, a long dominant run):")
    print(f"    {clean} frame bits in, {raw} bits out of the stuffed region: "
          f"{raw - clean} stuff bits inserted")
    if raw <= clean:
        print("    FAIL: the stuffer never fired, so this frame proves nothing")
        allok = False
    print()
    allok &= controls()
    print()
    print("PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
