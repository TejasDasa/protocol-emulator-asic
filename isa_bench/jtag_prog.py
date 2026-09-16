"""STT program: JTAG master that walks the TAP from Test-Logic-Reset to
Shift-DR, shifts one byte, and returns to Run-Test/Idle.

Pin slots: 0 = TDI, 1 = TCK, 2 = TMS.  Input 0 = TDO.

The structural cost this exposes: the `single5` row format allows ONE pin write
per row, but JTAG needs TMS and TDI stable before TCK rises and TCK is a third
pin. So a TAP walk spends a row per pin change plus two per clock pulse, in a
way a bit loop does not. Row count, not palette coverage, is what JTAG stresses.
"""
from stt import Row, SttProgram, SttCore


def tck_pulse(name, nxt, extra_act=()):
    """Two rows: TCK high for a bit time, then low for a bit time."""
    return [
        Row(f"{name}H", "tmr", f"{name}L", pins={1: "hi"}, act=list(extra_act)),
        Row(f"{name}L", "tmr", nxt, pins={1: "lo"}),
    ]


def stt_jtag(P):
    rows = []
    # --- walk TLR -> RunTestIdle -> SelectDR -> CaptureDR -> ShiftDR
    rows.append(Row("A", "always", "AH", pins={2: "lo"}, act=["trst"]))
    rows += tck_pulse("A", "B")                 # TLR -> RTI
    rows.append(Row("B", "always", "BH", pins={2: "hi"}))
    rows += tck_pulse("B", "C")                 # RTI -> SelectDR
    rows.append(Row("C", "always", "CH", pins={2: "lo"}))
    rows += tck_pulse("C", "DH")                # SelectDR -> CaptureDR
    rows += tck_pulse("D", "LD")                # CaptureDR -> ShiftDR
    # --- load the byte and present its first bit
    rows.append(Row("LD", "fifo", "LD2", pins={2: "lo"}, act=["load", "cload"]))
    rows.append(Row("LD2", "always", "SHH", pins={0: "sr"}))
    # --- shift loop, one pin write per row (the single5 constraint).
    # 7 iterations, not 8: the TCK edge that leaves Shift-DR (TMS=1) shifts the
    # last bit, which is how JTAG works and costs one loop pass fewer.
    rows.append(Row("SHH", "tmr", "SHL", pins={1: "hi"}, act=["shift", "cdec"]))
    rows.append(Row("SHL", "tmr", "SHD", pins={1: "lo"}))
    rows.append(Row("SHD", "always", "CNT", pins={0: "sr"}))
    rows.append(Row("CNT", "cz", "EX", "SHH"))
    # --- leave Shift-DR: TMS=1 on the last TCK
    rows.append(Row("EX", "always", "EXH", pins={2: "hi"}))
    rows += tck_pulse("EX", "UPH")              # ShiftDR -> Exit1DR
    rows += tck_pulse("UP", "RT")               # Exit1DR -> UpdateDR
    rows.append(Row("RT", "always", "RTH", pins={2: "lo"}, act=["push"]))
    rows += tck_pulse("RT", "B")                # UpdateDR -> RTI, then re-walk
                                                # to SelectDR for the next byte
    prog = SttProgram(rows)
    core = SttCore(prog, slots=[("tdi", "pp"), ("tck", "pp"), ("tms", "pp")],
                   ins=["tdo"], period=P // 2, shift="right", fill="in0",
                   init_pins=[0, 0, 1], cload=(7, 0, 0))
    return core, prog


if __name__ == "__main__":
    core, prog = stt_jtag(32)
    print(f"rows = {len(prog.rows)}")
    for r in prog.rows:
        print(f"  {r.name:5} test={r.test:7} t={str(r.t):5} f={str(r.f):5} "
              f"pins={r.pins} act={r.act}")
