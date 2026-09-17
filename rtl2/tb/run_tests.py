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

PROGRAMS = ["uart_tx", "uart_rx", "spi", "i2c", "usb", "jtag"]
SOURCES = ["stt_config.v", "stt_imem.v", "stt_core.v", "stt_top.v"]
TIMESCALE = ("1ns", "1ps")


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
    bad = []
    for p in want:
        print(f"\n=== lockstep: {p} " + "=" * (56 - len(p)))
        xml = runner.test(
            hdl_toplevel="stt_top",
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
