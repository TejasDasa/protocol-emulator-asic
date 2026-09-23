"""Gate: the USB LS receiver decodes what the USB LS transmitter sends.

Loopback in the model, machine to machine: `stt_usb_1pin` drives dp/dm and
`stt_usb_rx` reads dp, exactly as the FPGA test wires them. Nothing here is a
hand-built waveform -- the stimulus IS the reference transmitter, so a decoder
that agrees with it agrees with the thing that already passes its own
benchmark.

The receiver pushes one byte per eight decoded bits, with no field structure:

    byte 0   SYNC, 0x80
    byte 1   PID
    byte 2   ADDR and the low bit of ENDP
    byte 3   the top three bits of ENDP, then CRC5

It cannot do better than that, for a reason worth stating. The ISA has no test
that reads the CRC register -- the ten test codes are always, c2z, cz, fifo,
in0h, in0l, in1h, in1l, srbit, tmr and stall -- so a receiver cannot compare
its CRC against anything. `loadcrc` moves the CRC into the shift register,
where five `srbit` tests could examine it, but that is ten-odd rows to reach a
verdict the host can reach for free. So the CRC5 arrives as data and is checked
here.
"""
import sys

from devices import crc5_usb, bits_lsb
import programs as P
from world import World

PACKETS = [(0x2D, 0x000), (0xE1, 0x3A | (0xA << 7)), (0x69, 0x7FF), (0x69, 0x001)]

# Idle bit times a host must leave between packets. Six ones is what stuffing
# allows, so the seventh is what marks the line idle; the rest is margin.
IDLE_BITS = 12


def expected(pid, field):
    crc = crc5_usb(bits_lsb(field, 11))
    return [0x80, pid, field & 0xFF, ((field >> 8) & 0x7) | (crc << 3)]


def run(period=16, packets=PACKETS, limit=None):
    tx_core, _ = P.stt_usb_1pin(period)
    rx_core, rx_prog = P.stt_usb_rx(period)
    w = World([("dp", 0), ("dm", 1), ("dec", 0)])
    w.devices = []
    # Packets are SPACED, and the receiver requires it. End of packet is SE0 --
    # both halves low -- which this receiver cannot see: it has two inputs and
    # both are spent, one on D+ and one on the decoded-bit loopback that NRZI
    # decoding needs. So it ends a packet by noticing the line has gone idle,
    # which it reads as a run of ones longer than stuffing permits. The
    # transmitter emits SE0, SE0, J and then starts the next packet at once, so
    # back to back there is one idle bit and the run never builds. A host that
    # leaves a gap -- any real one does -- is what makes framing work.
    gap = IDLE_BITS * period
    packet_cycles = 36 * period

    want = []
    for pid, field in packets:
        want += expected(pid, field)

    limit = limit or ((packet_cycles + gap) * len(packets) + 40 * period)
    w.resolve()
    nxt = 0
    for t in range(limit):
        if nxt < len(packets) and t == nxt * (packet_cycles + gap):
            pid, field = packets[nxt]
            w.tx_fifo.extend([pid, field & 0xFF, field >> 8])
            nxt += 1
        w.t = t
        w.resolve()
        tx_core.step(w)
        rx_core.step(w)
        w.resolve()
        for name, n in w.nets.items():
            w.history[name].append(n.value)
        if len(w.rx_fifo) >= len(want):
            break
    return [v & 0xFF for v in w.rx_fifo], want, rx_prog


def sweep(lo=4, hi=32):
    """The slowest bit period this receiver works at, and why there is one.

    The decoded bit is driven on a pin and read back through the two-cycle
    synchronizer before `shift` can take it, so a bit cell has to be long
    enough to hold sample, drive, two cycles of slack, shift and the byte
    check. Below that the shift picks up the previous bit.
    """
    ok = []
    for p in range(lo, hi + 1):
        got, want, _ = run(p)
        if got[:len(want)] == want:
            ok.append(p)
    return ok


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--sweep":
        ok = sweep()
        print(f"usb_rx works at periods {min(ok)}..{max(ok)}" if ok
              else "usb_rx works at NO period in 4..32")
        if ok:
            gaps = [p for p in range(min(ok), max(ok) + 1) if p not in ok]
            print(f"  minimum bit period {min(ok)} cycles"
                  + (f", gaps at {gaps}" if gaps else ", no gaps"))
        return 0 if ok else 1
    period = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    got, want, prog = run(period)
    print(f"usb_rx: {len(prog.rows)} rows of 32")
    print(f"  period {period}")
    ok = got[:len(want)] == want
    for i in range(0, min(len(want), len(got)), 4):
        g = got[i:i + 4]
        wv = want[i:i + 4]
        mark = "ok  " if g == wv else "FAIL"
        print(f"  {mark} packet {i // 4}: got {[hex(x) for x in g]} "
              f"want {[hex(x) for x in wv]}")
    if len(got) < len(want):
        print(f"  FAIL: only {len(got)} of {len(want)} bytes received")
        ok = False
    print()
    if ok:
        print("OK: the USB LS receiver decodes the reference transmitter")
        return 0
    print("FAIL: the USB LS receiver does not agree with the transmitter")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
