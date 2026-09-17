"""Run the chip-boundary test: pin assignment, run flag, five machines."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.abspath(os.path.join(HERE, ".."))
BENCH = os.path.abspath(os.path.join(RTL, "..", "isa_bench"))

os.environ["CHIP"] = "1"

from cocotb_tools.runner import get_runner
from run_tests import TIMESCALE, failures, sources_and_top


def main():
    srcs, top = sources_and_top()
    runner = get_runner("icarus")
    runner.build(
        verilog_sources=srcs, includes=[RTL], hdl_toplevel=top,
        build_dir=os.path.join(RTL, "sim_build_chip"),
        build_args=(["-g2012", "-Wall", "-gno-specify"]
                    + (["-DIMEM_MACRO"] if os.environ.get("IMEM") == "cfgmem" else [])),
        timescale=TIMESCALE, always=True,
    )
    xml = runner.test(
        hdl_toplevel=top, test_module="test_chip", test_dir=HERE,
        build_dir=os.path.join(RTL, "sim_build_chip"), timescale=TIMESCALE,
        extra_env={"CHIP_PROGS": os.environ.get("CHIP_PROGS",
                                                 "uart_tx,uart_rx,spi,i2c,jtag"),
                   "CHIP_CYCLES": os.environ.get("CHIP_CYCLES", "2000"),
                   "BIT_PERIOD": "32",
                   "PYTHONPATH": HERE + os.pathsep + BENCH},
        results_xml="results_chip.xml",
    )
    bad = failures(xml)
    if bad:
        for name, msg in bad:
            print(f"  FAIL ({name}): {msg}")
        return 1
    print("OK: every machine reaches its assigned pins through the iomux")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
