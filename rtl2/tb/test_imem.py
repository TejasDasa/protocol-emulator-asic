"""Directed load-path test: write a known pattern, read back every row.

The three lockstep suites all load the program through the SAME serial path, so
a load-path bug that corrupts a row would corrupt it identically for the model
and the RTL... except it would not, because the model never goes through that
path at all -- it runs the symbolic program directly. A wrong word would show up
as a divergence. What they do NOT give is coverage: they visit whatever rows the
program branches to, and nothing guarantees all 32 addresses are ever read.

This does. Every address is written with a distinct payload and then read back
through the real read path -- the row pointer is walked across all 32 addresses
by a program whose rows each branch to the next -- so it keeps working when the
behavioural array is replaced by two CFGMEM_IHP16 macros and a one-hot WROW
decode. That decode is new logic the behavioural model does not need, which is
exactly where a load-path bug could enter unseen.

The control fields carry the walk; the remaining 18 bits carry the pattern:

    test = always, mode = BRANCH, target = (i + 1) mod 32     -> 14 bits
    pin_slot, pin_op, act_sr, act_c1, act_c2, act_tm, act_xx  -> 18 bits payload

Arbitrary payloads are safe to load: every unassigned code decodes to "no
action" or "hold" rather than X, so a pattern cannot put the core in an
undefined state while the memory is being checked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from steps import PERIOD_NS, i_, settle, shift_in

NROWS = 32
PAYLOAD_BITS = 18
PAYLOAD_MASK = (1 << PAYLOAD_BITS) - 1

# test(4) | mode(2) | target(8) | payload(18)
def word_for(i, payload):
    return (0                      # test = always
            | (1 << 4)             # mode = BRANCH: true -> target, false -> next
            | (((i + 1) % NROWS) << 6)
            | ((payload & PAYLOAD_MASK) << 14))


def patterns():
    """(name, [payload per row]) -- enough to catch a stuck, swapped or
    shorted bit anywhere in the 18 payload bits, and a misplaced row."""
    yield "zeros", [0] * NROWS
    yield "ones", [PAYLOAD_MASK] * NROWS
    yield "walking-one", [1 << (i % PAYLOAD_BITS) for i in range(NROWS)]
    yield "walking-zero", [PAYLOAD_MASK ^ (1 << (i % PAYLOAD_BITS))
                           for i in range(NROWS)]
    yield "alternating", [0x2AAAA if i % 2 else 0x15555 for i in range(NROWS)]
    # A distinct value per row: catches a row written to the wrong address,
    # which a uniform pattern cannot.
    yield "unique", [(i * 0x2F5B) & PAYLOAD_MASK for i in range(NROWS)]


async def load_words(dut, words):
    dut.en.value = 0
    dut.imem_ld_en.value = 0
    dut.cfg_ld_en.value = 0
    dut.ld_in.value = 0
    dut.tx_ne.value = 0
    dut.tx_data.value = 0
    dut.pin_in.value = 0
    dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await settle(dut)

    # Configuration is irrelevant to a memory test except that the period must
    # be sane; load a minimal one so the timer does not sit at zero.
    from lockstep import CFG_BITS, O_PERIOD, O_SRW
    cfg = (8 << O_PERIOD) | (8 << O_SRW)
    await shift_in(dut, dut.cfg_ld_en, cfg, CFG_BITS)

    bits = 0
    for i, wd in enumerate(words):
        bits |= wd << (32 * i)
    await shift_in(dut, dut.imem_ld_en, bits, 32 * len(words))


@cocotb.test()
async def imem_load_readback(dut):
    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    checked = 0

    for pname, payloads in patterns():
        words = [word_for(i, p) for i, p in enumerate(payloads)]
        await load_words(dut, words)

        assert i_(dut.imem_ld_addr, "imem_ld_addr") == 0, (
            f"{pname}: write pointer is {i_(dut.imem_ld_addr)} after writing "
            f"{NROWS} rows; it should have wrapped to 0")

        # Walk the row pointer across every address and check what the read
        # path returns. Each row branches to the next, so 32 cycles visit all.
        dut.en.value = 1
        await settle(dut)
        seen = {}
        for step in range(NROWS):
            addr = i_(dut.dbg_row, "dbg_row")
            seen[addr] = i_(dut.row, "row")
            checked += 1
            await RisingEdge(dut.clk)
            await settle(dut)

        bad = {a: g for a, g in seen.items() if g != words[a]}
        if bad:
            lines = [f"{pname}: {len(bad)} of {len(seen)} addresses wrong"]
            for a in sorted(seen):
                mark = "  <-- WRONG" if a in bad else ""
                where = [j for j, wv in enumerate(words) if wv == seen[a]]
                lines.append(f"    addr {a:2d}: read 0x{seen[a]:08x}  "
                             f"expected 0x{words[a]:08x}"
                             f"{' (that is word ' + str(where) + ')' if where else ''}"
                             f"{mark}")
            raise AssertionError("\n".join(lines[:20]))
        dut.en.value = 0
        await settle(dut)

        assert set(seen) == set(range(NROWS)), (
            f"{pname}: the walk visited {len(seen)} of {NROWS} addresses, "
            f"missing {sorted(set(range(NROWS)) - set(seen))}")
        dut._log.info(f"{pname}: all {NROWS} addresses written and read back correctly")

    dut._log.info(f"imem load path: {checked} address reads checked across "
                  f"{len(list(patterns()))} patterns")
    assert checked == NROWS * len(list(patterns()))
