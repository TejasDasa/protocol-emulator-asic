"""Far-side device models. Each one checks protocol correctness independently of the ISA."""
import random


def crc5_usb(bits):
    """USB CRC5 over bits in transmission order (LSB first). Returns the 5-bit field value
    as transmitted LSB first."""
    crc = 0x1F
    for b in bits:
        if (crc ^ b) & 1:
            crc = (crc >> 1) ^ 0x14
        else:
            crc >>= 1
    return (~crc) & 0x1F


def bits_lsb(value, n):
    return [(value >> i) & 1 for i in range(n)]


def edge_jitter(edges, t0, period):
    """Largest distance of any edge from the ideal bit grid starting at t0."""
    worst = 0
    for e in edges:
        off = (e - t0) % period
        worst = max(worst, min(off, period - off))
    return worst


# ---------------------------------------------------------------- UART
class UartMonitor:
    """Decodes 8N1 frames on a line and measures edge placement."""

    def __init__(self, net, period):
        self.net, self.P = net, period
        self.frames = []            # (byte, stop_ok)
        self.jitter = 0
        self.prev = 1
        self.start = None
        self.edges = []

    def step(self, w):
        v = w.value(self.net)
        t = w.t
        if v != self.prev and self.start is not None:
            self.edges.append(t)
        if self.start is None and self.prev == 1 and v == 0:
            self.start, self.bits, self.edges = t, [], [t]
        if self.start is not None:
            k, r = divmod(t - self.start, self.P)
            if r == self.P // 2:
                self.bits.append(v)
                if k == 9:
                    start_ok = self.bits[0] == 0
                    byte = sum(b << i for i, b in enumerate(self.bits[1:9]))
                    if not start_ok:
                        w.error("uart: bad start bit")
                    self.frames.append((byte, self.bits[9] == 1))
                    self.jitter = max(self.jitter,
                                      edge_jitter(self.edges, self.start, self.P))
                    self.start = None
        self.prev = v


class UartDriver:
    """Drives frames onto a line. frames: list of (byte, good_stop)."""

    def __init__(self, net, period, frames, t0=40, gap_bits=2):
        self.net = net
        self.wave = {}
        t = t0
        for byte, good in frames:
            bits = [0] + bits_lsb(byte, 8) + [1 if good else 0]
            for b in bits:
                for i in range(period):
                    self.wave[t + i] = b
                t += period
            if not good:        # line held low a little longer, then idle
                for i in range(period):
                    self.wave[t + i] = 0
                t += period
            t += gap_bits * period
        self.end = t

    def step(self, w):
        w.nets[self.net].drive("uart_drv", self.wave.get(w.t, 1))


# ---------------------------------------------------------------- SPI
class SpiTarget:
    """Mode 0 SPI target. Records each transaction's bytes and replies from a list."""

    def __init__(self, cs, sck, mosi, miso, replies,
                 sck_nominal=None, tol=0.25):
        """sck_nominal: expected SCK half-period in cycles. When given, every
        SCK phase while CS is low must last at least sck_nominal*(1-tol).

        This is a MINIMUM, not an equality, which is how SPI and I2C specify
        clock timing (t_HIGH / t_LOW are minimums) and what makes the check
        survive propagation delay and clock jitter. `tol` is deliberate slack,
        not measurement noise: tighten it to test timing margin, loosen it to
        allow a sloppier master. A program that ignores its timer collapses the
        phase to one or two cycles and fails at any sane tolerance."""
        self.cs, self.sck, self.mosi, self.miso = cs, sck, mosi, miso
        self.sck_min = None if sck_nominal is None else sck_nominal * (1.0 - tol)
        self.last_edge_t = None
        self.replies = list(replies)
        self.transactions = []
        self.prev = None
        self.active = False

    def _load(self, w, pending=False):
        self.tx = self.replies.pop(0) if self.replies else 0
        self.pending = pending
        w.nets[self.miso].drive("spi_tgt", (self.tx >> 7) & 1)

    def step(self, w):
        cs, sck, mosi = w.value(self.cs), w.value(self.sck), w.value(self.mosi)
        if self.prev is None:
            self.prev = (cs, sck, mosi)
            return
        pcs, psck, pmosi = self.prev

        if psck != sck:                     # SCK edge: check the phase just ended
            if (self.sck_min is not None and self.active
                    and self.last_edge_t is not None):
                dur = w.t - self.last_edge_t
                if dur < self.sck_min:
                    w.error(f"spi: SCK phase {dur} cycles < minimum "
                            f"{self.sck_min:.1f} (master ignored its bit timer?)")
            self.last_edge_t = w.t

        if pcs == 1 and cs == 0:
            if sck != 0:
                w.error("spi: CS fell with SCK high")
            self.active, self.nbits, self.rx, self.cur = True, 0, 0, []
            self._load(w)
        elif pcs == 0 and cs == 1:
            if self.active:
                if self.nbits % 8:
                    w.error(f"spi: transaction ended after {self.nbits} bits")
                if psck != 0:
                    w.error("spi: CS rose with SCK high")
                self.transactions.append(self.cur)
                if self.pending:        # byte was preloaded but never clocked out
                    self.replies.insert(0, self.tx)
            self.active = False
            w.nets[self.miso].drive("spi_tgt", None)
        elif self.active:
            if psck == 0 and sck == 1:
                if mosi != pmosi:
                    w.error("spi: MOSI changed on the sampling edge (hold violation)")
                self.pending = False
                self.rx = ((self.rx << 1) | pmosi) & 0xFF
                self.nbits += 1
                if self.nbits % 8 == 0:
                    self.cur.append(self.rx)
            elif psck == 1 and sck == 0:
                if self.nbits % 8 == 0:
                    self._load(w, pending=True)
                else:
                    self.tx = (self.tx << 1) & 0xFF
                    w.nets[self.miso].drive("spi_tgt", (self.tx >> 7) & 1)
            elif sck == 1 and mosi != pmosi:
                w.error("spi: MOSI changed while SCK high")
        self.prev = (cs, sck, mosi)


# ---------------------------------------------------------------- I2C
class I2cTarget:
    """7-bit I2C target at `addr`. ACKs its address and every data byte except 0xFF.
    Randomly stretches the clock after falling edges."""

    def __init__(self, sda, scl, addr, stretch_max=6, seed=1,
                 scl_high_nominal=None, scl_low_nominal=None, tol=0.25):
        """scl_high_nominal / scl_low_nominal: expected SCL phase lengths in
        cycles. Each observed phase must last at least nominal*(1-tol).

        Minimums, matching how I2C specifies clock timing (t_HIGH and t_LOW are
        both minimums in the spec), which also makes the check correct under
        clock stretching: the target can only ever LENGTHEN the low phase, never
        shorten it, so a minimum never produces a false failure. The high phase
        is master-controlled and not stretchable.

        `tol` is deliberate slack for propagation delay and jitter, not
        measurement noise. A master that ignores its bit timer collapses both
        phases to one or two cycles and fails at any sane tolerance."""
        self.sda, self.scl, self.addr = sda, scl, addr
        self.scl_hi_min = None if scl_high_nominal is None else scl_high_nominal * (1.0 - tol)
        self.scl_lo_min = None if scl_low_nominal is None else scl_low_nominal * (1.0 - tol)
        self.last_scl_edge_t = None
        self.rng = random.Random(seed)
        self.stretch_max = stretch_max
        self.transactions = []      # (addr_byte, [data], acked_flags)
        self.prev = (1, 1)
        self.state = "idle"
        self.hold = 0

    def step(self, w):
        sda, scl = w.value(self.sda), w.value(self.scl)
        psda, pscl = self.prev

        if pscl != scl:                     # SCL edge: check the phase just ended
            lim = self.scl_hi_min if pscl == 1 else self.scl_lo_min
            if lim is not None and self.last_scl_edge_t is not None:
                dur = w.t - self.last_scl_edge_t
                if dur < lim:
                    w.error(f"i2c: SCL {'high' if pscl == 1 else 'low'} phase "
                            f"{dur} cycles < minimum {lim:.1f} "
                            f"(master ignored its bit timer?)")
            self.last_scl_edge_t = w.t

        if self.hold > 0:
            self.hold -= 1
            if self.hold == 0:
                w.nets[self.scl].drive("i2c_tgt", None)

        if pscl == 1 and scl == 1 and psda != sda:
            if sda == 0:                        # START
                if self.state not in ("idle",):
                    w.error("i2c: unexpected repeated start")
                self.state, self.nbits, self.byte = "addr", 0, 0
                self.cur = [None, [], []]
            else:                               # STOP
                if self.state in ("addr", "data") and self.nbits not in (0, 1):
                    w.error(f"i2c: stop mid-byte ({self.nbits} bits)")
                if self.state != "idle":
                    self.transactions.append(tuple(self.cur))
                self.state = "idle"
                w.nets[self.sda].drive("i2c_tgt", None)
        elif pscl == 0 and scl == 1:            # rising edge: sample
            if sda != psda:
                w.error("i2c: SDA changed on the SCL rising edge (hold violation)")
            if self.state in ("addr", "data"):
                self.byte = ((self.byte << 1) | sda) & 0xFF
                self.nbits += 1
            elif self.state == "nacked":
                self.nack_rises += 1
                if self.nack_rises > 2:     # the NACK clock itself, then the STOP's rise
                    w.error("i2c: master kept clocking after NACK")
        elif pscl == 1 and scl == 0:            # falling edge
            if self.state in ("addr", "data") and self.nbits == 8:
                if self.state == "addr":
                    self.cur[0] = self.byte
                    ack = (self.byte >> 1) == self.addr and (self.byte & 1) == 0
                else:
                    self.cur[1].append(self.byte)
                    ack = self.byte != 0xFF
                self.cur[2].append(ack)
                self.state = "ack" if ack else "nacked"
                self.nack_rises = 0
                if ack:
                    w.nets[self.sda].drive("i2c_tgt", 0)
                self.nbits = 9
            elif self.state == "ack" and self.nbits == 9:
                w.nets[self.sda].drive("i2c_tgt", None)
                self.state, self.nbits, self.byte = "data", 0, 0
            if self.stretch_max and self.rng.random() < 0.5:
                self.hold = self.rng.randint(1, self.stretch_max)
                w.nets[self.scl].drive("i2c_tgt", 0)
        self.prev = (sda, scl)


# ---------------------------------------------------------------- USB low speed


class UsbLsMonitor:
    """Decodes low-speed USB token packets from D+/D-.
    Low speed idle J: D+ = 0, D- = 1.  K: D+ = 1, D- = 0.  SE0: both 0."""

    def __init__(self, dp, dm, period):
        self.dp, self.dm, self.P = dp, dm, period
        self.packets = []   # (pid, field11) or error string
        self.jitter = 0
        self.start = None
        self.prev = None

    def _state(self, w):
        return (w.value(self.dp), w.value(self.dm))

    def step(self, w):
        s = self._state(w)
        t = w.t
        if self.prev is None:
            self.prev = s
            return
        if self.start is not None and s != self.prev:
            self.edges.append(t)
        if self.start is None and self.prev == (0, 1) and s == (1, 0):
            self.start, self.samples, self.edges = t, [], [t]
        if self.start is not None:
            k, r = divmod(t - self.start, self.P)
            if r == self.P // 2:
                self.samples.append(s)
                if s == (0, 1) and len(self.samples) >= 2 and self.samples[-2] == (0, 0):
                    self._finish(w)
        self.prev = s

    def _finish(self, w):
        sm = self.samples
        self.jitter = max(self.jitter, edge_jitter(self.edges, self.start, self.P))
        self.start = None
        n_se0 = 0
        while sm and sm[-2 - n_se0] == (0, 0):
            n_se0 += 1
        data_states = sm[:len(sm) - 1 - n_se0]
        if n_se0 != 2:
            self.packets.append(f"EOP SE0 length {n_se0} bits")
            return
        # NRZI decode (previous state starts at J)
        prev, raw = (0, 1), []
        for st in data_states:
            if st not in ((0, 1), (1, 0)):
                self.packets.append("SE0 inside packet")
                return
            raw.append(1 if st == prev else 0)
            prev = st
        # destuff
        bits, ones, i = [], 0, 0
        while i < len(raw):
            b = raw[i]
            bits.append(b)
            ones = ones + 1 if b else 0
            i += 1
            if ones == 6:
                if i >= len(raw) or raw[i] != 0:
                    self.packets.append("bit stuffing violation")
                    return
                i += 1
                ones = 0
        if len(bits) != 32:
            self.packets.append(f"wrong length {len(bits)}")
            return
        if bits[:8] != [0, 0, 0, 0, 0, 0, 0, 1]:
            self.packets.append("bad SYNC")
            return
        pid = sum(b << j for j, b in enumerate(bits[8:16]))
        if (pid & 0xF) != (~pid >> 4) & 0xF:
            self.packets.append(f"bad PID check {pid:#x}")
            return
        field = sum(b << j for j, b in enumerate(bits[16:27]))
        crc = sum(b << j for j, b in enumerate(bits[27:32]))
        if crc != crc5_usb(bits[16:27]):
            self.packets.append(f"bad CRC {crc:#x} expected {crc5_usb(bits[16:27]):#x}")
            return
        self.packets.append((pid, field))
