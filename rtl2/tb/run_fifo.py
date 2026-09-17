"""Run the directed hostbuf test. Exit non-zero on failure."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.abspath(os.path.join(HERE, ".."))

from cocotb_tools.runner import get_runner
from run_tests import TIMESCALE, failures


def main():
    runner = get_runner("icarus")
    runner.build(
        verilog_sources=[os.path.join(RTL, s)
                         for s in ("stt_fifo.v", "stt_hostbuf.v")],
        includes=[RTL], hdl_toplevel="stt_hostbuf",
        build_dir=os.path.join(RTL, "sim_build_fifo"),
        build_args=["-g2012", "-Wall"], timescale=TIMESCALE, always=True,
    )
    xml = runner.test(
        hdl_toplevel="stt_hostbuf", test_module="test_fifo", test_dir=HERE,
        build_dir=os.path.join(RTL, "sim_build_fifo"), timescale=TIMESCALE,
        extra_env={"PYTHONPATH": HERE},
        results_xml="results_fifo.xml",
    )
    bad = failures(xml)
    if bad:
        for name, msg in bad:
            print(f"  FAIL ({name}): {msg}")
        return 1
    print("OK: hostbuf depth, overflow, underflow and sticky flags all correct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
