"""Directed test for stt_hostbuf: depth, overflow, underflow, sticky flags.

The chip-level test never fills a FIFO -- that is the point of depth 4, which
gives a byte every 30 cycles at the fastest receiver against a host servicing
every 5. So the boundary behaviour SPEC section 9 specifies has no coverage
there at all, and a sticky flag nothing ever sets is a gate that cannot fail.

This drives stt_hostbuf directly and checks:

  * exactly DEPTH bytes fit, and host_tx_full rises on the last one;
  * a write to a full FIFO is DROPPED and leaves the contents intact and in
    order -- not overwriting the oldest, which would corrupt a byte stream;
  * a pop from an empty FIFO is a no-op;
  * both set a sticky flag that stays set;
  * the flags are PER MACHINE: overflowing machine 0 does not flag machine 1.

That last one matters because per-machine FIFOs are the reason this module is
not shared, so cross-talk between them would defeat the point.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from steps import PERIOD_NS, i_, settle

NSM = 5
DEPTH = 4


async def host_write(dut, k, byte):
    dut.host_sel.value = k
    dut.host_tx_data.value = byte
    dut.host_tx_we.value = 1
    await RisingEdge(dut.clk)
    await settle(dut)
    dut.host_tx_we.value = 0
    await settle(dut)


async def machine_pop(dut, k):
    dut.tx_pop.value = 1 << k
    await RisingEdge(dut.clk)
    await settle(dut)
    dut.tx_pop.value = 0
    await settle(dut)


async def machine_push(dut, k, byte):
    dut.rx_data.value = byte << (k * 8)
    dut.rx_push.value = 1 << k
    await RisingEdge(dut.clk)
    await settle(dut)
    dut.rx_push.value = 0
    await settle(dut)


async def host_read(dut, k):
    dut.host_sel.value = k
    await settle(dut)
    v = i_(dut.host_rx_data, "host_rx_data")
    dut.host_rx_re.value = 1
    await RisingEdge(dut.clk)
    await settle(dut)
    dut.host_rx_re.value = 0
    await settle(dut)
    return v


async def reset(dut):
    dut.host_sel.value = 0
    dut.host_tx_we.value = 0
    dut.host_tx_data.value = 0
    dut.host_rx_re.value = 0
    dut.tx_pop.value = 0
    dut.rx_push.value = 0
    dut.rx_data.value = 0
    dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await settle(dut)


@cocotb.test()
async def fifo_boundaries(dut):
    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    await reset(dut)

    assert i_(dut.tx_ne, "tx_ne") == 0, "TX should be empty out of reset"
    assert i_(dut.rx_ovf, "rx_ovf") == 0 and i_(dut.tx_unf, "tx_unf") == 0, \
        "sticky flags should be clear out of reset"

    # ---- TX: fills to DEPTH, then drops -----------------------------------
    for i in range(DEPTH):
        dut.host_sel.value = 0
        await settle(dut)
        assert not i_(dut.host_tx_full, "host_tx_full"), (
            f"TX reported full after only {i} of {DEPTH} bytes")
        await host_write(dut, 0, 0xA0 + i)
    dut.host_sel.value = 0
    await settle(dut)
    assert i_(dut.host_tx_full, "host_tx_full"), (
        f"TX should be full after {DEPTH} bytes")

    await host_write(dut, 0, 0xEE)          # dropped
    assert i_(dut.tx_unf, "tx_unf") == 0, "a TX overflow must not flag underflow"

    # the four originals survive, in order, and 0xEE is nowhere
    for i in range(DEPTH):
        got = i_(dut.tx_data, "tx_data") & 0xFF
        assert got == 0xA0 + i, (
            f"TX byte {i} is 0x{got:02x}, expected 0x{0xA0 + i:02x} -- a full "
            f"FIFO must drop the NEW byte, not overwrite the oldest")
        await machine_pop(dut, 0)
    assert i_(dut.tx_ne, "tx_ne") == 0, "TX should be empty after DEPTH pops"

    # ---- TX underflow ------------------------------------------------------
    await machine_pop(dut, 0)
    assert i_(dut.tx_unf, "tx_unf") & 1, "a pop from empty must set tx_unf"
    unf_after = i_(dut.tx_unf, "tx_unf")
    await machine_pop(dut, 0)
    assert i_(dut.tx_unf, "tx_unf") == unf_after, "tx_unf must be sticky"

    # ---- RX overflow, on a DIFFERENT machine ------------------------------
    for i in range(DEPTH):
        await machine_push(dut, 2, 0xB0 + i)
    assert i_(dut.rx_ovf, "rx_ovf") == 0, f"no overflow at {DEPTH} pushes"
    await machine_push(dut, 2, 0xFF)        # dropped
    assert i_(dut.rx_ovf, "rx_ovf") & (1 << 2), "a push onto full must set rx_ovf"

    for i in range(DEPTH):
        got = await host_read(dut, 2)
        assert got == 0xB0 + i, (
            f"RX byte {i} is 0x{got:02x}, expected 0x{0xB0 + i:02x}")
    dut.host_sel.value = 2
    await settle(dut)
    assert not i_(dut.host_rx_ne, "host_rx_ne"), "RX should be empty after DEPTH reads"

    # ---- the flags are PER MACHINE ----------------------------------------
    ovf, unf = i_(dut.rx_ovf, "rx_ovf"), i_(dut.tx_unf, "tx_unf")
    assert ovf == (1 << 2), (
        f"rx_ovf is 0x{ovf:02x}; only machine 2 overflowed, so the FIFOs are "
        f"not independent")
    assert unf == (1 << 0), (
        f"tx_unf is 0x{unf:02x}; only machine 0 underflowed")

    # ---- reset clears them -------------------------------------------------
    await reset(dut)
    assert i_(dut.rx_ovf, "rx_ovf") == 0 and i_(dut.tx_unf, "tx_unf") == 0, \
        "reset must clear the sticky flags"

    dut._log.info(
        f"hostbuf: depth {DEPTH} exact, full drops the new byte and keeps order, "
        f"empty pop is a no-op, both flags sticky and per machine, reset clears")
