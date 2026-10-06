"""The mutation generator, shared by every suite that needs one.

Lifted out of mutate.py so a caller can corrupt a program without importing
gensweep, which runs a full sweep at import time. mutate.py still owns the
3-ISA benchmark run and the kill-rate gate; this module owns only the
corruptions themselves, so there is one definition of what a mutant is.

Mutation classes are documented in mutate.py.
"""
from stt import ACT_ORDER, Row, SttProgram, TESTS_V2

TESTS = sorted(TESTS_V2)
PINOPS = ["hold", "lo", "hi", "sr", "tgl", "d0", "d1"]
SLOTS = [0, 1, 2, "pair"]


def _clone(prog):
    return SttProgram([Row(r.name, r.test, r.t, r.f, dict(r.pins), list(r.act))
                       for r in prog.rows])


def mutants(prog):
    """Yield (class, description, mutated_program) -- one corruption each."""
    n = len(prog.rows)
    names = [r.name for r in prog.rows]

    for i, r in enumerate(prog.rows):
        # --- wrong test code
        alt = TESTS[(TESTS.index(r.test) + 1) % len(TESTS)] if r.test in TESTS else "always"
        if alt != r.test:
            m = _clone(prog); m.rows[i].test = alt
            yield "test", f"row {r.name}: test {r.test} -> {alt}", m

        # --- branch target shifted by one row
        if r.t in names:
            j = (names.index(r.t) + 1) % n
            if names[j] != r.t:
                m = _clone(prog); m.rows[i].t = names[j]
                yield "target", f"row {r.name}: target {r.t} -> {names[j]}", m

        # --- branch mode: swap the true and false exits
        if r.t != r.f:
            m = _clone(prog); m.rows[i].t, m.rows[i].f = r.f, r.t
            yield "mode", f"row {r.name}: swap true/false exits", m

        # --- drop one action
        for a in r.act:
            m = _clone(prog); m.rows[i].act = [x for x in r.act if x != a]
            yield "act_drop", f"row {r.name}: drop action {a}", m

        # --- add one spurious action (first one not already present)
        for a in ACT_ORDER:
            if a not in r.act:
                m = _clone(prog); m.rows[i].act = list(r.act) + [a]
                yield "act_add", f"row {r.name}: add action {a}", m
                break

        # --- wrong pin op / wrong slot
        for slot, op in list(r.pins.items()):
            alt_op = PINOPS[(PINOPS.index(op) + 1) % len(PINOPS)] if op in PINOPS else "hold"
            if alt_op != op:
                m = _clone(prog); m.rows[i].pins = dict(r.pins); m.rows[i].pins[slot] = alt_op
                yield "pinop", f"row {r.name}: pin {slot} op {op} -> {alt_op}", m
            alt_slot = SLOTS[(SLOTS.index(slot) + 1) % len(SLOTS)] if slot in SLOTS else 0
            if alt_slot != slot:
                m = _clone(prog); p = dict(r.pins); p.pop(slot); p[alt_slot] = op
                m.rows[i].pins = p
                yield "pinslot", f"row {r.name}: pin op {op} slot {slot} -> {alt_slot}", m

    # --- swap adjacent rows
    for i in range(n - 1):
        m = _clone(prog)
        m.rows[i], m.rows[i + 1] = m.rows[i + 1], m.rows[i]
        m = SttProgram(m.rows)
        yield "swap", f"swap rows {names[i]} / {names[i+1]}", m


