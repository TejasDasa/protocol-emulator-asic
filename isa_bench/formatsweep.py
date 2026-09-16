"""Compare row formats: bits, correctness of decoded programs, speed, and palette generalization."""
import json
import programs as P
import bench as B
from rowformat import Format

BENCH = ["uart_tx", "uart_rx", "spi", "i2c", "usb"]
SRC = {"slots3": {b: P.BUILDERS["STT"][b] for b in BENCH},
       "single5": P.STT_1PIN, "combo": P.STT_1PIN}
ORIG = {b: P.BUILDERS["STT"][b] for b in BENCH}


def palette_from(fmt, benches):
    keys = set()
    for b in benches:
        keys |= {fmt.key(r) for r in SRC[fmt.pins][b](32)[1].rows}
    empty = ((), ()) if fmt.pins == "combo" else ()
    return [empty] + sorted(keys - {empty}, key=str)


def evaluate(fmt, check=True):
    out = {}
    for b in BENCH:
        if fmt.storage == "silicon" and fmt.palette == "loo":
            f = Format(fmt.pins, fmt.acts, "silicon", palette_from(fmt, [x for x in BENCH if x != b]))
        elif fmt.storage == "silicon":
            f = Format(fmt.pins, fmt.acts, "silicon", palette_from(fmt, BENCH))
        else:
            f = fmt
        res = f.encode(SRC[fmt.pins][b](32)[1])
        if res["bits"] is None:
            out[b] = dict(bits=None, missing=res["missing"])
            continue
        entry = dict(bits=res["bits"], row_width=res["row_width"], rows=res["rows"],
                     palette_bits=res["palette_bits"])
        if f.acts == "palette" and f.storage == "silicon":
            entry["palette_size"] = len(f.palette)
        if check:
            def build(T, b=b, dec=res["decoded"]):
                core, _ = SRC[fmt.pins][b](T)
                core.p, core.row = dec, 0
                return core, dec
            P.BUILDERS["STT"][b] = build
            _, r = B.BENCHES[b]("STT", 32)
            entry["ok"] = r.ok
            entry["speed"] = B.fastest("STT", b)[1]
            P.BUILDERS["STT"][b] = ORIG[b]
        out[b] = entry
    return out


formats = [
    ("A", Format("slots3", "flags")),
    ("B", Format("slots3", "grouped")),
    ("C", Format("single5", "flags")),
    ("D", Format("single5", "grouped")),
    ("E", Format("single5", "palette", "program")),
    ("F", Format("combo", "palette", "program")),
    ("G", Format("single5", "palette", "silicon")),
    ("H", Format("combo", "palette", "silicon")),
]
results = {}
for tag, fmt in formats:
    res = evaluate(fmt)
    results[tag] = dict(label=fmt.label, per_bench=res)
    tot4 = sum(res[b]["bits"] for b in BENCH[:4])
    tot5 = tot4 + res["usb"]["bits"]
    ok = all(res[b]["ok"] for b in BENCH)
    widths = sorted({res[b]["row_width"] for b in BENCH})
    extra = f" palette={res['usb'].get('palette_size')}" if fmt.storage == "silicon" else ""
    print(f"{tag} {fmt.label:28} width={widths} first4={tot4:5} all5={tot5:5} "
          f"{'ALL PASS' if ok else 'FAIL'}{extra}  bits:{[res[b]['bits'] for b in BENCH]} "
          f"speed:{[res[b]['speed'] for b in BENCH]}")

print("\nLeave-one-out: silicon palette built from the other four programs")
for tag, fmt in [("G", Format("single5", "palette", "silicon", "loo")),
                 ("H", Format("combo", "palette", "silicon", "loo"))]:
    res = evaluate(fmt, check=True)
    results[tag + "_loo"] = res
    for b in BENCH:
        e = res[b]
        if e["bits"] is None:
            print(f"  {tag} {b:8} DOES NOT FIT: {e['missing']} entries missing")
        else:
            print(f"  {tag} {b:8} fits, palette {e['palette_size']} entries, bits {e['bits']}, "
                  f"{'PASS' if e['ok'] else 'FAIL'}")
json.dump(results, open("format_results.json", "w"), indent=1, default=str)
