"""Mutation run over the UART detector -- EXPERIMENT, not conformance.

Same generator the reference programs use. A mutant SURVIVES if the detector
still gets all seven cases right; anything else is a kill. A detector whose
mutants all survive would be one whose rows do not matter.
"""
import io
import contextlib
import sys

sys.path.insert(0, ".")
with contextlib.redirect_stdout(io.StringIO()):
    import detector
    from mutate import mutants

core, prog = detector.stt_uart_detect(32)
base_ok = detector.check_all()
print(f"baseline: {'all 7 cases correct' if base_ok else 'BASELINE BROKEN'}")
assert base_ok, "the unmutated detector must pass before mutating it"

killed = survived = skipped = 0
survivors = []
for kind, desc, m in mutants(prog):
    try:
        ok = detector.check_all(prog_override=m)
    except Exception:
        killed += 1
        continue
    if ok:
        survived += 1
        survivors.append(f"{kind}: {desc}")
    else:
        killed += 1

total = killed + survived
print(f"mutants: {total}   killed: {killed}   survived: {survived}")
print(f"kill rate: {100.0 * killed / total:.1f}%")
if survivors:
    print("\nsurvivors (behaviour the seven cases do not pin down):")
    for s in survivors[:12]:
        print(f"  {s}")
    if len(survivors) > 12:
        print(f"  ... and {len(survivors) - 12} more")
