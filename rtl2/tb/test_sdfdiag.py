"""Why did nothing reach a pin? Watch uo_out through the whole load sequence.

uo_out[0] carries imem load-busy while run is low (SPEC 11.1), so it must
toggle during loading. If it never moves, the failure is upstream of the
protocol entirely.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from lockstep import CFG_BITS, capture_benchmark, config_word, encode_rows
from pinmap import PinPlan

SCALE = int(os.environ.get("SDF_SCALE", "1000"))
PERIOD_NS = 20 * SCALE
NSM, NSLOT, NIN = 5, 3, 2


def rd(sig):
    return int(sig.value) if sig.value.is_resolvable else None


@cocotb.test()
async def diag(dut):
    core = capture_benchmark("spi", 32)["core"]
    words, decoded = encode_rows(core.p)
    core.p, core.row = decoded, 0

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut._log.info(f"DIAG after reset asserted: uo_out={rd(dut.uo_out)} "
                  f"uio_out={rd(dut.uio_out)} uio_oe={rd(dut.uio_oe)}")
    dut.rst_n.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut._log.info(f"DIAG after reset released: uo_out={rd(dut.uo_out)}")

    # drive the config chain enable and watch whether busy ever appears
    seen = set()
    n = 0
    for i in range(300):
        dut.ui_in.value = (1 << 1) | ((i & 1) << 4)
        await RisingEdge(dut.clk)
        v = rd(dut.uo_out)
        if v not in seen:
            seen.add(v)
            dut._log.info(f"DIAG cfg-shift cycle {i}: uo_out={v}")
        n += 1
    dut._log.info(f"DIAG distinct uo_out values during cfg shift: {sorted(x for x in seen if x is not None)}")

    # now the imem chain, which must raise busy
    seen2 = set()
    for i in range(400):
        dut.ui_in.value = (1 << 0) | ((i & 1) << 4)
        await RisingEdge(dut.clk)
        v = rd(dut.uo_out)
        seen2.add(v)
    dut._log.info(f"DIAG distinct uo_out during imem shift: {sorted(x for x in seen2 if x is not None)}")
    dut._log.info(f"DIAG busy(uo_out[0]) ever high? "
                  f"{any((x or 0) & 1 for x in seen2 if x is not None)}")
