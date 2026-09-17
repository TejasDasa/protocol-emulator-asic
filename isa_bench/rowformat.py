"""General row-format explorer.

Row = test 4 | mode 2 | target 5 | PIN FIELD | ACTION FIELD

PIN FIELD
  slots3   3 slots x 3-bit op                       9 bits
  single5  2-bit slot (3 = D+/D- pair) + 3-bit op   5 bits   (at most one pin op per row)
  combo    folded into the palette entry

ACTION FIELD
  flags    one bit per action (counter load is a 2-bit field)   16 bits
  grouped  mutually exclusive groups                             13 bits
  palette  index into a table of action sets (or pin+action combos)

PALETTE STORAGE
  program  table stored in program memory, counted in the bits
  silicon  table fixed at tapeout, not counted, must already contain every needed entry
"""
from rowenc import (best_order, pack, unpack, rebuild, bits_for, RET, TESTS,
                    encode_actions_grouped, decode_actions_grouped, GROUPS, GROUP_BITS, ACTS)
from stt import SttProgram

# "crcb" appended: codes 0-6 must not move. SPEC section 9.
PINOPS = ["hold", "lo", "hi", "sr", "tgl", "d0", "d1", "crcb"]
SLOTS = [0, 1, 2, "pair"]
NO_CL = [a for a in ACTS if a not in ("cload", "cload_b", "cload_c")]
CLOADS = ["", "cload", "cload_b", "cload_c"]


def pin_key(r):
    return tuple(sorted(((str(k), v) for k, v in r.pins.items())))


def act_key(r):
    return tuple(sorted(r.act))


class Format:
    def __init__(self, pins, acts, storage=None, palette=None, tgt_bits=5):
        self.pins, self.acts, self.storage = pins, acts, storage
        self.palette = palette          # silicon palette (list of keys) if storage == "silicon"
        # Branch-target field width. 5 is the 21-bit row (31 reachable rows,
        # code 31 = RET). The 32-bit row widens it to 8 because the bits are
        # free there, not because 5 was binding -- see docs/row-format-decision.md.
        self.tgt_bits = tgt_bits
        self.ret = (1 << tgt_bits) - 1

    @property
    def label(self):
        a = self.acts if self.acts != "palette" else f"{self.storage} palette"
        return f"{self.pins} + {a}"

    def key(self, r):
        if self.pins == "combo":
            return (pin_key(r), act_key(r))
        return act_key(r)

    def entry_width(self):
        w = GROUP_BITS
        if self.pins == "combo":
            w += 9
        return w

    def encode(self, prog):
        """Returns dict(bits, row_width, palette_bits, missing, decoded)."""
        lay = best_order(prog.rows)
        names = [x["row"].name for x in lay]

        if self.acts == "palette":
            if self.storage == "program":
                empty = ((), ()) if self.pins == "combo" else ()
                pal = [empty] + sorted({self.key(x["row"]) for x in lay} - {empty})
            else:
                pal = self.palette
                missing = {self.key(x["row"]) for x in lay} - set(pal)
                if missing:
                    return dict(bits=None, missing=len(missing))
            k = bits_for(len(pal))
        packed, widths = [], None
        for x in lay:
            r = x["row"]
            tgt = self.ret if x["target"] == "ret" else (names.index(x["target"]) if x["target"] else 0)
            f = [(TESTS.index(r.test), 4), (x["mode"], 2), (tgt, self.tgt_bits)]
            if self.pins == "slots3":
                f += [(PINOPS.index(r.pins.get(s, "hold")), 3) for s in range(3)]
            elif self.pins == "single5":
                if len(r.pins) > 1:
                    raise ValueError(f"row {r.name} drives {len(r.pins)} pin fields")
                (slot, op), = r.pins.items() if r.pins else ((0, "hold"),)
                f += [(SLOTS.index(slot), 2), (PINOPS.index(op), 3)]
            if self.acts == "flags":
                cl = next((i for i, c in enumerate(CLOADS) if c and c in r.act), 0)
                f += [(cl, 2)] + [(int(a in r.act), 1) for a in NO_CL]
            elif self.acts == "grouped":
                f += [(c, bits_for(len(ch))) for (_, ch), c in
                      zip(GROUPS, encode_actions_grouped(r.act))]
            else:
                f += [(pal.index(self.key(r)), k)]
            v, w = pack(f)
            packed.append(v)
            widths = [fw for _, fw in f]
        # ---- decode
        extras = []
        for i, v in enumerate(packed):
            u = unpack(v, widths)
            test, mode, tgt, rest = TESTS[u[0]], u[1], u[2], u[3:]
            pins = {}
            if self.pins == "slots3":
                pins = {s: PINOPS[c] for s, c in enumerate(rest[:3]) if c}
                rest = rest[3:]
            elif self.pins == "single5":
                if rest[1]:
                    pins = {SLOTS[rest[0]]: PINOPS[rest[1]]}
                rest = rest[2:]
            if self.acts == "flags":
                acts = [a for a, b in zip(NO_CL, rest[1:]) if b]
                if rest[0]:
                    acts.append(CLOADS[rest[0]])
            elif self.acts == "grouped":
                acts = decode_actions_grouped(rest)
            else:
                entry = pal[rest[0]]
                if self.pins == "combo":
                    pk, acts = entry
                    pins = {(int(s) if s.isdigit() else s): op for s, op in pk}
                else:
                    acts = entry
                acts = list(acts)
            extras.append(dict(name=names[i], test=test, mode=mode,
                               target=None if mode == 3 else tgt, pins=pins, acts=acts))
        dec = rebuild(lay, extras, ret=self.ret)
        pal_bits = 0
        if self.acts == "palette" and self.storage == "program":
            pal_bits = (len(pal) - 1) * self.entry_width()
        row_w = sum(widths)
        return dict(bits=len(packed) * row_w + pal_bits, row_width=row_w,
                    palette_bits=pal_bits, missing=0, decoded=dec, rows=len(packed),
                    packed=packed)


# ------------------------------------------------------------------ split fallback
from stt import Row, ACT_ORDER
from collections import Counter

SINGLES = [(a,) for a in ACT_ORDER]


def principled_palette(training_rows, size=32):
    """Empty set + every single action + the most frequent multi-action sets in training."""
    pal = [()] + sorted(SINGLES)
    freq = Counter(tuple(sorted(r.act)) for r in training_rows if len(r.act) > 1)
    for s, _ in freq.most_common():
        if len(pal) >= size:
            break
        pal.append(s)
    return pal


def split_rows(prog, palette):
    """Rewrite rows whose action set is not in the palette into a chain of rows.
    Actions keep their execution order across the chain. Pin ops that read the shift register
    go on the last row; other pin ops stay on the first (tick) row. CALL goes last."""
    pal = set(palette)
    out, added = [], 0
    for r in prog.rows:
        key = tuple(sorted(r.act))
        if key in pal:
            out.append(r)
            continue
        remaining = sorted(r.act, key=ACT_ORDER.index)
        chunks = []
        while remaining:
            # longest prefix of the ordered actions that is a palette entry
            for n in range(len(remaining), 0, -1):
                if tuple(sorted(remaining[:n])) in pal:
                    chunks.append(remaining[:n])
                    remaining = remaining[n:]
                    break
        names = [r.name] + [f"{r.name}_s{i}" for i in range(1, len(chunks))]
        sr_pins = {k: v for k, v in r.pins.items() if v == "sr"}
        other_pins = {k: v for k, v in r.pins.items() if v != "sr"}
        for i, (nm, ch) in enumerate(zip(names, chunks)):
            last = i == len(chunks) - 1
            pins = dict(other_pins) if i == 0 else {}
            if last:
                pins.update(sr_pins)
            test = r.test if i == 0 else "always"
            t = r.t if last else names[i + 1]
            if i == 0:
                f = r.f
            else:
                f = r.f if (last and "call" in ch) else nm
            out.append(Row(nm, test, t, f, pins=pins, act=ch))
        added += len(chunks) - 1
    return SttProgram(out), added
