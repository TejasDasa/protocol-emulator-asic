"""Part D device models: JTAG TAP and CAN base-frame RX.

Written the same way as devices.py, and with timing checks from the start --
the SPI/I2C models had none, which is how the timer-mutant blind spot survived
(see README, "Known validation gap").

JTAG matters more than CAN here: the TAP controller is a genuine 16-state
machine, not a bit loop, so it tests whether the ISA's branch/test structure
covers control flow rather than just serialisation.
"""
from collections import deque

# ---------------------------------------------------------------- JTAG TAP
# IEEE 1149.1 state names, indexed by the standard TMS graph.
TLR, RTI = "TestLogicReset", "RunTestIdle"
TAP_NEXT = {
    # state:        (TMS=0,           TMS=1)
    TLR:           (RTI,             TLR),
    RTI:           (RTI,             "SelectDR"),
    "SelectDR":    ("CaptureDR",     "SelectIR"),
    "SelectIR":    ("CaptureIR",     TLR),
    "CaptureDR":   ("ShiftDR",       "Exit1DR"),
    "CaptureIR":   ("ShiftIR",       "Exit1IR"),
    "ShiftDR":     ("ShiftDR",       "Exit1DR"),
    "ShiftIR":     ("ShiftIR",       "Exit1IR"),
    "Exit1DR":     ("PauseDR",       "UpdateDR"),
    "Exit1IR":     ("PauseIR",       "UpdateIR"),
    "PauseDR":     ("PauseDR",       "Exit2DR"),
    "PauseIR":     ("PauseIR",       "Exit2IR"),
    "Exit2DR":     ("ShiftDR",       "UpdateDR"),
    "Exit2IR":     ("ShiftIR",       "UpdateIR"),
    "UpdateDR":    (RTI,             "SelectDR"),
    "UpdateIR":    (RTI,             "SelectDR"),
}


class JtagTap:
    """IEEE 1149.1 TAP. Samples TMS/TDI on the TCK rising edge, drives TDO on
    the falling edge, and enforces TCK phase timing plus TMS/TDI setup.

    tck_nominal / tol: minimum TCK phase length, same convention as
    devices.SpiTarget -- a minimum, because that is how JTAG specifies clock
    timing, and it makes the check robust to propagation delay.
    setup: TMS/TDI must be stable this many cycles before the rising edge.
    """

    def __init__(self, tck, tms, tdi, tdo, ir_width=4, dr_value=0,
                 tck_nominal=None, tol=0.25, setup=1):
        self.tck, self.tms, self.tdi, self.tdo = tck, tms, tdi, tdo
        self.ir_width = ir_width
        self.state = TLR
        self.ir, self.dr = 0, dr_value
        self.dr_shifted = []        # DR values captured at each UpdateDR
        self.ir_shifted = []
        self.visited = set([TLR])
        self.prev = None
        self.tck_min = None if tck_nominal is None else tck_nominal * (1.0 - tol)
        self.last_edge_t = None
        self.setup = setup
        self._stable_since = {"tms": 0, "tdi": 0}
        self._last = {"tms": None, "tdi": None}
        self.sh = 0                 # shift register in Shift* states
        self.shn = 0

    def step(self, w):
        tck, tms, tdi = w.value(self.tck), w.value(self.tms), w.value(self.tdi)

        for nm, v in (("tms", tms), ("tdi", tdi)):
            if self._last[nm] != v:
                self._last[nm] = v
                self._stable_since[nm] = w.t

        if self.prev is None:
            self.prev = (tck, tms, tdi)
            return
        ptck, ptms, ptdi = self.prev

        if ptck != tck:
            if self.tck_min is not None and self.last_edge_t is not None:
                dur = w.t - self.last_edge_t
                if dur < self.tck_min:
                    w.error(f"jtag: TCK phase {dur} < minimum {self.tck_min:.1f} "
                            f"(master ignored its bit timer?)")
            self.last_edge_t = w.t

        if ptck == 0 and tck == 1:                      # rising: sample
            for nm in ("tms", "tdi"):
                held = w.t - self._stable_since[nm]
                if held < self.setup:
                    w.error(f"jtag: {nm.upper()} changed {held} cycles before "
                            f"the TCK rising edge (setup < {self.setup})")
            nxt = TAP_NEXT[self.state][tms]
            if self.state in ("ShiftDR", "ShiftIR"):
                self.sh = (self.sh >> 1) | (tdi << (self.shn - 1)) if self.shn else self.sh
            if self.state == "CaptureDR":
                self.sh, self.shn = self.dr, 8
            elif self.state == "CaptureIR":
                self.sh, self.shn = self.ir, self.ir_width
            elif self.state == "UpdateDR":
                pass
            if nxt == "UpdateDR" and self.state in ("Exit1DR", "Exit2DR"):
                self.dr_shifted.append(self.sh)
            if nxt == "UpdateIR" and self.state in ("Exit1IR", "Exit2IR"):
                self.ir_shifted.append(self.sh)
            self.state = nxt
            self.visited.add(nxt)
        elif ptck == 1 and tck == 0:                    # falling: drive TDO
            if self.state in ("ShiftDR", "ShiftIR"):
                w.nets[self.tdo].drive("jtag_tap", self.sh & 1)
            else:
                w.nets[self.tdo].drive("jtag_tap", None)

        self.prev = (tck, tms, tdi)


# ------------------------------------------------------------------- CAN
# ------------------------------------------------------------------- CAN
class CanRx:
    """CAN base-frame receiver: recovers the bit clock from the SOF edge,
    samples mid-bit, removes stuffing and checks the CRC-15.

    Stuffing covers SOF through the end of the CRC sequence; the delimiters,
    ACK slot and EOF that follow are sent raw. The length of the stuffed
    region is not known until the DLC has been decoded, so this is a
    structural decode rather than a fixed-length one -- which is also why the
    receiver cannot simply count edges to find the end of a frame.
    """

    CRC_POLY = 0x4599       # x^15 + x^14 + x^10 + x^8 + x^7 + x^4 + x^3 + 1

    def __init__(self, rx, bit_nominal, tol=0.25, stuff_after=5):
        self.rx = rx
        self.P = bit_nominal
        self.bit_min = bit_nominal * (1.0 - tol)
        self.stuff_after = stuff_after
        self.frames = []
        self.prev = 1
        self.start = None
        self.raw = []
        self.edges = []
        self.last_edge_t = None

    @classmethod
    def crc15(cls, bits):
        c = 0
        for b in bits:
            top = (c >> 14) & 1
            c = ((c << 1) ^ (cls.CRC_POLY if top ^ b else 0)) & 0x7FFF
        return c

    def _destuff(self):
        """De-stuff self.raw. Returns (bits, n_consumed), ("violation", i) or
        None when more raw bits are still needed."""
        bits, run, last, need, i = [], 0, None, None, 0
        while i < len(self.raw):
            b = self.raw[i]
            if last is not None and run >= self.stuff_after:
                if b == last:                   # must have been a complement
                    return ("violation", i)
                run, last, i = 1, b, i + 1
                continue
            run = run + 1 if b == last else 1
            last = b
            bits.append(b)
            i += 1
            if need is None and len(bits) >= 19:
                dlc = sum(bits[15 + k] << (3 - k) for k in range(4))
                need = 19 + 8 * min(dlc, 8) + 15
            if need is not None and len(bits) == need:
                return (bits, i)
        return None

    def step(self, w):
        v = w.value(self.rx)
        t = w.t
        if v != self.prev:
            if self.start is not None and self.last_edge_t is not None:
                dur = t - self.last_edge_t
                if dur < self.bit_min:
                    w.error(f"can: edge after {dur} cycles < minimum "
                            f"{self.bit_min:.1f} (master ignored its bit timer?)")
            self.last_edge_t = t
            self.edges.append(t)
        if self.start is None and self.prev == 1 and v == 0:
            self.start, self.raw, self.edges = t, [], [t]
            self.last_edge_t = t
        if self.start is not None:
            _k, r = divmod(t - self.start, self.P)
            if r == self.P // 2:
                self.raw.append(v)
                res = self._destuff()
                if res is not None:
                    self._finish(w, res)
        self.prev = v

    def _finish(self, w, res):
        bits, _n = res
        self.start = None
        if bits == "violation":
            w.error(f"can: stuffing violated, no complement after "
                    f"{self.stuff_after} identical bits")
            self.frames.append({"error": "stuffing"})
            return
        dlc = sum(bits[15 + k] << (3 - k) for k in range(4))
        n = 19 + 8 * dlc
        body, crc_rx = bits[:n], bits[n:n + 15]
        got = sum(b << (14 - i) for i, b in enumerate(crc_rx))
        want = self.crc15(body)
        if got != want:
            w.error(f"can: CRC-15 mismatch, got 0x{got:04x} want 0x{want:04x}")
        if bits[0] != 0:
            w.error("can: SOF not dominant")
        self.frames.append({
            "id": sum(bits[1 + k] << (10 - k) for k in range(11)),
            "rtr": bits[12], "ide": bits[13], "dlc": dlc,
            "data": [sum(body[19 + 8 * j + k] << (7 - k) for k in range(8))
                     for j in range(dlc)],
            "crc": got, "crc_ok": got == want,
        })
