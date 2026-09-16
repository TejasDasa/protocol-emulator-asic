"""RP2040-style PIO: assembler for a pioasm-like syntax and a single state machine.

Every instruction is 16 bits. Side-set and delay share 5 bits; with `side_set N opt`,
N+1 bits are used for side-set and 5-N-1 for delay.
"""
import re

M32 = 0xFFFFFFFF
BITS_PER_INSTR = 16


class Instr:
    def __init__(self, op, args, side, delay, text):
        self.op, self.args, self.side, self.delay, self.text = op, args, side, delay, text


class PioProgram:
    def __init__(self, instrs, labels, side_bits, side_opt, side_pindirs):
        self.instrs, self.labels = instrs, labels
        self.side_bits, self.side_opt, self.side_pindirs = side_bits, side_opt, side_pindirs

    @property
    def bits(self):
        return len(self.instrs) * BITS_PER_INSTR


def assemble(src, side_set=0, side_opt=False, side_pindirs=False, **defs):
    delay_bits = 5 - side_set - (1 if side_opt else 0)
    max_delay = (1 << delay_bits) - 1
    lines = []
    labels = {}
    for raw in src.splitlines():
        line = raw.split(";")[0].strip()
        while True:
            m = re.match(r"^(\w+):\s*(.*)$", line)
            if not m:
                break
            labels[m.group(1)] = len(lines)
            line = m.group(2).strip()
        if line:
            lines.append(line)
    if len(lines) > 32:
        raise ValueError(f"PIO program has {len(lines)} instructions (max 32)")

    def num(s):
        s = s.strip()
        if s in labels:
            return labels[s]
        return int(eval(s, {"__builtins__": {}}, defs))

    instrs = []
    for line in lines:
        text = line
        delay = 0
        m = re.search(r"\[([^\]]+)\]", line)
        if m:
            delay = num(m.group(1))
            line = line[:m.start()] + line[m.end():]
        side = None
        m = re.search(r"\bside\s+(\S+)", line)
        if m:
            side = num(m.group(1))
            line = line[:m.start()] + line[m.end():]
        if delay < 0 or delay > max_delay:
            raise ValueError(f"delay {delay} out of range 0..{max_delay}: {text}")
        if side is None and side_set and not side_opt:
            raise ValueError(f"side-set required: {text}")
        if side is not None and side >= (1 << side_set):
            raise ValueError(f"side value too large: {text}")
        parts = line.replace(",", " ").split()
        op, a = parts[0].lower(), parts[1:]
        if op == "nop":
            op, a = "mov", ["y", "y"]
        if op == "jmp":
            cond = a[0] if len(a) == 2 else ""
            args = (cond, num(a[-1]))
        elif op == "wait":
            args = (num(a[0]), num(a[2]))           # wait <pol> pin <n>
        elif op in ("in", "out"):
            args = (a[0], num(a[1]) if len(a) > 1 else 32)
        elif op in ("push", "pull"):
            args = (a[0] if a else "block",)
        elif op == "mov":
            src_ = a[1]
            mop = ""
            for p in ("::", "~", "!"):
                if src_.startswith(p):
                    mop, src_ = p, src_[len(p):]
            args = (a[0], mop, src_)
        elif op == "set":
            args = (a[0], num(a[1]))
        else:
            raise ValueError(f"unknown op {op}")
        instrs.append(Instr(op, args, side, delay, text))
    return PioProgram(instrs, labels, side_set, side_opt, side_pindirs)


class PioSM:
    """One PIO state machine attached to a list of nets (index = local GPIO number)."""

    def __init__(self, prog, pins, *, in_base=0, out_base=0, out_count=1, set_base=0,
                 set_count=1, side_base=0, jmp_pin=0, out_shift_right=True,
                 in_shift_right=True, divider=1, status_n=1, entry=0,
                 pull_thresh=32, push_thresh=32, autopull=False, autopush=False,
                 init_values=0, init_dirs=0):
        self.p, self.pins = prog, pins
        self.in_base, self.out_base, self.out_count = in_base, out_base, out_count
        self.set_base, self.set_count, self.side_base = set_base, set_count, side_base
        self.jmp_pin = jmp_pin
        self.out_right, self.in_right = out_shift_right, in_shift_right
        self.divider, self.status_n = divider, status_n
        self.pull_thresh, self.push_thresh = pull_thresh, push_thresh
        self.autopull, self.autopush = autopull, autopush
        self.pc = entry
        self.x = self.y = self.isr = self.osr = 0
        self.isr_count = 0
        self.osr_count = 32          # empty at reset
        self.delay = 0
        self.div_ctr = 0
        self.values, self.dirs = init_values, init_dirs
        self.name = "pio"

    # -- pin helpers
    def _read(self, w, idx):
        return w.read_sync(self.pins[idx])

    def _write_bits(self, which, base, count, data):
        mask = ((1 << count) - 1) << base
        v = (data << base) & mask
        if which == "values":
            self.values = (self.values & ~mask) | v
        else:
            self.dirs = (self.dirs & ~mask) | v

    def _drive(self, w):
        for i, net in enumerate(self.pins):
            if net is None:
                continue
            if (self.dirs >> i) & 1:
                w.nets[net].drive(self.name, (self.values >> i) & 1)
            else:
                w.nets[net].drive(self.name, None)

    # -- main step
    def step(self, w):
        self.div_ctr += 1
        if self.div_ctr < self.divider:
            return
        self.div_ctr = 0
        if self.delay > 0:
            self.delay -= 1
            return
        ins = self.p.instrs[self.pc]
        if ins.side is not None:
            n = self.p.side_bits
            which = "dirs" if self.p.side_pindirs else "values"
            self._write_bits(which, self.side_base, n, ins.side)
        done = self._exec(ins, w)
        if done:
            self.delay = ins.delay
        self._drive(w)

    def _next(self):
        self.pc = (self.pc + 1) % len(self.p.instrs)

    def _exec(self, ins, w):
        op, a = ins.op, ins.args
        if op == "jmp":
            cond, target = a
            if cond == "":
                c = True
            elif cond == "!x":
                c = self.x == 0
            elif cond == "!y":
                c = self.y == 0
            elif cond == "x--":
                c = self.x != 0
                self.x = (self.x - 1) & M32
            elif cond == "y--":
                c = self.y != 0
                self.y = (self.y - 1) & M32
            elif cond == "x!=y":
                c = self.x != self.y
            elif cond == "pin":
                c = self._read(w, self.jmp_pin) == 1
            elif cond == "!osre":
                c = self.osr_count < self.pull_thresh
            else:
                raise ValueError(cond)
            if c:
                self.pc = target
            else:
                self._next()
            return True
        if op == "wait":
            pol, n = a
            if self._read(w, self.in_base + n) == pol:
                self._next()
                return True
            return False
        if op == "in":
            src, n = a
            data = self._source(w, src) & ((1 << n) - 1)
            if self.in_right:
                self.isr = ((self.isr >> n) | (data << (32 - n))) & M32 if n < 32 else data
            else:
                self.isr = ((self.isr << n) | data) & M32 if n < 32 else data
            self.isr_count = min(32, self.isr_count + n)
            if self.autopush and self.isr_count >= self.push_thresh:
                w.rx_fifo.append(self.isr)
                self.isr, self.isr_count = 0, 0
            self._next()
            return True
        if op == "out":
            dst, n = a
            if self.autopull and self.osr_count >= self.pull_thresh:
                if not w.tx_fifo:
                    return False
                self.osr, self.osr_count = w.tx_fifo.popleft(), 0
            if self.out_right:
                data = self.osr & ((1 << n) - 1)
                self.osr = (self.osr >> n) if n < 32 else 0
            else:
                data = (self.osr >> (32 - n)) & ((1 << n) - 1)
                self.osr = ((self.osr << n) & M32) if n < 32 else 0
            self.osr_count = min(32, self.osr_count + n)
            if dst == "pc":
                self.pc = data
                return True
            self._dest(dst, data, n)
            self._next()
            return True
        if op == "push":
            w.rx_fifo.append(self.isr)
            self.isr, self.isr_count = 0, 0
            self._next()
            return True
        if op == "pull":
            if not w.tx_fifo:
                if a[0] == "noblock":
                    self.osr, self.osr_count = self.x, 0
                    self._next()
                    return True
                return False
            self.osr, self.osr_count = w.tx_fifo.popleft() & M32, 0
            self._next()
            return True
        if op == "mov":
            dst, mop, src = a
            v = self._source(w, src)
            if mop in ("~", "!"):
                v = (~v) & M32
            elif mop == "::":
                v = int(f"{v:032b}"[::-1], 2)
            if dst == "pc":
                self.pc = v % len(self.p.instrs)
                return True
            self._dest(dst, v, 32)
            self._next()
            return True
        if op == "set":
            dst, v = a
            if dst == "pins":
                self._write_bits("values", self.set_base, self.set_count, v)
            elif dst == "pindirs":
                self._write_bits("dirs", self.set_base, self.set_count, v)
            else:
                self._dest(dst, v, 32)
            self._next()
            return True
        raise ValueError(op)

    def _source(self, w, src):
        if src == "pins":
            v = 0
            for i in range(self.in_base, len(self.pins)):
                if self.pins[i] is not None:
                    v |= self._read(w, i) << (i - self.in_base)
            return v
        if src == "x":
            return self.x
        if src == "y":
            return self.y
        if src == "null":
            return 0
        if src == "isr":
            return self.isr
        if src == "osr":
            return self.osr
        if src == "status":
            return M32 if len(w.tx_fifo) < self.status_n else 0
        raise ValueError(src)

    def _dest(self, dst, v, n):
        if dst == "x":
            self.x = v & M32
        elif dst == "y":
            self.y = v & M32
        elif dst == "null":
            pass
        elif dst == "isr":
            self.isr, self.isr_count = v & M32, 0
        elif dst == "osr":
            self.osr, self.osr_count = v & M32, 0
        elif dst == "pins":
            self._write_bits("values", self.out_base, min(n, self.out_count), v)
        elif dst == "pindirs":
            self._write_bits("dirs", self.out_base, min(n, self.out_count), v)
        else:
            raise ValueError(dst)
