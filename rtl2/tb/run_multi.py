"""Run the multi-machine lockstep test. Exit non-zero on any divergence."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.abspath(os.path.join(HERE, ".."))
BENCH = os.path.abspath(os.path.join(RTL, "..", "isa_bench"))

os.environ["MULTI"] = "1"

from cocotb_tools.runner import get_runner
from run_tests import TIMESCALE, failures, sources_and_top


def main():
    srcs, top = sources_and_top()
    runner = get_runner("icarus")
    runner.build(
        verilog_sources=srcs, includes=[RTL], hdl_toplevel=top,
        build_dir=os.path.join(RTL, "sim_build_multi"),
        build_args=(["-g2012", "-Wall", "-gno-specify"]
                    + (["-DIMEM_MACRO"] if os.environ.get("IMEM") == "cfgmem" else [])),
        timescale=TIMESCALE, always=True,
    )
    xml = runner.test(
        hdl_toplevel=top, test_module="test_multi", test_dir=HERE,
        build_dir=os.path.join(RTL, "sim_build_multi"), timescale=TIMESCALE,
        extra_env={"MULTI_PROGS": os.environ.get("MULTI_PROGS",
                                                 "uart_tx,uart_rx,spi,i2c,jtag"),
                   "MULTI_CYCLES": os.environ.get("MULTI_CYCLES", "2500"),
                   "BIT_PERIOD": "32",
                   "PYTHONPATH": HERE + os.pathsep + BENCH},
        results_xml="results_multi.xml",
    )
    bad = failures(xml)
    if bad:
        for name, msg in bad:
            print(f"  FAIL ({name}): {msg}")
        return 1
    print("OK: every machine runs its own program in lockstep with its own model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
