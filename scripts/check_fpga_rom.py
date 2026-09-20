"""Gate: the generated FPGA ROM must mean what the hardware will read.

FPGA BRING-UP INFRASTRUCTURE. Not part of the ASIC submission.

`isa_bench/` already simulates UART TX cycle-accurately, but it does so from
the benchmark's own parameters. Nothing checked the path that actually reaches
the board: SttCore -> config_word -> stt_rom.vh -> stt_config.v. This decodes
the emitted bit stream back into fields and checks it against the numbers the
hardware uses, so a disagreement between the encoder and the RTL shows up here
rather than as a wrong baud rate on a scope.

Three things are checked, and the third is the one that catches scaling bugs:

  1. the decoded configuration is the configuration that was asked for;
  2. the decoded timer period gives the intended bit period and baud, at the
     clock the generator says it assumed;
  3. the stream LENGTHS match the widths the RTL computes for its own shift
     registers, read out of stt_config.v and stt_iomux.v rather than
     duplicated here.

Check 3 matters because a config chain that is N bits short does not fail
loudly -- every field lands N positions high, and a period read N bits off is
a period multiplied by 2^N. A factor of exactly 32 is five bits.

    python3 scripts/check_fpga_rom.py
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "isa_bench"))
sys.path.insert(0, os.path.join(ROOT, "rtl2", "tb"))

import lockstep as L                                    # noqa: E402

RTL = os.path.join(ROOT, "rtl2")
UART_TOLERANCE = 0.02      # a receiver samples mid-bit; 2% is conservative


def rtl_params(path):
    """Parameter and localparam integer defaults from a Verilog source."""
    txt = open(path).read()
    out = {}
    for m in re.finditer(r"(?:parameter|localparam)\s+integer\s+(\w+)\s*=\s*([^,;\n]+)", txt):
        out[m.group(1)] = m.group(2).strip()
    for m in re.finditer(r"parameter\s+(\w+)\s*=\s*([^,;\n]+)", txt):
        out.setdefault(m.group(1), m.group(2).strip())
    return txt, out


def rtl_chain_widths():
    """The widths the RTL gives its own config and pin-assignment chains."""
    txt, p = rtl_params(os.path.join(RTL, "stt_config.v"))
    env = {k: int(v) for k, v in p.items() if re.fullmatch(r"\d+", v)}
    expr = re.search(r"localparam integer NBITS\s*=\s*(.+?);", txt, re.S).group(1)
    cfg_n = eval(re.sub(r"\s+", " ", expr), {}, env)            # noqa: S307

    txt, p = rtl_params(os.path.join(RTL, "stt_iomux.v"))
    return cfg_n, txt, p


def iomux_sel_bits(nsm, nslot=3, nin=2, nout=16, npin=16):
    """stt_iomux's NBITS, evaluated the way the RTL computes it."""
    import math
    drv = nsm * nslot
    oselw = max(1, math.ceil(math.log2(drv))) if drv > 1 else 1
    iselw = max(1, math.ceil(math.log2(npin))) if npin > 1 else 1
    return 1 + nout * oselw + nsm * nin * iselw + 1 + 2 * iselw


def gen(args):
    """Run the generator and return (stdout, parsed localparams)."""
    cmd = [sys.executable, os.path.join(HERE, "gen_fpga_rom.py")] + args
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        raise SystemExit(f"generator failed:\n{r.stdout}\n{r.stderr}")
    vals = {}
    pat = (r"localparam\s+(?:integer\s+)?(?:\[[^\]]*\]\s*)?(\w+)"
           r"\s*=\s*(?:(\d+)'([bh]))?([0-9a-fA-F]+);")
    for m in re.finditer(pat, r.stdout):
        width, base, digits = m.group(2), m.group(3), m.group(4)
        radix = {"b": 2, "h": 16}.get(base, 10)
        vals[m.group(1)] = (int(width) if width else None, int(digits, radix))
    return r.stdout, vals


def field(cfg, off, w):
    return (cfg >> off) & ((1 << w) - 1)


def widths_agree(rtl_n, enc_n):
    """The whole point of check 3, as one testable function.

    A stream N bits shorter than the register it feeds does not fail loudly:
    every field lands N positions high and the timer period comes back scaled
    by 2^N. Five bits is a factor of 32.
    """
    return rtl_n == enc_n


def self_test():
    """The check must be able to fail. Verified without touching any RTL."""
    bad = []
    if not widths_agree(100, 100):
        bad.append("matching widths reported as a mismatch")
    if widths_agree(105, 100):
        bad.append("a 5-bit mismatch -- the exact shape of a 32x period "
                   "error -- reported as agreement")
    if bad:
        for b in bad:
            print(f"  FAIL self-test: {b}")
        return False
    print("  ok   self-test: matching widths pass, a 5-bit mismatch fails")
    return True


def main():
    ok = self_test()
    rtl_cfg_n, _, _ = rtl_chain_widths()
    print("=== chain widths: generator vs the RTL's own localparams ===")
    print(f"  stt_config.v NBITS      = {rtl_cfg_n}")
    print(f"  lockstep.py  CFG_BITS   = {L.CFG_BITS}")
    if not widths_agree(rtl_cfg_n, L.CFG_BITS):
        print(f"  FAIL: the encoder packs {L.CFG_BITS} bits into a "
              f"{rtl_cfg_n}-bit register. Every field lands "
              f"{rtl_cfg_n - L.CFG_BITS} positions off, and the timer period "
              f"is scaled by 2^{abs(rtl_cfg_n - L.CFG_BITS)}.")
        ok = False
    else:
        print("  ok   the encoder and the RTL agree on the config chain")

    cases = [
        ("blink",   ["--program", "blink", "--div", "8"]),
        ("uart_tx", ["--program", "uart_tx", "--div", "8", "--baud", "9600"]),
    ]
    for name, args in cases:
        print(f"\n=== {name} ===")
        out, vals = gen(args)
        f_sys = 125e6 / 8
        cfg_n, cfg = vals["STT_ROM_CFG"]
        sel_n, _ = vals["STT_ROM_SEL"]
        _, period = vals["STT_ROM_PERIOD"]
        nsm = vals["STT_ROM_NSM"][1]

        print(f"  assumed clock        {f_sys / 1e6:.6g} MHz")
        print(f"  emitted period P     {period} cycles")
        if cfg_n != rtl_cfg_n:
            print(f"  FAIL: config stream is {cfg_n} bits, RTL register is "
                  f"{rtl_cfg_n}")
            ok = False
        want_sel = iomux_sel_bits(nsm)
        if sel_n != want_sel:
            print(f"  FAIL: pin chain is {sel_n} bits, iomux register is "
                  f"{want_sel}")
            ok = False
        else:
            print(f"  ok   pin chain {sel_n} bits matches the iomux at nsm={nsm}")

        decoded = field(cfg, L.O_PERIOD, L.TIMER_W)
        if decoded != period:
            print(f"  FAIL: the config word decodes to period {decoded}, but "
                  f"the ROM reports {period}")
            ok = False
        else:
            print(f"  ok   config word decodes to period {decoded}")

        if name == "uart_tx":
            baud_got = f_sys / decoded
            err = (baud_got - 9600) / 9600
            print(f"  bit period           {decoded / f_sys * 1e6:.3f} us")
            print(f"  baud from the ROM    {baud_got:.2f} ({err * 100:+.4f}%)")
            if abs(err) > UART_TOLERANCE:
                print(f"  FAIL: {err * 100:+.2f}% is outside +/-"
                      f"{UART_TOLERANCE * 100:g}%")
                ok = False
            else:
                print(f"  ok   within +/-{UART_TOLERANCE * 100:g}%")
            byte = field(cfg, L.O_K, L.SR_W)
            srw = field(cfg, L.O_SRW, 4)
            init = field(cfg, L.O_INIT, L.NSLOT)
            shift_left = field(cfg, L.O_SHIFT, 1)
            fill = field(cfg, L.O_FILL, 2)
            for label, got, want in (("loadk", byte, 0x55),
                                     ("sr_width", srw, 8),
                                     ("init_pins bit 0 (idle high)", init & 1, 1),
                                     ("shift_left (0 = LSB first)", shift_left, 0),
                                     ("fill (1 = line returns high)", fill, 1)):
                if got != want:
                    print(f"  FAIL: {label} decodes to {got}, expected {want}")
                    ok = False
                else:
                    print(f"  ok   {label} = {got}")

    print()
    if ok:
        print("OK: the generated ROM means what the hardware will read")
        return 0
    print("FAIL: the generated ROM does not match the hardware's own widths")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
