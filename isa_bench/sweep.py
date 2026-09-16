"""Timing sweep and final results table."""
import json
from bench import BENCHES, NOMINAL, fastest
from programs import BUILDERS
from stt import WIDTH

rows = {}
for bench in BENCHES:
    for isa in ["PIO", "STT", "RM"]:
        prog, r = BENCHES[bench](isa, NOMINAL[bench])
        minP, bit_time = fastest(isa, bench)
        entry = {"pass": r.ok, "bits": prog.bits, "min_param": minP, "bit_time": bit_time,
                 "units": len(getattr(prog, "instrs", getattr(prog, "rows", [])))}
        if isa == "STT":
            entry["stt_version"] = prog.version
            entry["bits_v1"] = prog.bits_at(1) if prog.version == 1 else None
            entry["bits_v2"] = prog.bits_at(2)
        rows[f"{bench}/{isa}"] = entry
        print(bench, isa, entry, flush=True)
json.dump(rows, open("results.json", "w"), indent=1)
