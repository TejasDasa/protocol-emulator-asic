"""Check that the instruction memory holds what was shifted into it.

Runs at the TT boundary with the CFGMEM macros, because the busy handshake
that the load path has to honour only exists in the macro configuration.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.abspath(os.path.join(HERE, ".."))
BENCH = os.path.abspath(os.path.join(RTL, "..", "isa_bench"))

from cocotb_tools.runner import get_runner
from run_tests import failures

SRCS = ["cfgmem_ihp16_model.v", "stt_config.v", "stt_imem_cfgmem.v",
        "stt_core.v", "stt_top_cfgmem.v", "stt_array.v", "stt_iomux.v",
        "stt_fifo.v", "stt_hostbuf.v", "stt_hostport.v", "stt_chip.v",
        "tt_um_stt.v"]


def main():
    progs = os.environ.get("IMEMLOAD_PROGS", "spi,i2c,jtag,usb,uart_tx").split(",")
    runner = get_runner("icarus")
    runner.build(
        verilog_sources=[os.path.join(RTL, f) for f in SRCS],
        includes=[RTL], hdl_toplevel="tt_um_stt",
        build_dir=os.path.join(RTL, "sim_build_imemload"),
        build_args=["-g2012", "-gno-specify", "-DIMEM_MACRO"],
        timescale=("1ns", "1ps"), always=True,
    )
    bad = []
    for prog in progs:
        xml = runner.test(
            hdl_toplevel="tt_um_stt", test_module="test_imemload", test_dir=HERE,
            build_dir=os.path.join(RTL, "sim_build_imemload"),
            timescale=("1ns", "1ps"),
            extra_env={"PROG": prog.strip(),
                       "PYTHONPATH": HERE + os.pathsep + BENCH},
            results_xml=f"results_imemload_{prog.strip()}.xml",
        )
        bad += [(prog, nm, msg) for nm, msg in failures(xml)]
    if bad:
        for p, nm, msg in bad:
            print(f"  FAIL {p} ({nm}): {msg}")
        return 1
    print(f"OK: instruction memory loads intact for {len(progs)} programs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
