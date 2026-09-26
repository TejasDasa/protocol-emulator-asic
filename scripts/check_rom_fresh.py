"""Gate: the tracked rtl2/stt_rom.vh must be what the generator produces now.

FPGA BRING-UP INFRASTRUCTURE. Not part of the ASIC submission.

stt_rom.vh is generated but tracked, and every testbench regenerates it before
running. That combination hides a specific failure: hand-written RTL can start
referencing a localparam the generator has only just learned to emit, every
test still passes because every test regenerates, and the file the repository
actually carries is stale. A Vivado build -- which does not run the generator
-- then fails on an undeclared identifier that no simulation ever saw.

That is not hypothetical. stt_fpga_top.v gained references to
STT_ROM_HOST_RELAY and STT_ROM_UART_P while the committed stt_rom.vh predated
both.

scripts/check_fpga_rom.py does not cover this: it runs the generator fresh and
decodes its output, so it never reads the tracked file at all.

This gate reads the "Reproduce with:" line out of the tracked header, re-runs
exactly that command into a temporary file, and requires the result to be
byte-identical.

    python3 scripts/check_rom_fresh.py
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROM = os.path.join(ROOT, "rtl2", "stt_rom.vh")


def main():
    if not os.path.exists(ROM):
        print("FAIL: rtl2/stt_rom.vh is missing")
        return 1
    with open(ROM) as f:
        text = f.read()

    m = re.search(r"^//\s+(python3 scripts/gen_fpga_rom\.py .*)$", text, re.M)
    if not m:
        print("FAIL: rtl2/stt_rom.vh carries no 'Reproduce with:' command.")
        print("      Regenerate it with a generator that emits one.")
        return 1
    cmd = m.group(1).split()

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "stt_rom.vh")
        # Replace the -o target so the tracked file is never touched.
        run = [sys.executable if c == "python3" else c for c in cmd]
        tracked_out = run[run.index("-o") + 1]
        run[run.index("-o") + 1] = out
        r = subprocess.run(run, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print("FAIL: the reproduce command did not run:")
            print("     ", " ".join(cmd))
            print(r.stderr.strip()[:800])
            return 1
        with open(out) as f:
            fresh = f.read()

    # The header echoes its own -o argument, and this gate redirects that to a
    # temporary file so the tracked one is never touched. Put the tracked path
    # back before comparing, or every run reports a difference it caused.
    fresh = fresh.replace(out, tracked_out)

    if fresh == text:
        prog = re.search(r"--program\s+(\S+)", " ".join(cmd))
        print("OK: rtl2/stt_rom.vh matches the generator "
              f"({prog.group(1) if prog else '?'}, byte-identical)")
        return 0

    print("FAIL: rtl2/stt_rom.vh is stale -- the generator produces something")
    print("      else. Regenerate and commit it:")
    print("     ", " ".join(cmd))
    tl, fl = text.splitlines(), fresh.splitlines()
    shown = 0
    for i in range(max(len(tl), len(fl))):
        a = tl[i] if i < len(tl) else "<absent>"
        b = fl[i] if i < len(fl) else "<absent>"
        if a != b:
            print(f"      line {i + 1}:")
            print(f"        tracked: {a[:96]}")
            print(f"        fresh:   {b[:96]}")
            shown += 1
            if shown == 6:
                print("      ...")
                break
    return 1


if __name__ == "__main__":
    sys.exit(main())
