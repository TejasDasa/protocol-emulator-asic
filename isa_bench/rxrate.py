"""Byte rate into the RX FIFO, at each protocol's fastest working bit period.

The harness high-waters say nothing about rate. What bounds FIFO depth is how
long the host has to service a byte before the next one lands, which is
(bits per frame) x (cycles per bit) at the minimum bit period the program works
at -- the worst case the design must survive, not the case the benchmark ran.
"""
import io, contextlib, sys
sys.path.insert(0, ".")
with contextlib.redirect_stdout(io.StringIO()):
    import bench, programs as P

# bits per host byte, including framing, from the programs themselves
FRAME = {"uart_tx": 10, "uart_rx": 10, "spi": 8, "i2c": 9, "usb": 8}
DIR = {"uart_tx": "TX", "uart_rx": "RX", "spi": "both", "i2c": "both", "usb": "TX"}

saved = dict(P.BUILDERS["STT"])
P.BUILDERS["STT"].update(P.STT_1PIN)
print(f"{'program':9} {'dir':>5} {'min cyc/bit':>12} {'bits/byte':>10} "
      f"{'cyc/byte':>9} {'depth4 budget':>14}")
worst = None
try:
    for n in ["uart_tx", "uart_rx", "spi", "i2c", "usb"]:
        with contextlib.redirect_stdout(io.StringIO()):
            ok, cpb = bench.fastest("STT", n)
        cyc_byte = cpb * FRAME[n]
        if DIR[n] in ("RX", "both"):
            if worst is None or cyc_byte < worst[1]:
                worst = (n, cyc_byte, cpb)
        print(f"  {n:9} {DIR[n]:>5} {cpb:>12} {FRAME[n]:>10} "
              f"{cyc_byte:>9.1f} {4*cyc_byte:>13.0f}c")
finally:
    P.BUILDERS["STT"].update(saved)

n, cyc, cpb = worst
print(f"\nBinding RX case: {n} at {cpb} cycles/bit -> a byte every {cyc:.0f} cycles.")
for d in (2, 4, 8, 16):
    us = d * cyc / 47.0
    print(f"  depth {d:>2}: {d*cyc:>6.0f} cycles of host latency "
          f"= {us:6.2f} us at 47 MHz")
print(f"\nIf a future capture mode pushes ONE ENTRY PER EDGE rather than per byte,")
print(f"an edge can arrive every {cpb} cycles:")
for d in (4, 8, 16, 32):
    print(f"  depth {d:>2}: {d*cpb:>6.0f} cycles = {d*cpb/47.0:6.2f} us at 47 MHz")
