"""Gap 2: `next` from the last row.

rtl/stt_decode.v:73   nxt_seq = (cur == ROWS-1) ? 0 : cur+1     -> wraps at the
                      END OF IMEM (row 31), and needs no program-length register.
isa_bench/rowenc.py:182  nxt = names[i+1] if i+1 < len(names) else names[0]
                      -> wraps at the END OF THE PROGRAM.

They agree only if a program fills the imem, or never takes `next` from its own
last row.  Measure which benchmarks take `next` from their last row.
"""
import io, contextlib
_b = io.StringIO()
with contextlib.redirect_stdout(_b):
    import rowenc
    from gensweep import BENCH, SRC
    from rowformat import Format
    import jtag_prog, stt

MODE_USES_NEXT = {0: False, 1: True, 2: True, 3: True}   # WAIT / BRANCH / SKIP / STEP
NAME = {0: "WAIT", 1: "BRANCH", 2: "SKIP", 3: "STEP"}

progs = {b: SRC[b](32)[1] for b in BENCH}
progs["jtag"] = jtag_prog.stt_jtag(32)[1]

print(f"  {'bench':9} {'rows':>5} {'last row':10} {'mode':7} {'takes next?':>12}  divergence")
bad = 0
for name, prog in progs.items():
    lay = rowenc.best_order(prog.rows)
    last = lay[-1]
    uses = MODE_USES_NEXT[last["mode"]]
    n = len(lay)
    div = "none (program fills imem)" if n == 32 else ("MODEL WRAPS AT %d, RTL AT 32" % n if uses else "unexercised")
    if uses and n != 32:
        bad += 1
    print(f"  {name:9} {n:>5} {last['row'].name:10} {NAME[last['mode']]:7} "
          f"{('yes' if uses else 'no'):>12}  {div}")
print(f"\n  benchmarks where model and RTL would diverge: {bad}")
raise SystemExit(1 if bad else 0)
