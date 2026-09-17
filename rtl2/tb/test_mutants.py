"""Mutation testing against rtl2, not against the models.

The six reference programs pass in cycle-exact lockstep, but they were written
to drive six protocols, not to cover the ISA: tb/coverage.py measures them at
93.9% of defined field values, and the combinations they reach are a much
smaller fraction still. A decode path no program takes is a path whose RTL has
never been compared against anything.

So: take the same single-point corruptions `isa_bench/mutate.py` applies to a
program, encode each mutant at the frozen row format, and run it on BOTH the
model and the RTL in lockstep. The mutant is not expected to pass its benchmark
-- that is what mutate.py measures. What is expected is that the RTL and the
model AGREE about what the corrupted program does, cycle for cycle. They are
executing the same rows; if they disagree, the RTL decodes something wrong, and
the mutation is just the thing that steered execution onto that path.

Every mutant runs in one simulator invocation, with a reset and reload between
them, because starting Icarus per mutant would dominate the runtime.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock

from lockstep import capture_benchmark, encode_rows
from steps import PERIOD_NS, Divergence, reset_and_load, run_lockstep
from coverage_util import CodeCoverage

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "isa_bench")))
from mutate import mutants


@cocotb.test()
async def mutant_lockstep(dut):
    names = os.environ.get("MUT_PROGS", "uart_tx,uart_rx,spi,i2c,usb,jtag").split(",")
    period = int(os.environ.get("BIT_PERIOD", "32"))
    cap = int(os.environ.get("MUT_CYCLES", "1200"))
    limit = int(os.environ.get("MUT_LIMIT", "0"))    # 0 = no limit

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())

    cov = CodeCoverage()
    checked = skipped_encode = skipped_model = 0
    diverged = []
    per_prog = {}

    for name in names:
        name = name.strip()
        if not name:
            continue
        base = capture_benchmark(name, period)["core"].p
        n_here = 0
        for kind, desc, mprog in mutants(base):
            if limit and checked >= limit:
                break
            # A mutant that cannot be expressed at the frozen row format is not
            # a test of the RTL. Counted, not silently dropped.
            try:
                words, decoded = encode_rows(mprog)
            except Exception:
                skipped_encode += 1
                continue

            stash = capture_benchmark(name, period)
            core, w, done, max_cycles = (stash["core"], stash["world"],
                                         stash["done"], stash["max_cycles"])
            core.p, core.row = decoded, 0

            await reset_and_load(dut, core, words, w)
            label = f"{name}/{kind}/{desc}"
            try:
                await run_lockstep(dut, core, w, done, min(max_cycles, cap),
                                   label, len(core.slots), words, cov=cov)
            except Divergence as d:
                diverged.append(str(d))
                dut._log.error(str(d))
            except Exception as e:
                # The MODEL fell over on this mutant (an unreachable target, an
                # input index a corrupted test code does not have). Nothing to
                # compare, so it is not evidence either way.
                skipped_model += 1
                dut._log.debug(f"{label}: model raised {type(e).__name__}: {e}")
                continue
            checked += 1
            n_here += 1
        per_prog[name] = n_here

    dut._log.info(
        f"mutants checked in lockstep: {checked} "
        f"({', '.join(f'{k}={v}' for k, v in per_prog.items())})")
    dut._log.info(f"  skipped, not encodable at 32 bits: {skipped_encode}")
    dut._log.info(f"  skipped, model raised:             {skipped_model}")
    dut._log.info(f"  RTL/model divergences:             {len(diverged)}")
    hit, capn = cov.summary()
    dut._log.info(f"  executed code coverage under mutation: {hit}/{capn} = "
                  f"{100.0*hit/capn:.1f}%  missing={cov.missing() or 'none'}")

    assert checked > 0, "no mutants were actually checked"
    if diverged:
        raise AssertionError(
            f"{len(diverged)} mutant(s) made the RTL and the model disagree.\n"
            + "\n".join(diverged[:5]))
