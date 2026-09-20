"""Run the inter-pin skew measurement on the signed-off gate netlist.

Needs the SDF prepared by rtl2/sdf/prep_sdf.py -- see that file for the three
Icarus incompatibilities it works around, one of which silently reports zero
skew for every pair.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(RTL, ".."))
BENCH = os.path.join(ROOT, "isa_bench")
RUN = os.environ.get(
    "PNR_RUN", os.path.join(ROOT, "floorplan", "runs", "RUN_2026-09-18_00-21-34"))
PDK = os.environ.get(
    "PDK_VERILOG",
    "/home/tejas/pdk/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog")
WORK = os.environ.get("SDF_WORK", "/home/tejas/sdf_work")

from cocotb_tools.runner import get_runner
from run_tests import failures

CORNERS = {"slow": "nom_slow_1p08V_125C", "typ": "nom_typ_1p20V_25C"}
PROGRAMS = ["spi", "i2c", "jtag", "usb"]


def prepared_sdf(corner):
    src = os.path.join(RUN, "final", "sdf", CORNERS[corner],
                       f"tt_um_stt__{CORNERS[corner]}.sdf")
    dst = os.path.join(WORK, f"skew_{corner}.sdf")
    if not os.path.exists(src):
        sys.exit(f"SDF not found: {src}")
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        os.makedirs(WORK, exist_ok=True)
        subprocess.check_call(
            [sys.executable, os.path.join(RTL, "sdf", "prep_sdf.py"),
             src, dst, "--scale=1000"])
    return dst


def main():
    corners = sys.argv[1:] or ["slow", "typ"]
    nl = os.path.join(RUN, "final", "nl", "tt_um_stt.nl.v")
    if not os.path.exists(nl):
        sys.exit(f"gate netlist not found: {nl}")
    bad = []
    for corner in corners:
        sdf = prepared_sdf(corner)
        runner = get_runner("icarus")
        runner.build(
            verilog_sources=[nl,
                             os.environ.get("MACRO_NL", os.path.join(ROOT, "floorplan", "macro", "CFGMEM_IHP16.nl.v")),
                             os.path.join(RTL, "sdf", "tt_um_stt_sdf.v"),
                             os.path.join(PDK, "sg13cmos5l_stdcell.v"),
                             os.path.join(PDK, "sg13cmos5l_udp.v")],
            hdl_toplevel="tt_um_stt_sdf",
            build_dir=os.path.join(RTL, "sim_build_skew"),
            # -gspecify: without it there are no paths to annotate.
            # -ginterconnect: without it Icarus rejects every INTERCONNECT.
            build_args=["-g2012", "-gspecify", "-ginterconnect",
                        f"-DSDF_FILE=\"{sdf}\"", "-DUSE_SDF"],
            timescale=("1ns", "1ps"), always=True,
        )
        for prog in PROGRAMS:
            print(f"\n=== {prog} @ {corner} " + "=" * 40)
            xml = runner.test(
                hdl_toplevel="tt_um_stt_sdf", test_module="test_skew",
                test_dir=HERE, build_dir=os.path.join(RTL, "sim_build_skew"),
                timescale=("1ns", "1ps"),
                extra_env={"PROG": prog, "CORNER": corner, "SDF_FILE": sdf,
                           "PYTHONPATH": HERE + os.pathsep + BENCH},
                results_xml=f"results_skew_{prog}_{corner}.xml",
            )
            for nm, msg in failures(xml):
                bad.append((prog, corner, nm, msg))
    if bad:
        for p, c, nm, msg in bad:
            print(f"  FAIL {p}@{c} ({nm}): {msg}")
        return 1
    print("\nOK: inter-pin skew measured on the gate netlist at every corner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
