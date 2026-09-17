"""cocotb test: rtl2 against SttCore, cycle by cycle, for each reference program.

Select the program with the PROG environment variable; rtl2/tb/run_tests.py
runs all six. The loop itself lives in steps.py, shared with the mutation test.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock

from lockstep import capture_benchmark, encode_rows
from steps import PERIOD_NS, reset_and_load, run_lockstep


@cocotb.test()
async def lockstep(dut):
    name = os.environ.get("PROG", "uart_tx")
    period = int(os.environ.get("BIT_PERIOD", "32"))

    stash = capture_benchmark(name, period)
    core, w, done, max_cycles = (stash["core"], stash["world"],
                                 stash["done"], stash["max_cycles"])

    # SPEC section 13 runs the models on the DECODED rows, which is what proves
    # the encoding lossless. It also means the model and the RTL index rows the
    # same way: the encoder reorders rows and may add trampolines.
    words, decoded = encode_rows(core.p)
    core.p, core.row = decoded, 0

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    await reset_and_load(dut, core, words, w)

    assert int(dut.imem_ld_addr.value) == 0, (
        f"write pointer is {int(dut.imem_ld_addr.value)} after loading a full "
        f"32 rows; it should have wrapped to 0")

    cycles, finished = await run_lockstep(dut, core, w, done, max_cycles, name,
                                          len(core.slots), words)
    dut._log.info(f"{name}: {cycles} cycles in lockstep, "
                  f"{'benchmark completed' if finished else 'ran to max_cycles'}, "
                  f"{len(words)} rows, no divergence")
    assert cycles > 0, "no cycles ran"
