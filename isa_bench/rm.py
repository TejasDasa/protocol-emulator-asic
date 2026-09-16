"""Tiny register machine.

16-bit instructions: 5-bit opcode + 11 operand bits. Four 8-bit registers r0-r3, Z and C flags,
a free-running timer (WAIT blocks until its next tick), and a one-level CALL/RET link register.
Every instruction takes one cycle; POP and WAIT stall.

Operand layouts (11 bits):
  reg + imm8 (2+8)   reg, reg (2+2)   addr8   pin3 + addr8   mask4 + val4   pin3
"""

BITS_PER_INSTR = 16

# opcode -> operand signature
OPS = {
    "LDI": "ri", "MOV": "rr", "ADD": "rr", "SUB": "rr", "AND": "rr", "XOR": "rr",
    "XORI": "ri", "ANDI": "ri",
    "SHR": "r", "SHL": "r", "RCR": "r", "RCL": "r", "DEC": "r",
    "JMP": "a", "JZ": "a", "JNZ": "a", "JC": "a", "JNC": "a",
    "JPH": "pa", "JPL": "pa", "JFE": "a",
    "POP": "r", "PUSH": "r",
    "PSET": "p", "PCLR": "p", "POUT": "p", "PIN": "p", "PORT": "mv",
    "WAIT": "", "TRST": "h", "CALL": "a", "RET": "",
}
assert len(OPS) == 32


def assemble(src, **defs):
    lines, labels = [], {}
    for raw in src.splitlines():
        line = raw.split(";")[0].strip()
        while True:
            head, sep, rest = line.partition(":")
            if sep and head.strip().isidentifier() and " " not in head.strip():
                labels[head.strip()] = len(lines)
                line = rest.strip()
            else:
                break
        if line:
            lines.append(line)
    if len(lines) > 256:
        raise ValueError("program too long")

    def val(s):
        s = s.strip()
        if s in labels:
            return labels[s]
        return int(eval(s, {"__builtins__": {}}, defs))

    prog = []
    for line in lines:
        parts = line.replace(",", " ").split()
        op, args = parts[0].upper(), parts[1:]
        if op == "NOP":
            op, args = "MOV", ["r0", "r0"]
        sig = OPS[op]
        out = []
        for kind, a in zip(sig, args):
            if kind == "r":
                out.append(int(a[1]))
            elif kind in "iamvhp":
                v = val(a)
                lim = {"i": 255, "a": 255, "m": 15, "v": 15, "h": 1, "p": 7}[kind]
                if not 0 <= v <= lim:
                    raise ValueError(f"operand out of range: {line}")
                out.append(v)
        if len(out) != len(sig):
            raise ValueError(f"bad operands: {line}")
        prog.append((op, out, line))
    return RmProgram(prog, labels)


class RmProgram:
    def __init__(self, instrs, labels):
        self.instrs, self.labels = instrs, labels

    @property
    def bits(self):
        return len(self.instrs) * BITS_PER_INSTR


class RmCore:
    def __init__(self, prog, *, pins, period, init_pins=None):
        """pins: list of (net, mode) with mode 'pp', 'od', or 'in'."""
        self.p, self.pins, self.P = prog, pins, period
        self.r = [0, 0, 0, 0]
        self.z = self.c = 0
        self.pc = 0
        self.link = 0
        self.tcount = period - 1
        self.pinv = list(init_pins) if init_pins else [1] * len(pins)
        self.name = "rm"

    def _flags(self, v):
        self.z = int((v & 0xFF) == 0)

    def step(self, w):
        tick = self.tcount == 0
        new_t = None
        op, a, _ = self.p.instrs[self.pc]
        r = self.r
        nxt = self.pc + 1
        if op == "LDI":
            r[a[0]] = a[1]
        elif op == "MOV":
            r[a[0]] = r[a[1]]
        elif op in ("ADD", "SUB"):
            v = r[a[0]] + r[a[1]] if op == "ADD" else r[a[0]] - r[a[1]]
            self.c = int(v > 255 or v < 0)
            r[a[0]] = v & 0xFF
            self._flags(v)
        elif op in ("AND", "XOR", "XORI", "ANDI"):
            rhs = r[a[1]] if op in ("AND", "XOR") else a[1]
            v = r[a[0]] & rhs if op in ("AND", "ANDI") else r[a[0]] ^ rhs
            r[a[0]] = v
            self._flags(v)
        elif op == "SHR":
            self.c, r[a[0]] = r[a[0]] & 1, r[a[0]] >> 1
            self._flags(r[a[0]])
        elif op == "SHL":
            self.c, r[a[0]] = r[a[0]] >> 7, (r[a[0]] << 1) & 0xFF
            self._flags(r[a[0]])
        elif op == "RCR":
            c = self.c
            self.c, r[a[0]] = r[a[0]] & 1, (r[a[0]] >> 1) | (c << 7)
            self._flags(r[a[0]])
        elif op == "RCL":
            c = self.c
            self.c, r[a[0]] = r[a[0]] >> 7, ((r[a[0]] << 1) & 0xFF) | c
            self._flags(r[a[0]])
        elif op == "DEC":
            r[a[0]] = (r[a[0]] - 1) & 0xFF
            self._flags(r[a[0]])
        elif op == "JMP":
            nxt = a[0]
        elif op in ("JZ", "JNZ", "JC", "JNC"):
            cond = {"JZ": self.z, "JNZ": not self.z, "JC": self.c, "JNC": not self.c}[op]
            if cond:
                nxt = a[0]
        elif op in ("JPH", "JPL"):
            v = w.read_sync(self.pins[a[0]][0])
            if v == (1 if op == "JPH" else 0):
                nxt = a[1]
        elif op == "JFE":
            if not w.tx_fifo:
                nxt = a[0]
        elif op == "POP":
            if w.tx_fifo:
                r[a[0]] = w.tx_fifo.popleft() & 0xFF
            else:
                nxt = self.pc
        elif op == "PUSH":
            w.rx_fifo.append(r[a[0]])
        elif op == "PSET":
            self.pinv[a[0]] = 1
        elif op == "PCLR":
            self.pinv[a[0]] = 0
        elif op == "POUT":
            self.pinv[a[0]] = self.c
        elif op == "PIN":
            self.c = w.read_sync(self.pins[a[0]][0])
        elif op == "PORT":
            for i in range(4):
                if (a[0] >> i) & 1:
                    self.pinv[i] = (a[1] >> i) & 1
        elif op == "WAIT":
            if not tick:
                nxt = self.pc
        elif op == "TRST":
            new_t = self.P // 2 - 1 if a[0] else self.P - 1
        elif op == "CALL":
            self.link, nxt = self.pc + 1, a[0]
        elif op == "RET":
            nxt = self.link
        else:
            raise ValueError(op)
        self.pc = nxt
        if new_t is not None:
            self.tcount = new_t
        else:
            self.tcount = self.P - 1 if tick else self.tcount - 1
        for (net, mode), v in zip(self.pins, self.pinv):
            if net is None or mode == "in":
                continue
            if mode == "od":
                w.nets[net].drive(self.name, None if v else 0)
            else:
                w.nets[net].drive(self.name, v)
