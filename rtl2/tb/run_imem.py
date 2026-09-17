"""Run the directed imem load-path test. Exit non-zero on failure."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.abspath(os.path.join(HERE, ".."))
BENCH = os.path.abspath(os.path.join(RTL, "..", "isa_bench"))

from cocotb_tools.runner import get_runner
from run_tests import TIMESCALE, failures, sources_and_top


def main():
    srcs, top = sources_and_top()
    runner = get_runner("icarus")
    runner.build(
        verilog_sources=srcs, includes=[RTL], hdl_toplevel=top,
        build_dir=os.path.join(RTL, "sim_build"),
        build_args=["-g2012", "-Wall", "-gno-specify"],
        timescale=TIMESCALE, always=True,
    )
    xml = runner.test(
        hdl_toplevel=top, test_module="test_imem", test_dir=HERE,
        build_dir=os.path.join(RTL, "sim_build"), timescale=TIMESCALE,
        extra_env={"PYTHONPATH": HERE + os.pathsep + BENCH},
        results_xml="results_imem.xml",
    )
    bad = failures(xml)
    if bad:
        for name, msg in bad:
            print(f"  FAIL ({name}): {msg}")
        return 1
    print("OK: imem load path writes and reads back every row")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
