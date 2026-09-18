import io, contextlib, sys, json
sys.path.insert(0, ".")
with contextlib.redirect_stdout(io.StringIO()):
    import programs as P, jtag_prog
    from rowformat import Format
B = dict(P.STT_1PIN); B["jtag"] = jtag_prog.stt_jtag
out = {}
for n, b in B.items():
    core, prog = b(32)
    r = Format("single5", "grouped", tgt_bits=8).encode(prog)
    out[n] = r["packed"]
print(json.dumps(out))
