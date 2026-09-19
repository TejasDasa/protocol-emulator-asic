"""Make an OpenSTA-written SDF usable by Icarus Verilog, and scale it.

Three incompatibilities, each found by bisecting against the real file. All
three are silent: two abort annotation, and the third produces a simulation
that runs happily with the wrong numbers.

1. `(INSTANCE)` with no argument. OpenSTA emits one such CELL holding every
   top-level INTERCONNECT -- port to first cell, last cell to port. Icarus
   aborts on it with "NULL handle passed to vpi_scan", and `(INSTANCE *)`
   does not help. It is removed, which is sound for output-pin measurements
   and NOT sound in general:

       every output-side entry in that block is 0.0000 ns (verified: 24 of
       24, both corners), because the output buffer drives the pad directly.
       What is lost is the clk-port-to-clock-buffer hop and the input-pin
       hops, which are common-mode for output-to-output skew.

   If you use this for input timing, put those back by hand.

2. `(VOLTAGE 1.080::1.080)` and the PROCESS/TEMPERATURE lines carry a triple
   with an empty typical value. Icarus reports "Chosen value not defined" and
   then gives up with "too many errors". They are informational; dropped.

3. **Icarus rounds annotated delays to the cell module's TIME UNIT, not its
   precision.** The PDK cells are `1ns/10ps`, so the unit is 1 ns and every
   sub-nanosecond delay is destroyed: measured, 0.250 ns annotates as 0,
   0.830 ns as 1 ns, 2.500 ns as 3 ns. A design whose skew is tens of
   picoseconds simulates as though it had none. Giving the cells a finer
   timescale does not fix it -- annotation then applies nothing at all.

   The workaround is to simulate in a SCALED TIME DOMAIN: multiply every
   delay by `--scale` (default 1000) so the values are integers in the 1 ns
   unit, and scale the testbench clock by the same factor. Uniform scaling
   preserves every timing relationship exactly, and measured intervals are
   divided by the same factor to recover real time. Verified exact at 0.017,
   0.250, 0.830 and 2.500 ns.

Usage:
    prep_sdf.py <in.sdf> <out.sdf> [--scale 1000] [--keep-top]
"""
import re
import sys


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = [a for a in sys.argv[1:] if a.startswith("--")]
    src, dst = args[0], args[1]
    scale = 1000
    for o in opts:
        if o.startswith("--scale"):
            scale = int(o.split("=")[1]) if "=" in o else 1000
    keep_top = "--keep-top" in opts

    t = open(src, errors="replace").read()

    # (2) informational header triples Icarus rejects
    t = "".join(l for l in t.splitlines(keepends=True)
                if not re.match(r"\s*\((VOLTAGE|PROCESS|TEMPERATURE)\b", l))

    # (1) split out the empty-INSTANCE cell by paren matching, never by string
    # splitting -- a broken DELAYFILE annotates nothing and says almost nothing
    m = re.search(r"^[ \t]*\(CELL\b", t, re.M)
    head, body = t[:m.start()], t[m.start():]
    cells, i = [], 0
    while True:
        j = body.find("(CELL", i)
        if j < 0:
            break
        d, k = 0, j
        while k < len(body):
            if body[k] == "(":
                d += 1
            elif body[k] == ")":
                d -= 1
                if d == 0:
                    k += 1
                    break
            k += 1
        cells.append(body[j:k])
        i = k
    is_top = lambda c: re.search(r"\(INSTANCE\s*(\*)?\s*\)", c) is not None
    top = [c for c in cells if is_top(c)]
    keep = cells if keep_top else [c for c in cells if not is_top(c)]

    out = head + "\n".join(keep) + "\n)\n"

    # (3) scale every delay triple
    n_scaled = [0]

    def rescale(mo):
        n_scaled[0] += 1
        vals = [f"{float(v) * scale:.6g}" for v in mo.group(1).split(":")]
        return "(" + ":".join(vals) + ")"

    out = re.sub(r"\(([\d.]+(?::[\d.]*)+)\)", rescale, out)

    open(dst, "w").write(out)
    print(f"  cells: {len(cells)} parsed, {len(keep)} kept, {len(top)} top dropped")
    print(f"  delay triples scaled by {scale}: {n_scaled[0]}")


if __name__ == "__main__":
    main()
