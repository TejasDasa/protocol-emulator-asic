"""Random 32-row programs, generated at the ENCODED level.

The mutation suite corrupts the six reference programs, so it can only reach
decode paths near programs somebody wrote. Two things it structurally cannot
reach:

  * `next` wrapping from row 31 to row 0 (SPEC section 5). No reference program
    has 32 rows and mutation does not add rows, so nothing in the repository
    executes that wrap.
  * most combinations of mode x target x pin op x action group. Only one row of
    one program (usb row 8) uses RET at all.

These programs are 32 rows of random valid fields, so row 31 exists and its
`next` exit wraps. Words are generated first and the symbolic program is DECODED
from them, which guarantees the model and the RTL are running the identical
program rather than two encodings of the same intent.

The model is authoritative (SPEC section 0), so no expected output is needed:
any program the model can run is a valid test, and the only question is whether
the RTL agrees.
"""
import json
import os
import random

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", ".."))
SPEC = json.load(open(os.path.join(ROOT, "spec", "isa.json")))

NTESTS = len(SPEC["tests"])
NPINOPS = len(SPEC["pin_ops"])
GROUPS = [(g["name"], len(g["choices"])) for g in SPEC["action_groups"]]
GROUP_ACTS = {g["name"]: {c["code"]: list(c["actions"]) for c in g["choices"]}
              for g in SPEC["action_groups"]}
TEST_NAME = {t["code"]: t["name"] for t in SPEC["tests"]}
PINOP_NAME = {p["code"]: p["name"] for p in SPEC["pin_ops"]}
FIELDS = {f["name"]: (f["lsb"], f["width"]) for f in SPEC["fields"]}
RET = SPEC["ret_code"]
NROWS = SPEC["max_rows"]


def pack(fields):
    v = 0
    for name, val in fields.items():
        lsb, wd = FIELDS[name]
        assert 0 <= val < (1 << wd), (name, val)
        v |= val << lsb
    return v


def random_words(rng, nrows=NROWS, p_ret=0.08):
    """One random encoded row per index, all fields legal."""
    words = []
    for i in range(nrows):
        mode = rng.randrange(4)
        # RET is deliberately NOT generated on SKIP. SPEC section 5 says target
        # 255 means return, but SttCore resolves 'ret' only on the TRUE exit
        # while SKIP feeds the target field to the FALSE exit, so the model
        # would raise KeyError. That disagreement is recorded in rtl2/README.md;
        # generating it here would test the model's limitation, not the RTL.
        if mode in (0, 1) and rng.random() < p_ret:
            target = RET
        else:
            target = rng.randrange(nrows)

        slot = rng.randrange(4)
        # d0/d1 on a single slot is rejected by the encoder (SPEC section 7),
        # so a program cannot express it and neither does this.
        ops = list(range(NPINOPS))
        if slot != 3:
            ops = [o for o in ops if PINOP_NAME[o] not in ("d0", "d1")]
        words.append(pack({
            "test": rng.randrange(NTESTS),
            "mode": mode,
            "target": target,
            "pin_slot": slot,
            "pin_op": rng.choice(ops),
            "act_sr": rng.randrange(GROUPS[0][1]),
            "act_c1": rng.randrange(GROUPS[1][1]),
            "act_c2": rng.randrange(GROUPS[2][1]),
            "act_tm": rng.randrange(GROUPS[3][1]),
            "act_xx": rng.randrange(GROUPS[4][1]),
        }))
    return words


def decode(words):
    """words -> SttProgram, resolving each mode's exits exactly as SPEC section 5
    and rowenc.rebuild do."""
    from stt import Row, SttProgram
    names = [f"R{i}" for i in range(len(words))]
    rows = []
    for i, wd in enumerate(words):
        f = {n: (wd >> l) & ((1 << w) - 1) for n, (l, w) in FIELDS.items()}
        nxt = names[(i + 1) % len(words)]        # SPEC section 5: wraps mod 32
        me = names[i]
        tgt = "ret" if f["target"] == RET else names[f["target"]]
        mode = f["mode"]
        if mode == 0:
            t, fa = tgt, me
        elif mode == 1:
            t, fa = tgt, nxt
        elif mode == 2:
            t, fa = nxt, tgt
        else:
            t, fa = nxt, me
        acts = []
        for (gname, _), key in zip(GROUPS, ("act_sr", "act_c1", "act_c2",
                                            "act_tm", "act_xx")):
            acts.extend(GROUP_ACTS[gname][f[key]])
        pins = {}
        op = PINOP_NAME[f["pin_op"]]
        if op != "hold":
            pins = {("pair" if f["pin_slot"] == 3 else f["pin_slot"]): op}
        rows.append(Row(me, TEST_NAME[f["test"]], t, fa, pins=pins, act=acts))
    return SttProgram(rows)
