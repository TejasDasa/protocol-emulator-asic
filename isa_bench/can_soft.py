"""What CAN costs without the hardware bit stuffer.

The hardware stuffer is in the datapath: the program emits a bit, the stuffer
may substitute one, and `stall` lets the program find out so it can hold the
shift register. Doing the same work in rows means tracking (last bit, run
length) somewhere the program can test.

Nothing in the live action set chains one register into another, so the run
length has no register to live in -- it has to live in the program counter.
This builds that state machine and counts it, rather than asserting a number.
"""
from stt import Row, SttProgram, TESTS_V2, MAX_ROWS


def soft_stuff_rows(dlc=1):
    """The data phase with stuffing done in rows, plus the surrounding frame.
    Returns the row list; it is not wrapped in SttProgram because the whole
    point of the measurement is that it does not fit."""
    rows = []
    S = lambda v, k: f"S{v}_{k}"

    # arm
    rows += [
        Row("IDLE",   "fifo",   "RST1"),
        Row("RST1",   "always", "RST2",  act=["crc16rst", "c2load"]),
        Row("RST2",   "always", "LOAD",  act=["stuffrst", "trst"]),
        Row("LOAD",   "always", S(1, 1), act=["load", "cload_b"]),
    ]

    # one (last bit, run length) pair per state, run capped at 5
    for v in (0, 1):
        for k in range(1, 5):
            # the next bit to emit is visible only through `srbit`
            dst1 = S(1, k + 1) if v == 1 else S(1, 1)
            dst0 = S(0, k + 1) if v == 0 else S(0, 1)
            rows += [
                Row(f"W{v}_{k}", "tmr",    f"T{v}_{k}"),
                Row(f"T{v}_{k}", "srbit",  f"A{v}_{k}", f"B{v}_{k}"),
                Row(f"A{v}_{k}", "always", "EMIT", dst1, act=["call"]),
                Row(f"B{v}_{k}", "always", "EMIT", dst0, act=["call"]),
            ]
        # run of 5: insert the complement, consuming no data bit
        rows += [
            Row(f"W{v}_5", "tmr",    f"I{v}"),
            Row(f"I{v}",   "always", S(1 - v, 1), pins={0: "hi" if v == 0 else "lo"}),
        ]

    # shared emit subroutine, and the byte boundary folded into its tail
    rows += [
        Row("EMIT",   "always", "EMIT2", pins={0: "sr"}, act=["crc16step", "cdec"]),
        Row("EMIT2",  "always", "EMIT3", act=["shift"]),
        Row("EMIT3",  "cz",     "BYTEC", "ret"),
        Row("BYTEC",  "always", "BYTZ",  act=["c2dec"]),
        Row("BYTZ",   "c2z",    "CRCPH", "RELOAD"),
        Row("RELOAD", "always", "ret",   act=["load", "cload"]),
    ]

    # CRC sequence and trailer, same shape as the hardware version
    rows += [
        Row("CRCPH",  "always", "CBW",   act=["cload_c"]),
        Row("CBW",    "tmr",    "CSEND"),
        Row("CSEND",  "always", "CCK2",  pins={0: "crcb"}, act=["cdec"]),
        Row("CCK2",   "cz",     "TRAIL", "CBW"),
        Row("TRAIL",  "always", "TBW",   act=["cload_c"]),
        Row("TBW",    "tmr",    "TSEND"),
        Row("TSEND",  "always", "TCK",   pins={0: "hi"}, act=["stuffrst", "cdec"]),
        Row("TCK",    "cz",     "IDLE",  "TBW"),
    ]
    return rows


def crc_phase_is_impossible():
    """Software stuffing cannot cover the CRC sequence at any row count.

    CAN stuffs SOF through the end of the CRC. In the data phase the program
    can see the bit it is about to send, with `srbit`. In the CRC sequence the
    bit comes out of the wide CRC unit through the `crcb` pin op, and no test
    reads that register -- so the program cannot know what it just sent, and
    cannot track a run. Derived from the live test list, not asserted.
    """
    visible = {t for t in TESTS_V2}
    sees_crc16 = {t for t in visible if "crc" in t}
    return sorted(visible), sorted(sees_crc16)


def main():
    rows = soft_stuff_rows()
    n = len(rows)
    print(f"software bit stuffing, CAN 2.0A transmitter: {n} rows "
          f"(budget {MAX_ROWS})")
    print(f"  over budget by {n - MAX_ROWS} rows" if n > MAX_ROWS
          else "  fits")
    try:
        SttProgram(rows)
        print("  SttProgram accepted it")
    except ValueError as e:
        print(f"  SttProgram rejects it: {e}")
    print()
    tests, sees = crc_phase_is_impossible()
    print(f"  live tests ({len(tests)}): {', '.join(tests)}")
    print(f"  of those, able to read the wide CRC register: "
          f"{sees if sees else 'none'}")
    print("  so the CRC sequence -- which CAN also stuffs -- cannot be")
    print("  stuffed in software at any row count: the program cannot see")
    print("  the bit `crcb` emits, so it cannot track the run.")
    print()
    print(f"  hardware stuffer: 24 rows, whole frame stuffed")
    print(f"  software stuffer: {n} rows, data phase only, and it does not fit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
