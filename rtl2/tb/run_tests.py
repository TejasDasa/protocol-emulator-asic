"""Run the lockstep test for every reference program. Exit non-zero on any failure.

cocotb 2.x's runner.test() does NOT raise when a test fails -- it returns the
path to a JUnit XML file. A gate that cannot fail is not a gate, so the XML is
parsed here and any <failure> or <error> element fails the build. Verified in
both directions: see rtl2/README.md.

Usage: run_tests.py [program ...]
"""
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.abspath(os.path.join(HERE, ".."))
BENCH = os.path.abspath(os.path.join(RTL, "..", "isa_bench"))

from cocotb_tools.runner import get_runner

# The conformance six, plus CAN. CAN is not in the frozen encoding set -- it
# is here because it is the only program that exercises the SPEC section 9
# wider units as a protocol rather than as codes.
PROGRAMS = ["uart_tx", "uart_rx", "spi", "i2c", "usb", "jtag", "can_tx"]
TIMESCALE = ("1ns", "1ps")

# IMEM=cfgmem swaps the behavioural array for two CFGMEM_IHP16 macros, using the
# REAL DFFRAM netlist and the PDK's own cell models rather than a hand-written
# stand-in -- a stand-in would only prove the stand-in matches the RTL. The
# suites are identical either way, which is the point: the swap must change
# nothing observable.
MACRO_NL = os.environ.get(
    "MACRO_NL",
    os.path.abspath(os.path.join(RTL, "..", "floorplan", "macro",
                                 "CFGMEM_IHP16.nl.v")))
PDK_V = os.environ.get(
    "PDK_V", "/home/tejas/pdk/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog")


def sources_and_top():
    """(verilog sources, toplevel) for the selected configuration.

    MULTI=1 builds the NSM-machine array; IMEM=cfgmem puts each machine's
    instruction memory in CFGMEM_IHP16 macros.
    """
    multi = os.environ.get("MULTI", "0") == "1"
    chip  = os.environ.get("CHIP", "0") == "1"
    ttop  = os.environ.get("TTOP", "0") == "1"
    if os.environ.get("IMEM", "behavioural") == "cfgmem":
        base = ("cfgmem_ihp16_model.v", "stt_config.v", "stt_imem_cfgmem.v",
                "stt_core.v", "stt_top_cfgmem.v")
        top = "stt_top_cfgmem"
    else:
        base = ("stt_config.v", "stt_imem.v", "stt_core.v", "stt_top.v")
        top = "stt_top"
    if chip or ttop:
        base = base + ("stt_array.v", "stt_iomux.v", "stt_fifo.v",
                       "stt_hostbuf.v", "stt_hostport.v", "stt_chip.v")
        top = "stt_chip"
    if ttop:
        # The real submission boundary: only ui_in/uo_out/uio reach the top.
        base = base + ("tt_um_stt.v",)
        top = "tt_um_stt"
    elif multi:
        base = base + ("stt_array.v",)
        top = "stt_array"
    return ([os.path.join(RTL, s) for s in base], top)


# kept for callers that only need the plain list
SOURCES = ["stt_config.v", "stt_imem.v", "stt_core.v", "stt_top.v"]


def failures(xml_path):
    """[(testname, message)] for every failed or errored case in a JUnit XML."""
    out = []
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as e:
        return [("<results>", f"could not read {xml_path}: {e}")]
    cases = root.iter("testcase")
    n = 0
    for case in cases:
        n += 1
        for bad in list(case.findall("failure")) + list(case.findall("error")):
            msg = (bad.get("message") or bad.text or "").strip().splitlines()
            out.append((case.get("name", "?"), msg[0] if msg else "failed"))
    if n == 0:
        out.append(("<results>", f"no testcases recorded in {xml_path}"))
    return out


def main():
    want = sys.argv[1:] or PROGRAMS
    srcs, top = sources_and_top()
    runner = get_runner("icarus")
    runner.build(
        verilog_sources=srcs, includes=[RTL], hdl_toplevel=top,
        build_dir=os.path.join(RTL, "sim_build"),
        build_args=["-g2012", "-Wall", "-gno-specify"],
        timescale=TIMESCALE, always=True,
    )
    bad = []
    for p in want:
        print(f"\n=== lockstep: {p} " + "=" * (56 - len(p)))
        xml = runner.test(
            hdl_toplevel=top,
            test_module="test_lockstep",
            test_dir=HERE,
            build_dir=os.path.join(RTL, "sim_build"),
            timescale=TIMESCALE,
            extra_env={"PROG": p, "BIT_PERIOD": "32",
                       "PYTHONPATH": HERE + os.pathsep + BENCH},
            results_xml=f"results_{p}.xml",
        )
        for name, msg in failures(xml):
            bad.append((p, name, msg))

    print("\n" + "=" * 70)
    if bad:
        for p, name, msg in bad:
            print(f"  FAIL {p} ({name}): {msg}")
        print(f"FAIL: {len(bad)} failure(s) across {len(want)} reference program(s)")
        return 1
    print(f"OK: all {len(want)} reference programs run in cycle-exact lockstep "
          f"with the models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
