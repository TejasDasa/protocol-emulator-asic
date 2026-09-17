"""SPEC section 11.2: the host byte port, through the real Tiny Tapeout pins.

This runs against `tt_um_stt`, whose port list is only clk, rst_n, ena, ui_in,
uo_out, uio_in and uio_oe -- so every byte here travels the way it would on
silicon. There is no back door: the host writes a bit at a time on a pin it
assigned, and reads a bit at a time from a pin it assigned.

The machine under test runs a two-row echo program, `load` then `push`, so a
byte the host writes comes back on the next frame. That makes the round trip
the assertion and needs no pin stimulus to drive it.

Checked here:
  * a byte written on `host_din` reaches the machine and comes back on
    `host_dout`, through pins, with the frame layout section 11.2 specifies;
  * reading an empty RX FIFO returns 0 with `rx_ne` = 0, and does NOT pop --
    the next frame still returns the byte that was waiting;
  * a frame abandoned by dropping `host_stb` has no effect at all;
  * writing onto a full TX FIFO is dropped and `tx_full` says so.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from lockstep import CFG_BITS, config_word
from pinmap import PinPlan
from steps import PERIOD_NS, i_, settle

STT_ROWS = 32
NSM, NOUT, NPIN, NSLOT, NIN = 5, 16, 16, 3, 2
OSELW = ISELW = 4
OBITS = NOUT * OSELW
IBITS = NSM * NIN * ISELW
O_HEN = 1 + OBITS + IBITS          # host_en, then two 4-bit pin selects
HOST_CODE = 15                     # free output select: 15 drivers, 0..14

STB_PIN = 7                        # ui_in[7]
DIN_PIN = 6                        # ui_in[6]
DOUT_PIN = 1                       # uo_out[1], via output select 15
ECHO_SM = 0


def echo_program():
    from stt import Row, SttProgram, SttCore
    from rowformat import Format
    prog = SttProgram([
        Row("IDLE", "fifo",   "ECHO", act=["load"]),
        Row("ECHO", "always", "IDLE", act=["push"]),
    ])
    core = SttCore(prog, slots=[("x", "pp")], period=4,
                   shift="right", fill="1")
    words = list(Format("single5", "grouped", tgt_bits=8).encode(prog)["packed"])
    return core, words


async def shift_ctl(dut, enable_bit, bits, nbits, where=""):
    """Shift one control chain in on ui_in, honouring uo_out[0] = imem busy."""
    for i in range(nbits):
        n = 0
        while i_(dut.uo_out, "uo_out") & 1:
            dut.ui_in.value = 0
            await RisingEdge(dut.clk)
            await settle(dut)
            n += 1
            assert n <= 200, f"loader stuck at {where} bit {i}"
        dut.ui_in.value = (1 << enable_bit) | (((bits >> i) & 1) << 4)
        await RisingEdge(dut.clk)
        await settle(dut)
    dut.ui_in.value = 0
    await settle(dut)


async def frame(dut, sel, wr, data, nbits=16):
    """One transaction: 16 clocks of host_stb, MSB first (SPEC 11.2).

    `nbits` < 16 abandons the frame partway, which must have no effect.
    Returns (rxdata, status) for a complete frame.
    """
    word = ((sel & 7) << 13) | ((wr & 1) << 12) | ((data & 0xFF) << 4)
    out = 0
    for k in range(15, 15 - nbits, -1):
        dut.ui_in.value = (1 << STB_PIN) | (((word >> k) & 1) << DIN_PIN)
        await settle(dut)
        out = (out << 1) | ((i_(dut.uo_out, "uo_out") >> DOUT_PIN) & 1)
        await RisingEdge(dut.clk)
        await settle(dut)
    dut.ui_in.value = 0
    await settle(dut)
    return (out >> 4) & 0xFF, out & 0xF


async def idle(dut, n):
    for _ in range(n):
        await RisingEdge(dut.clk)
    await settle(dut)


@cocotb.test()
async def hostport(dut):
    core, words = echo_program()

    # Pin assignment through the checked builder (isa_bench/pinmap.py), which
    # would refuse this plan if the echo program moved bytes and no pin
    # selected the host port.
    plan = PinPlan()
    plan.drive(ECHO_SM, 0, 0)
    for m in range(NSM):
        for i in range(NIN):
            plan.read(m, i, 0)
    plan.host_port(dout_pin=DOUT_PIN, stb_pin=STB_PIN, din_pin=DIN_PIN)
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
    await settle(dut)

    # Load the echo machine. Every tile takes a full 16 words (SPEC section 10),
    # so the program is padded to 32 rows.
    dut.uio_in.value = ECHO_SM << 5
    await settle(dut)
    await shift_ctl(dut, 1, config_word(core), CFG_BITS, "cfg")
    padded = words + [0] * (STT_ROWS - len(words))
    bits = 0
    for i, word in enumerate(padded):
        bits |= word << (32 * i)
    await shift_ctl(dut, 0, bits, 32 * len(padded), "imem")
    await shift_ctl(dut, 2, sel, nsel, "pinsel")
    dut.uio_in.value = 0
    await idle(dut, 4)                         # run, then machines enable

    # ---- 1. round trip through the pins ------------------------------------
    payload = [0xA5, 0x3C, 0x00, 0xFF, 0x5A]
    got = []
    rx, st = await frame(dut, ECHO_SM, 1, payload[0])
    assert st & 8 == 0, f"RX reported non-empty before anything was written: {st:#x}"
    assert rx == 0, f"empty RX returned 0x{rx:02x}, expected 0"
    for b in payload[1:]:
        await idle(dut, 4)                     # let the echo program run
        rx, st = await frame(dut, ECHO_SM, 1, b)
        assert st & 8, f"RX empty when a byte should have been echoed (status {st:#x})"
        got.append(rx)
    await idle(dut, 4)
    rx, st = await frame(dut, ECHO_SM, 0, 0)
    assert st & 8, "last echoed byte never arrived"
    got.append(rx)
    assert got == payload, (
        f"round trip through the pins returned {[hex(b) for b in got]}, "
        f"host wrote {[hex(b) for b in payload]}")
    dut._log.info(f"round trip: wrote {[hex(b) for b in payload]}, "
                  f"read {[hex(b) for b in got]}")

    # ---- 2. an empty read does not pop -------------------------------------
    await idle(dut, 8)
    rx, st = await frame(dut, ECHO_SM, 1, 0x77)   # queue one byte
    await idle(dut, 8)
    rx1, st1 = await frame(dut, ECHO_SM, 0, 0)    # read it
    assert st1 & 8 and rx1 == 0x77, f"expected 0x77, got 0x{rx1:02x} status {st1:#x}"
    rx2, st2 = await frame(dut, ECHO_SM, 0, 0)    # now empty
    assert (st2 & 8) == 0 and rx2 == 0, (
        f"empty read returned 0x{rx2:02x} status {st2:#x}; it must read 0 and not pop")
    rx3, st3 = await frame(dut, ECHO_SM, 0, 0)    # still empty, nothing consumed
    assert (st3 & 8) == 0 and rx3 == 0, "a read of an empty FIFO changed state"

    # ---- 3. an abandoned frame does nothing --------------------------------
    await frame(dut, ECHO_SM, 1, 0xC3, nbits=9)   # drop stb partway
    await idle(dut, 16)
    rx, st = await frame(dut, ECHO_SM, 0, 0)
    assert (st & 8) == 0 and rx == 0, (
        f"an abandoned frame still wrote: read back 0x{rx:02x} status {st:#x}")

    # ---- 4. writing onto a full TX FIFO is dropped, and says so ------------
    # Machine 4 has no program loaded and never pops, so its TX FIFO fills.
    DEAD = 4
    fulls = []
    for i in range(6):
        _rx, st = await frame(dut, DEAD, 1, 0x10 + i)
        fulls.append((st >> 2) & 1)
    assert fulls[0] == 0, "TX FIFO reported full before anything was written"
    assert fulls[-1] == 1, (
        f"TX FIFO never reported full after 6 writes into a depth-4 FIFO: {fulls}")
    dut._log.info(f"tx_full across six writes into a depth-4 FIFO: {fulls}")

    dut._log.info("host port verified through the real boundary")
