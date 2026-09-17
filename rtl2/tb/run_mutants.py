"""Run the mutation suite against rtl2. Exit non-zero on any RTL/model divergence.

Usage: run_mutants.py [program,program,...]
Environment: MUT_CYCLES (per-mutant cycle cap), MUT_LIMIT (stop after N).
"""
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.abspath(os.path.join(HERE, ".."))
BENCH = os.path.abspath(os.path.join(RTL, "..", "isa_bench"))

from cocotb_tools.runner import get_runner
from run_tests import SOURCES, TIMESCALE, failures


def main():
    progs = sys.argv[1] if len(sys.argv) > 1 else "uart_tx,uart_rx,spi,i2c,usb,jtag"
    runner = get_runner("icarus")
    runner.build(
        verilog_sources=[os.path.join(RTL, s) for s in SOURCES],
        includes=[RTL],
        hdl_toplevel="stt_top",
        build_dir=os.path.join(RTL, "sim_build"),
        build_args=["-g2012", "-Wall"],
        timescale=TIMESCALE,
        always=True,
    )
    xml = runner.test(
        hdl_toplevel="stt_top",
        test_module="test_mutants",
        test_dir=HERE,
        build_dir=os.path.join(RTL, "sim_build"),
        timescale=TIMESCALE,
        extra_env={"MUT_PROGS": progs, "BIT_PERIOD": "32",
                   "MUT_CYCLES": os.environ.get("MUT_CYCLES", "1200"),
                   "MUT_LIMIT": os.environ.get("MUT_LIMIT", "0"),
                   "PYTHONPATH": HERE + os.pathsep + BENCH},
        results_xml="results_mutants.xml",
    )
    bad = failures(xml)
    if bad:
        for name, msg in bad:
            print(f"  FAIL ({name}): {msg}")
        print("FAIL: the RTL and the models disagree on at least one mutant")
        return 1
    print("OK: every encodable mutant runs in lockstep; RTL and models agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
