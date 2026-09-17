import io, contextlib, sys
sys.path.insert(0, ".")
with contextlib.redirect_stdout(io.StringIO()):
    import detector
    from rowformat import Format

core, prog = detector.stt_uart_detect(32)
res = Format("single5", "grouped", tgt_bits=8).encode(prog)
print(f"encoded rows: {res['rows']} of 32   ({32 - res['rows']} remain)\n")

CASES = [("uart", "real UART traffic", True),
         ("uart_skew", "real UART, baud ~3% off the hypothesis", True),
         ("uart_badstop", "UART-shaped, every stop bit wrong", False),
         ("high", "line held high (idle)", False),
         ("low", "line held low", False),
         ("random", "pseudo-random toggling on the bit grid", False),
         ("square", "square wave at 2/3 the baud (SPI-clock-like)", False),
         ("square_aligned", "square wave AT the baud (genuinely ambiguous)", True)]

print(f"{'case':38} {'expect':>7} {'detections':>11}  verdict")
bad = 0
for kind, desc, want_detect in CASES:
    n, cyc, errs = detector.run_detect(kind)
    got = n > 0
    ok = (got == want_detect)
    bad += not ok
    print(f"  {desc:36} {'HIT' if want_detect else 'REJECT':>7} {n:>11}  "
          f"{'ok' if ok else 'WRONG'}")
    if errs:
        print(f"      model errors: {errs[:2]}")
print()
print("PASS: detects UART and rejects every negative" if not bad
      else f"FAIL: {bad} case(s) wrong")
