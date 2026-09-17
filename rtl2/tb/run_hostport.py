"""SPEC section 11.2 host byte port, at the tt_um_stt boundary."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["TTOP"] = "1"

from cocotb_tools.runner import get_runner
from run_tests import RTL, BENCH, TIMESCALE, sources_and_top, failures


def main():
    srcs, top = sources_and_top()
    runner = get_runner("icarus")
    runner.build(verilog_sources=srcs, includes=[RTL], hdl_toplevel=top,
                 build_dir=os.path.join(RTL, "sim_build_hp"),
                 build_args=["-g2012", "-Wall", "-gno-specify"],
                 timescale=TIMESCALE, always=True)
    xml = runner.test(hdl_toplevel=top, test_module="test_hostport",
                      test_dir=HERE, build_dir=os.path.join(RTL, "sim_build_hp"),
                      timescale=TIMESCALE,
                      extra_env={"PYTHONPATH": HERE + os.pathsep + BENCH},
                      results_xml="results_hostport.xml")
    bad = failures(xml)
    if bad:
        for name, msg in bad:
            print(f"  FAIL ({name}): {msg}")
        return 1
    print("OK: the host byte port moves bytes through the real Tiny Tapeout pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
