"""The program that was shifted in is the program that is in the memory.

Every lockstep suite loads through this same path, so a load that corrupts
words identically in every test is invisible to all of them: the RTL and the
model would both be driven from whatever actually landed, or the machine
simply sits still and the suite reports "no transitions" rather than "wrong
bits". This reads the CFGMEM contents back and compares them word for word.

It exists because that failure happened. `test_skew` reimplemented the
instruction-shift loop instead of using the shared one and left out the settle
past the clock edge, so it read the busy flag as it was BEFORE the edge. A
busy that had just gone high read as idle, the next bit went into a busy
memory and was lost -- exactly one bit at every 32-bit word boundary. Word N
came back as word N shifted right by N bits. Row 0 survived, so the machine
started, consumed a byte and drove CS low before executing a garbage row 1
that branched to 0 and stopped. It looked like a gate-level problem for days;
it reproduces here in seconds. See docs/writeup.md 4.3 entry 13.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from lockstep import CFG_BITS, capture_benchmark, config_word, encode_rows
from pinmap import PinPlan

PERIOD_NS = 20
STT_ROWS = 32
NTILE, TILE_WORDS = 2, 16
NSM, NIN = 5, 2
HOST_STB, HOST_DIN, HOST_DOUT = 15, 14, 13


async def settle():
    await Timer(PERIOD_NS // 2, unit="ns")


async def shift_ctl(dut, enable_bit, bits, nbits, tag):
    for i in range(nbits):
        stalled = 0
        while (int(dut.uo_out.value) & 1) if dut.uo_out.value.is_resolvable else 0:
            dut.ui_in.value = 0
            await RisingEdge(dut.clk)
            await settle()
            stalled += 1
            assert stalled < 300, f"{tag}: imem busy never cleared at bit {i}"
        dut.ui_in.value = (1 << enable_bit) | (((bits >> i) & 1) << 4)
        await RisingEdge(dut.clk)
        await settle()
    dut.ui_in.value = 0
    await RisingEdge(dut.clk)
    await settle()


@cocotb.test()
async def imem_load(dut):
    name = os.environ.get("PROG", "spi")
    core = capture_benchmark(name, 32)["core"]
    words, decoded = encode_rows(core.p)
    core.p, core.row = decoded, 0

    plan = PinPlan()
    for s in range(len(core.slots)):
        plan.drive(0, s, s)
    for m in range(NSM):
        for i in range(NIN):
            plan.read(m, i, 0)
    plan.host_port(dout_pin=HOST_DOUT, stb_pin=HOST_STB, din_pin=HOST_DIN)
    sel, nsel = plan.chain([core.p] + [None] * (NSM - 1))

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await settle()

    await shift_ctl(dut, 1, config_word(core), CFG_BITS, "cfg")
    want = list(words) + [0] * (STT_ROWS - len(words))
    bits = 0
    for i, w in enumerate(want):
        bits |= w << (32 * i)
    await shift_ctl(dut, 0, bits, 32 * len(want), "imem")
    await shift_ctl(dut, 2, sel, nsel, "pinsel")

    # A tile is loaded by walking a one-hot enable from the far end, so words
    # land in reverse within each tile (cfgmem_ihp16_model.v).
    im = dut.u_chip.u_array.g_sm[0].u_sm.u_imem
    got = []
    for t in range(NTILE):
        tile = im.g_tile[t].u_tile.cfgmem
        raw = [int(tile[r].value) if tile[r].value.is_resolvable else None
               for r in range(TILE_WORDS)]
        got.extend(reversed(raw))

    def dropped_bits(w, g):
        """How many bits went missing before this word, if that is what it is.

        A dropped bit shifts the word right and pulls the NEXT word's bits into
        the top, so the low 32-n bits match `w >> n` while the high bits are
        someone else's. Matching on the low bits is what names the mechanism.
        """
        if g is None:
            return None
        for n in range(1, 32):
            if (g & ((1 << (32 - n)) - 1)) == (w >> n):
                return n
        return None

    bad = [(i, want[i], got[i]) for i in range(STT_ROWS) if got[i] != want[i]]
    if bad:
        lines = []
        for i, w, g in bad[:12]:
            n = dropped_bits(w, g)
            lines.append(
                f"    row {i:<2d} want 0x{w:08x} got "
                + ("X" * 8 if g is None else f"0x{g:08x}")
                + (f"   (low bits = want >> {n}: {n} bits dropped)" if n else ""))
        lines = "\n".join(lines)
        raise AssertionError(
            f"{name}: {len(bad)} of {STT_ROWS} instruction words came back "
            f"different from what was shifted in:\n{lines}\n"
            "  A word that reads as the intended word shifted right by N is N "
            "dropped bits in the serial stream, one per word boundary -- the "
            "loader was fed a bit while imem_ld_busy was high.")
    dut._log.info(f"{name}: all {STT_ROWS} instruction words loaded intact")
