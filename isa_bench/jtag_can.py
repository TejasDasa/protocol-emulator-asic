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
class CanRx:
    """CAN base-frame receiver: samples a bit-stuffed NRZ stream and removes
    stuffing (a complementary bit after 5 identical). Records the de-stuffed
    frame. Enforces a minimum bit time, same convention as the others."""

    def __init__(self, rx, bit_nominal=None, tol=0.25, stuff_after=5):
        self.rx = rx
        self.bit_min = None if bit_nominal is None else bit_nominal * (1.0 - tol)
        self.stuff_after = stuff_after
        self.prev = None
        self.last_edge_t = None
        self.bits = []          # de-stuffed
        self.raw = []
        self.run_val, self.run_len = None, 0
        self.frames = []
        self.active = False

    def feed(self, b, w):
        """One raw bit: drop it if it is a stuff bit, else record it."""
        self.raw.append(b)
        if self.run_val == b:
            self.run_len += 1
        else:
            self.run_val, self.run_len = b, 1
        if self.run_len > self.stuff_after:
            w.error(f"can: {self.run_len} identical bits, stuffing violated")
        # a bit immediately following a run of `stuff_after` is a stuff bit
        if len(self.raw) >= 2 and self._prev_run == self.stuff_after and b != self.raw[-2]:
            self.run_val, self.run_len = b, 1
            return
        self.bits.append(b)

    def step(self, w):
        v = w.value(self.rx)
        if self.prev is None:
            self.prev = v
            self.last_edge_t = w.t
            return
        if v != self.prev:
            if self.bit_min is not None and self.last_edge_t is not None:
                dur = w.t - self.last_edge_t
                if dur < self.bit_min:
                    w.error(f"can: edge after {dur} cycles < minimum "
                            f"{self.bit_min:.1f} (master ignored its bit timer?)")
            self.last_edge_t = w.t
        self.prev = v
