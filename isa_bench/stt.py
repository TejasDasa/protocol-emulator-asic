"""State-table ISA.

Each row: test | next_true | next_false | pin ops (3 slots) | action flags.
When the test passes, actions run (in the fixed order below), then pin ops (which see the
updated shift register), then control goes to next_true. Otherwise nothing happens and
control goes to next_false.

v1 row = test 4 + next 5 + next 5 + pins 3x2 + actions 8            = 28 bits
v2 row = test 4 + next 5 + next 5 + pins 3x3 + actions 16           = 39 bits
v2 adds: toggle pin op, second counter, 3 counter-load values, constant load, CRC5 helper,
tests c2z/srbit, and a one-level call/return (`call` action, target 'ret').
"""

TESTS_V1 = {"always", "tmr", "fifo", "cz", "in0h", "in0l", "in1h", "in1l"}
TESTS_V2 = TESTS_V1 | {"c2z", "srbit", "stall"}
ACTS_V1 = ["load", "clr", "shift", "push", "cload", "cdec", "trst", "thalf"]
ACTS_V2_EXTRA = ["loadk", "loadcrc", "cload_b", "cload_c", "c2load", "c2dec",
                 "crcrst", "crcstep", "call",
                 # SPEC section 9 reserved codes, now implemented. They drive the
                 # WIDER shared units: a 16-bit programmable CRC and the bit
                 # stuffer. The per-SM CRC5 above is fixed at polynomial 0x14.
                 "crc16rst", "crc16step", "stuffrst"]
# crc16step sits with crcstep, BEFORE shift, for the reason SPEC section 8.2
# gives for crcstep: a CRC step must see the shift register as it was, not after
# this row's shift. Appending it at the end would silently invert that.
ACT_ORDER = ["load", "loadk", "loadcrc", "clr", "crcrst", "crcstep",
             "crc16rst", "crc16step", "stuffrst", "shift", "push",
             "cload", "cload_b", "cload_c", "cdec", "c2load", "c2dec", "trst", "thalf",
             "call"]
PINOPS_V1 = {"hold", "lo", "hi", "sr"}
PINOPS_V2 = PINOPS_V1 | {"tgl", "d0", "d1", "crcb"}

WIDTH = {1: 4 + 5 + 5 + 3 * 2 + 8, 2: 4 + 5 + 5 + 3 * 3 + 16}
MAX_ROWS = 32


class Row:
    def __init__(self, name, test, t, f=None, pins=None, act=()):
        self.name, self.test, self.t = name, test, t
        self.f = name if f is None else f
        self.pins = pins or {}
        self.act = list(act)


class SttProgram:
    def __init__(self, rows):
        if len(rows) > MAX_ROWS:
            raise ValueError(f"{len(rows)} rows (max {MAX_ROWS})")
        self.rows = rows
        self.index = {r.name: i for i, r in enumerate(rows)}
        v = 1
        for r in rows:
            for a in r.act:
                if a not in ACTS_V1 and a not in ACTS_V2_EXTRA:
                    raise ValueError(f"bad action {a}")
                if a in ACTS_V2_EXTRA:
                    v = 2
            if r.test not in TESTS_V2:
                raise ValueError(f"bad test {r.test}")
            if r.test not in TESTS_V1:
                v = 2
            for slot, op in r.pins.items():
                if op not in PINOPS_V2:
                    raise ValueError(f"bad pin op {op}")
                # d0/d1 name the two halves of the D+/D- pair. On a single slot
                # both the model and rtl/stt_datapath.v structurally write
                # nothing (single_we stays 0). That is a specified no-op in
                # hardware, but a program that asks for it has a bug, so the
                # encoder refuses to express it. See docs/SPEC.md section 6.
                if slot != "pair" and op in ("d0", "d1"):
                    raise ValueError(
                        f"pin op {op} on single slot {slot}: d0/d1 are pair-only")
                if op not in PINOPS_V1:
                    v = 2
            if r.t == "ret":
                v = 2
            for tgt in (r.t, r.f):
                if tgt != "ret" and tgt not in self.index and tgt not in [x.name for x in rows]:
                    raise ValueError(f"unknown target {tgt}")
        self.version = v

    @property
    def bits(self):
        return len(self.rows) * WIDTH[self.version]

    def bits_at(self, version):
        return len(self.rows) * WIDTH[version]


class SttCore:
    def __init__(self, prog, *, slots, ins=(), period, shift="right", fill="0",
                 sr_width=8, cload=(8, 0, 0), c2load=0, loadk=0, init_pins=None,
                 crc16_poly=0, crc16_width=16, crc16_reflect=False,
                 crc16_seed_ones=False, stuff_n=0, stuff_ones=False,
                 stuff_slots=()):
        """slots: list of (net, mode) with mode 'pp' or 'od'. ins: nets for in0, in1."""
        self.p = prog
        self.slots, self.ins = slots, list(ins)
        self.P = period
        self.shift, self.fill, self.w = shift, fill, sr_width
        self.cvals, self.c2val, self.k = cload, c2load, loadk
        self.row = 0
        self.sr = self.cnt = self.c2 = 0
        self.crc = 0x1F
        self.link = 0
        self.tcount = period - 1
        self.pinv = list(init_pins) if init_pins else [1] * len(slots)
        self.name = "stt"

        # ---- the wider shared units (SPEC section 9) ----------------------
        # Configuration, per SPEC section 9's reserved_config: polynomial, bit
        # order and seed are per-program constants, not row fields.
        self.crc16_poly = crc16_poly
        self.crc16_w = crc16_width
        self.crc16_reflect = crc16_reflect
        self.crc16_seed_ones = crc16_seed_ones
        self.crc16 = ((1 << crc16_width) - 1) if crc16_seed_ones else 0
        # Bit stuffer: stuff_n identical bits force a complementary bit.
        # stuff_ones counts only 1s (USB, HDLC); otherwise any identical run
        # (CAN). stuff_slots names which output slots route through it.
        self.stuff_n = stuff_n
        self.stuff_ones = stuff_ones
        self.stuff_slots = set(stuff_slots)
        self.stuff_run = 0
        self.stuff_last = None

    # ---- the wider shared units (SPEC section 9) -------------------------
    def _crc16_mask(self):
        return (1 << self.crc16_w) - 1

    def _crc16_advance(self, bit):
        """One Galois step. Reflected = right-shifting (USB-style); otherwise
        left-shifting MSB-first, which is what CAN and CCITT CRCs use."""
        m = self._crc16_mask()
        if self.crc16_reflect:
            fb = (self.crc16 ^ bit) & 1
            self.crc16 = ((self.crc16 >> 1) ^ self.crc16_poly) & m if fb \
                else (self.crc16 >> 1) & m
        else:
            top = (self.crc16 >> (self.crc16_w - 1)) & 1
            fb = top ^ (bit & 1)
            self.crc16 = ((self.crc16 << 1) ^ self.crc16_poly) & m if fb \
                else (self.crc16 << 1) & m

    def _crc16_shift_out(self):
        """The bit leaving the register, advancing it. This is how a CRC is
        transmitted -- shifted onto the wire -- rather than loaded into the
        shift register, which is why no act_sr code was needed for it."""
        m = self._crc16_mask()
        if self.crc16_reflect:
            b = self.crc16 & 1
            self.crc16 = (self.crc16 >> 1) & m
        else:
            b = (self.crc16 >> (self.crc16_w - 1)) & 1
            self.crc16 = (self.crc16 << 1) & m
        return b

    def _stall(self):
        """True when the stuffer will insert a bit instead of accepting one."""
        if not self.stuff_n or self.stuff_last is None:
            return False
        if self.stuff_ones and self.stuff_last != 1:
            return False
        return self.stuff_run >= self.stuff_n

    def _through_stuffer(self, bit):
        """Emit one bit through the stuffer, returning what reaches the pin."""
        if self._stall():
            out = 1 - self.stuff_last
            self.stuff_run, self.stuff_last = 1, out
            return out
        if self.stuff_last is not None and bit == self.stuff_last:
            self.stuff_run += 1
        else:
            self.stuff_run = 1
        self.stuff_last = bit
        return bit

    def _srbit(self):
        return (self.sr >> (self.w - 1)) & 1 if self.shift == "left" else self.sr & 1

    def _test(self, test, w, tick):
        if test == "always":
            return True
        if test == "tmr":
            return tick
        if test == "fifo":
            return bool(w.tx_fifo)
        if test == "cz":
            return self.cnt == 0
        if test == "c2z":
            return self.c2 == 0
        if test == "srbit":
            return self._srbit() == 1
        if test == "stall":
            return self._stall()
        pin = w.read_sync(self.ins[int(test[2])])
        return pin == (1 if test[3] == "h" else 0)

    def step(self, w):
        tick = self.tcount == 0
        r = self.p.rows[self.row]
        new_t = None
        if self._test(r.test, w, tick):
            acts = set(r.act)
            mask = (1 << self.w) - 1
            for a in ACT_ORDER:
                if a not in acts:
                    continue
                if a == "load":
                    if w.tx_fifo:
                        self.sr = w.tx_fifo.popleft() & mask
                    else:
                        w.error("stt: load from empty FIFO")
                elif a == "loadk":
                    self.sr = self.k & mask
                elif a == "loadcrc":
                    self.sr = (~self.crc) & 0x1F
                elif a == "clr":
                    self.sr = 0
                elif a == "crcrst":
                    self.crc = 0x1F
                elif a == "crcstep":
                    b = self._srbit()
                    self.crc = (self.crc >> 1) ^ 0x14 if (self.crc ^ b) & 1 else self.crc >> 1
                elif a == "crc16rst":
                    self.crc16 = self._crc16_mask() if self.crc16_seed_ones else 0
                elif a == "crc16step":
                    self._crc16_advance(self._srbit())
                elif a == "stuffrst":
                    self.stuff_run, self.stuff_last = 0, None
                elif a == "shift":
                    f = {"0": 0, "1": 1}.get(self.fill)
                    if f is None:
                        f = w.read_sync(self.ins[0])
                    if self.shift == "right":
                        self.sr = (self.sr >> 1) | (f << (self.w - 1))
                    else:
                        self.sr = ((self.sr << 1) | f) & mask
                elif a == "push":
                    w.rx_fifo.append(self.sr)
                elif a == "cload":
                    self.cnt = self.cvals[0]
                elif a == "cload_b":
                    self.cnt = self.cvals[1]
                elif a == "cload_c":
                    self.cnt = self.cvals[2]
                elif a == "cdec":
                    self.cnt = (self.cnt - 1) & 0xFF
                elif a == "c2load":
                    self.c2 = self.c2val
                elif a == "c2dec":
                    self.c2 = (self.c2 - 1) & 0xFF
                elif a == "trst":
                    new_t = self.P - 1
                elif a == "thalf":
                    new_t = self.P // 2 - 1
            for slot, op in r.pins.items():
                if slot == "pair":
                    # crcb on the pair drives both halves from one shift-out,
                    # as the SPEC section 7 pin-op table says. Without this the
                    # dict lookup below raises KeyError on a row the encoding
                    # permits.
                    if op == "crcb":
                        cb = self._crc16_shift_out()
                        self.pinv[0], self.pinv[1] = cb, cb
                        continue
                    b = self._srbit()
                    a0, a1 = {"lo": (0, 0), "hi": (1, 1), "sr": (b, 1 - b), "d0": (0, 1),
                              "d1": (1, 0), "tgl": (self.pinv[0] ^ 1, self.pinv[1] ^ 1)}[op]
                    self.pinv[0], self.pinv[1] = a0, a1
                    continue
                # The value the row asks for, before the stuffer sees it.
                if op == "lo":
                    want = 0
                elif op == "hi":
                    want = 1
                elif op == "sr":
                    want = self._srbit()
                elif op == "crcb":
                    want = self._crc16_shift_out()
                elif op == "tgl":
                    want = self.pinv[slot] ^ 1
                else:
                    continue          # hold, and d0/d1 on a single slot
                # A slot routed through the bit stuffer may emit a stuffed bit
                # instead of the one the row asked for. That is why `stall`
                # exists: the program tests it and holds the shift register.
                if slot in self.stuff_slots:
                    want = self._through_stuffer(want)
                self.pinv[slot] = want
            target = r.t
            if "call" in acts:
                self.link = self.p.index[r.f]
            nxt = self.link if target == "ret" else self.p.index[target]
        else:
            # SPEC section 5: target 255 means return, and in SKIP mode the
            # target field feeds the FALSE exit. Resolving "ret" only on the
            # true exit raised KeyError on a row no reference program happens to
            # contain; the rule is the same on either exit.
            nxt = self.link if r.f == "ret" else self.p.index[r.f]
        self.row = nxt
        if new_t is not None:
            self.tcount = new_t
        else:
            self.tcount = self.P - 1 if tick else self.tcount - 1
        for (net, mode), v in zip(self.slots, self.pinv):
            if net is None:
                continue
            if mode == "od":
                w.nets[net].drive(self.name, None if v else 0)
            else:
                w.nets[net].drive(self.name, v)
