"""Compressed row encodings for the state-table ISA.

Every scheme packs rows into real integers and unpacks them back into Row objects, so the
benchmarks can run on the decoded program to prove the encoding is lossless.

Branch modes (replace the two 5-bit targets with one target + 2-bit mode):
  0  WAIT     test ? target : self
  1  BRANCH   test ? target : next
  2  SKIP     test ? next   : target
  3  STEP     test ? next   : self        (target field unused)
A row whose two exits are neither `self` nor `next` gets a trampoline row (test always).
A CALL links to `next`. Target value 31 means return.
"""
import itertools
import random
from stt import Row, SttProgram, TESTS_V2, ACT_ORDER, PINOPS_V2

TESTS = sorted(TESTS_V2)                     # 10 tests -> 4 bits
PINOPS = ["hold", "lo", "hi", "sr", "tgl"]   # 3 bits per slot
ACTS = ACT_ORDER                             # 17 flags incl. 3 counter loads (16 in v2 accounting)
RET = 31

# Grouped (enumerated) action encoding. Each group holds mutually exclusive choices.
GROUPS = [
    ("sr", [(), ("load",), ("loadk",), ("loadcrc",), ("clr",), ("shift",),
            ("clr", "shift"), ("push",)]),                             # 3 bits
    ("c1", [(), ("cload",), ("cload_b",), ("cload_c",), ("cdec",)]),   # 3 bits
    ("c2", [(), ("c2load",), ("c2dec",)]),                             # 2 bits
    ("tm", [(), ("trst",), ("thalf",)]),                               # 2 bits
    ("xx", [(), ("crcrst",), ("crcstep",), ("call",), ("crcrst", "call")]),  # 3 bits
]


def bits_for(n):
    return max(1, (n - 1).bit_length())


def encode_actions_grouped(acts):
    """For each group, take the largest choice fully contained in the remaining actions."""
    left = set(acts)
    out = []
    for _, choices in GROUPS:
        fits = [j for j, c in enumerate(choices) if set(c) <= left]
        j = max(fits, key=lambda j: len(choices[j]))
        out.append(j)
        left -= set(choices[j])
    if left:
        raise ValueError(f"actions not encodable in groups: {left}")
    return out


def decode_actions_grouped(codes):
    acts = []
    for (name, choices), c in zip(GROUPS, codes):
        acts.extend(choices[c])
    return acts


GROUP_BITS = sum(bits_for(len(c)) for _, c in GROUPS)


# ------------------------------------------------------------------ layout
def realize(rows, order):
    """Given an order of row names, return rows with (mode, target) plus any trampolines.
    Returns list of dicts in final order."""
    pos = {name: i for i, name in enumerate(order)}
    byname = {r.name: r for r in rows}
    out = []
    for name in order:
        r = byname[name]
        nxt = order[pos[name] + 1] if pos[name] + 1 < len(order) else None
        t, f = r.t, r.f
        if "call" in r.act and f != nxt:
            raise ValueError("call must link to next row")
        if f == name and t == nxt and t != "ret":
            out.append(dict(row=r, mode=3, target=None))
        elif f == name:
            out.append(dict(row=r, mode=0, target=t))
        elif f == nxt:
            out.append(dict(row=r, mode=1, target=t))
        elif t == nxt and t != "ret":
            out.append(dict(row=r, mode=2, target=f))
        else:
            tramp = Row(f"_T_{name}", "always", f)
            out.append(dict(row=r, mode=1, target=t, tramp=tramp))
            out.append(dict(row=tramp, mode=0, target=f))
    return out


def cost(layout):
    return sum(1 for x in layout if x["row"].name.startswith("_T_"))


def best_order(rows, tries=3000, seed=0):
    """Search row orders (row 0 stays first) to minimize trampolines.
    Greedy chaining: after placing a row, prefer an unplaced exit as the next row."""
    rng = random.Random(seed)
    names = [r.name for r in rows]
    byname = {r.name: r for r in rows}
    best, best_c = None, None
    for k in range(tries):
        order = [names[0]]
        left = set(names[1:])
        while left:
            r = byname[order[-1]]
            cands = [x for x in (r.t, r.f) if x in left]
            # call rows must be followed by their link row
            if "call" in r.act and r.f in left:
                cands = [r.f]
            if cands and (k == 0 or rng.random() < 0.9):
                nxt = cands[0] if k == 0 else rng.choice(cands)
            else:
                nxt = rng.choice(sorted(left)) if k else sorted(left, key=names.index)[0]
            order.append(nxt)
            left.remove(nxt)
        try:
            lay = realize(rows, order)
        except ValueError:
            continue
        c = cost(lay)
        if best is None or c < best_c:
            best, best_c = order, c
            if c == 0:
                break
    return realize(rows, best)


# ------------------------------------------------------------------ schemes
class Scheme:
    name = ""

    def encode(self, prog):
        """Return (packed_rows, palette, bits, decoded SttProgram)."""
        raise NotImplementedError


def pack(fields):
    """fields: list of (value, width). Returns (int, total_width)."""
    v, w = 0, 0
    for val, width in fields:
        assert 0 <= val < (1 << width), (val, width)
        v |= val << w
        w += width
    return v, w


def unpack(v, widths):
    out = []
    for width in widths:
        out.append(v & ((1 << width) - 1))
        v >>= width
    return out


def pins_code(pins):
    return [PINOPS.index(pins.get(s, "hold")) for s in range(3)]


def pins_decode(codes):
    return {s: PINOPS[c] for s, c in enumerate(codes) if PINOPS[c] != "hold"}


def flags_code(acts):
    return [1 if a in acts else 0 for a in ACTS]


def flags_decode(bits):
    return [a for a, b in zip(ACTS, bits) if b]


def rebuild(layout, extras):
    """Turn a decoded layout back into an SttProgram with explicit targets."""
    names = [x["name"] for x in extras]
    rows = []
    for i, x in enumerate(extras):
        nxt = names[i + 1] if i + 1 < len(names) else names[0]
        me = names[i]
        tgt = "ret" if x["target"] == RET else (names[x["target"]] if x["target"] is not None else None)
        mode = x["mode"]
        if mode == 0:
            t, f = tgt, me
        elif mode == 1:
            t, f = tgt, nxt
        elif mode == 2:
            t, f = nxt, tgt
        else:
            t, f = nxt, me
        rows.append(Row(me, x["test"], t, f, pins=x["pins"], act=x["acts"]))
    return SttProgram(rows)


class Baseline(Scheme):
    """Original v2 format, original order."""
    name = "v2 baseline"

    def encode(self, prog):
        return None, 0, prog.bits_at(2), prog


class OneTarget(Scheme):
    """test 4 | mode 2 | target 5 | pins 9 | action flags or groups."""

    def __init__(self, grouped):
        self.grouped = grouped
        self.name = "one target + " + ("grouped actions" if grouped else "flags")
        self.aw = GROUP_BITS if grouped else 16

    def encode(self, prog):
        lay = best_order(prog.rows)
        names = [x["row"].name for x in lay]
        packed, width = [], None
        for x in lay:
            r = x["row"]
            tgt = RET if x["target"] == "ret" else (names.index(x["target"]) if x["target"] else 0)
            fields = [(TESTS.index(r.test), 4), (x["mode"], 2), (tgt, 5)]
            fields += [(c, 3) for c in pins_code(r.pins)]
            if self.grouped:
                for (gname, ch), c in zip(GROUPS, encode_actions_grouped(r.act)):
                    fields.append((c, bits_for(len(ch))))
            else:
                fl = flags_code(r.act)
                # the 3 counter-load flags are stored as one 2-bit field in v2 accounting
                cl = 1 if "cload" in r.act else 2 if "cload_b" in r.act else 3 if "cload_c" in r.act else 0
                rest = [b for a, b in zip(ACTS, fl) if a not in ("cload", "cload_b", "cload_c")]
                fields += [(cl, 2)] + [(b, 1) for b in rest]
            v, width = pack(fields)
            packed.append(v)
        # decode
        widths = [4, 2, 5, 3, 3, 3]
        if self.grouped:
            widths += [bits_for(len(ch)) for _, ch in GROUPS]
        else:
            widths += [2] + [1] * (len(ACTS) - 3)
        extras = []
        for i, v in enumerate(packed):
            f = unpack(v, widths)
            if self.grouped:
                acts = decode_actions_grouped(f[6:])
            else:
                cl = ["", "cload", "cload_b", "cload_c"][f[6]]
                others = [a for a in ACTS if a not in ("cload", "cload_b", "cload_c")]
                acts = [a for a, b in zip(others, f[7:]) if b] + ([cl] if cl else [])
            extras.append(dict(name=names[i], test=TESTS[f[0]], mode=f[1],
                               target=None if f[1] == 3 else f[2],
                               pins=pins_decode(f[3:6]), acts=acts))
        dec = rebuild(lay, extras)
        return packed, 0, len(packed) * width, dec


class Palette(Scheme):
    """test 4 | mode 2 | target 5 | palette index k.  Palette entries hold pins + actions.
    per_program=True: palette stored in program memory (counted).
    per_program=False: one fixed palette in silicon (not counted, but limits flexibility)."""

    def __init__(self, per_program, grouped_entries, global_palette=None):
        self.per_program, self.grouped = per_program, grouped_entries
        self.global_palette = global_palette
        kind = "per-program palette" if per_program else "fixed palette in silicon"
        self.name = kind + (" (grouped entries)" if grouped_entries and per_program else "")
        self.entry_w = 9 + (GROUP_BITS if grouped_entries else 16)

    def encode(self, prog):
        lay = best_order(prog.rows)
        names = [x["row"].name for x in lay]
        key = lambda r: (tuple(sorted(r.pins.items())), tuple(sorted(r.act)))
        if self.per_program:
            palette = [((), ())] + sorted({key(x["row"]) for x in lay} - {((), ())})
        else:
            palette = self.global_palette
        k = bits_for(len(palette))
        packed = []
        for x in lay:
            r = x["row"]
            tgt = RET if x["target"] == "ret" else (names.index(x["target"]) if x["target"] else 0)
            v, width = pack([(TESTS.index(r.test), 4), (x["mode"], 2), (tgt, 5),
                             (palette.index(key(r)), k)])
            packed.append(v)
        extras = []
        for i, v in enumerate(packed):
            t, m, tg, pi = unpack(v, [4, 2, 5, k])
            pins, acts = palette[pi]
            extras.append(dict(name=names[i], test=TESTS[t], mode=m,
                               target=None if m == 3 else tg,
                               pins=dict(pins), acts=list(acts)))
        dec = rebuild(lay, extras)
        pal_bits = (len(palette) - 1) * self.entry_w if self.per_program else 0
        return packed, pal_bits, len(packed) * width + pal_bits, dec
