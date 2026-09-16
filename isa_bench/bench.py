"""Run every benchmark on every ISA, check correctness, and sweep timing."""
import sys
from world import World, Host
from devices import (UartMonitor, UartDriver, SpiTarget, I2cTarget, UsbLsMonitor,
                     crc5_usb, bits_lsb)
from programs import BUILDERS


class Result:
    def __init__(self, ok, detail="", jitter=0, bit_time=None):
        self.ok, self.detail, self.jitter, self.bit_time = ok, detail, jitter, bit_time


def always(w):
    return True


def check_errors(w):
    return None if not w.errors else "; ".join(w.errors[:3])


# ------------------------------------------------------------------ UART TX
def run_uart_tx(isa, P):
    core, prog = BUILDERS[isa]["uart_tx"](P)
    data = [0x55, 0x00, 0xFF, 0xA3, 0x01, 0x80, 0x7E]
    w = World([("tx", 1)])
    mon = UartMonitor("tx", P)
    w.devices = [Host([(always, lambda w: w.tx_fifo.extend(data))]), mon]
    w.run(core, 20 * P * len(data) + 500, lambda w: len(mon.frames) >= len(data))
    got = [b for b, ok in mon.frames if ok]
    err = check_errors(w)
    ok = not err and got == data and all(ok for _, ok in mon.frames) and mon.jitter == 0
    return prog, Result(ok, err or f"got {[hex(b) for b in got]} jitter {mon.jitter}",
                        mon.jitter, P)


# ------------------------------------------------------------------ UART RX
def run_uart_rx(isa, P):
    core, prog = BUILDERS[isa]["uart_rx"](P)
    frames = [(0x55, True), (0xC3, True), (0x7E, False), (0x00, True), (0xFF, True),
              (0x81, True), (0x01, True)]
    w = World([("rx", 1)])
    drv = UartDriver("rx", P, frames)
    w.devices = [drv]
    w.run(core, drv.end + 4 * P, lambda w: False)
    w.errors = [e for e in w.errors if "timeout" not in e]
    got = [v & 0xFF for v in w.rx_fifo]
    want = [b for b, good in frames if good]
    err = check_errors(w)
    return prog, Result(not err and got == want, err or f"got {[hex(b) for b in got]}",
                        0, P)


# ------------------------------------------------------------------ SPI
def run_spi(isa, P):
    core, prog = BUILDERS[isa]["spi"](P)
    t1, t2 = [0xA5, 0x3C, 0xFF], [0x00, 0x81]
    replies = [0x11, 0x22, 0x33, 0x44, 0x55]
    w = World([("cs", 1), ("sck", 0), ("mosi", 0), ("miso", 1)])
    tgt = SpiTarget("cs", "sck", "mosi", "miso", replies)
    host = Host([
        (always, lambda w: w.tx_fifo.extend(t1)),
        (lambda w: len(tgt.transactions) == 1, lambda w: w.tx_fifo.extend(t2)),
    ])
    w.devices = [host, tgt]
    w.run(core, 200 * P + 2000,
          lambda w: len(tgt.transactions) == 2 and len(w.rx_fifo) == 5)
    err = check_errors(w)
    got_rx = [v & 0xFF for v in w.rx_fifo]
    ok = not err and tgt.transactions == [t1, t2] and got_rx == replies
    busy = sum(1 for v in w.history["cs"] if v == 0)
    return prog, Result(ok, err or f"target saw {tgt.transactions}, host got {got_rx}",
                        0, busy / 40)


# ------------------------------------------------------------------ I2C
def run_i2c(isa, P, stretch=None):
    core, prog = BUILDERS[isa]["i2c"](P)
    w = World([("sda", 1), ("scl", 1)])
    stretch = 2 * P if stretch is None else stretch   # longer than a whole bit
    tgt = I2cTarget("sda", "scl", 0x42, stretch_max=stretch)
    txns = [[0x84, 0x5A], [0x84, 0xFF], [0x20, 0x33]]
    host = Host([
        (always, lambda w: w.tx_fifo.extend(txns[0])),
        (lambda w: len(w.rx_fifo) == 1, lambda w: w.tx_fifo.extend(txns[1])),
        (lambda w: len(w.rx_fifo) == 2, lambda w: w.tx_fifo.extend(txns[2])),
    ])
    w.devices = [host, tgt]
    w.run(core, 400 * P + 4000,
          lambda w: len(w.rx_fifo) == 3 and len(tgt.transactions) == 3)
    err = check_errors(w)
    status = [v & 0xFF for v in w.rx_fifo]
    want_t = [(0x84, [0x5A], [True, True]), (0x84, [0xFF], [True, False]),
              (0x20, [], [False])]
    ok = (not err and tgt.transactions == want_t and len(status) == 3
          and status[0] == 0 and status[1] != 0 and status[2] != 0 and not w.tx_fifo)
    scl = w.history["scl"]
    rises = sum(1 for a, b in zip(scl, scl[1:]) if a == 0 and b == 1)
    busy = sum(1 for s, d in zip(scl, w.history["sda"]) if not (s == 1 and d == 1))
    return prog, Result(ok, err or f"target saw {tgt.transactions}, status {status}",
                        0, busy / max(rises, 1))


# ------------------------------------------------------------------ USB LS token
def run_usb(isa, P):
    core, prog = BUILDERS[isa]["usb"](P)
    packets = [(0x2D, 0x000), (0xE1, 0x3A | (0xA << 7)), (0x69, 0x7FF), (0x69, 0x001)]
    w = World([("dp", 0), ("dm", 1)])
    mon = UsbLsMonitor("dp", "dm", P)

    def push(i):
        pid, field = packets[i]
        if isa == "PIO":   # host must build the whole bit stream, including CRC
            crc = crc5_usb(bits_lsb(field, 11))
            w.tx_fifo.append(0x80 | pid << 8 | field << 16 | crc << 27)
        else:
            w.tx_fifo.extend([pid, field & 0xFF, field >> 8])

    script = [(always, lambda w: push(0))]
    for i in range(1, len(packets)):
        script.append((lambda w, i=i: len(mon.packets) == i, lambda w, i=i: push(i)))
    w.devices = [Host(script), mon]
    w.run(core, 60 * P * len(packets) + 1000, lambda w: len(mon.packets) == len(packets))
    err = check_errors(w)
    ok = not err and mon.packets == packets and mon.jitter == 0
    return prog, Result(ok, err or f"decoded {mon.packets} jitter {mon.jitter}",
                        mon.jitter, P)


BENCHES = {"uart_tx": run_uart_tx, "uart_rx": run_uart_rx, "spi": run_spi,
           "i2c": run_i2c, "usb": run_usb}
NOMINAL = {"uart_tx": 32, "uart_rx": 32, "spi": 32, "i2c": 32, "usb": 32}
SWEEP = {"uart_tx": range(2, 33), "uart_rx": range(2, 33), "spi": range(2, 33, 2),
         "i2c": range(4, 65, 4), "usb": range(2, 33)}


FIXED_RATE = {"uart_tx", "uart_rx", "usb"}


def fastest(isa, bench):
    """Best measured cycles per bit among passing timing settings.
    Fixed-rate protocols: the smallest passing bit period.
    SPI/I2C: timing is set by the program, so measure the achieved bit time."""
    best = (None, None)
    for P in SWEEP[bench]:
        try:
            _, r = BENCHES[bench](isa, P)
        except ValueError:
            continue
        if not r.ok:
            continue
        if bench in FIXED_RATE:
            return P, r.bit_time
        if best[1] is None or r.bit_time < best[1]:
            best = (P, r.bit_time)
    return best


if __name__ == "__main__":
    isas = ["PIO", "STT", "RM"]
    only = sys.argv[1:] or list(BENCHES)
    for bench in only:
        for isa in isas:
            prog, r = BENCHES[bench](isa, NOMINAL[bench])
            print(f"{bench:8} {isa:4} {'PASS' if r.ok else 'FAIL'} bits={prog.bits:4} {r.detail}")
