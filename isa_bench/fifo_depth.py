"""How deep do the FIFOs actually need to be?

Runs each reference benchmark and records the high-water mark of the TX and RX
queues, which the models keep unbounded. That is a measured lower bound on the
depth, not a guess.
"""
import io, contextlib, sys
sys.path.insert(0, ".")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    import world as W
    import bench, jtag_bench, programs as P

names = ["uart_tx", "uart_rx", "spi", "i2c", "usb"]
real_run = W.World.run
print(f"{'program':9} {'tx max':>7} {'rx max':>7} {'tx total':>9} {'rx total':>9}")
worst_tx = worst_rx = 0
for n in names:
    hi = {"tx": 0, "rx": 0, "txn": 0, "rxn": 0}

    def traced(self, core, max_cycles, done, _hi=hi):
        _hi["txn"] = len(self.tx_fifo)
        for t in range(max_cycles):
            self.t = t
            for d in self.devices:
                d.step(self)
            self.resolve()
            _hi["tx"] = max(_hi["tx"], len(self.tx_fifo))
            _hi["rx"] = max(_hi["rx"], len(self.rx_fifo))
            core.step(self)
            self.resolve()
            for nm, nt in self.nets.items():
                self.history[nm].append(nt.value)
            _hi["tx"] = max(_hi["tx"], len(self.tx_fifo))
            _hi["rx"] = max(_hi["rx"], len(self.rx_fifo))
            if done(self):
                break
        _hi["rxn"] = len(self.rx_fifo)
        return True

    W.World.run = traced
    saved = dict(P.BUILDERS["STT"])
    P.BUILDERS["STT"].update(P.STT_1PIN)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            bench.BENCHES[n]("STT", 32)
    finally:
        P.BUILDERS["STT"].update(saved)
        W.World.run = real_run
    worst_tx = max(worst_tx, hi["tx"])
    worst_rx = max(worst_rx, hi["rx"])
    print(f"  {n:9} {hi['tx']:>7} {hi['rx']:>7} {hi['txn']:>9} {hi['rxn']:>9}")

print(f"\nworst TX occupancy across the reference set: {worst_tx}")
print(f"worst RX occupancy across the reference set: {worst_rx}")
print("\nNote: the benchmarks preload the whole TX payload before the machine")
print("starts, so TX max is the payload size, not a rate requirement. RX max is")
print("what the host would have to drain, and nothing drains it during the run.")
