"""Five machines, five DIFFERENT programs, all in lockstep at once.

Replication is the easy part to write and the easy part to get subtly wrong. The
failure mode is not that a machine computes the wrong thing -- it is that
machines are not independent: a load reaching the wrong one, a shared staging
register, or instances that synthesis merged because they were never given
different state. docs/area-study.md records exactly that happening.

So this does not run the same program five times. It loads a different reference
program into every machine, runs a separate SttCore and a separate World for
each, and compares ALL of them against their own model on EVERY cycle. A machine
that leaked into its neighbour, or a load that addressed the wrong machine,
diverges immediately and the failure names which machine and which field.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from lockstep import CFG_BITS, capture_benchmark, config_word, encode_rows
from steps import PERIOD_NS, Divergence, i_, settle

STT_ROWS = 32
SR_W, CNT_W, ADDR_W, TIMER_W, NSLOT, NIN = 8, 8, 5, 16, 3, 2
FIELDS = ("row", "link", "sr", "cnt", "c2", "crc", "tcount", "pinv")
WIDTHS = dict(row=ADDR_W, link=ADDR_W, sr=SR_W, cnt=CNT_W, c2=CNT_W,
              crc=5, tcount=TIMER_W, pinv=NSLOT)


def slice_of(val, k, width):
    return (val >> (k * width)) & ((1 << width) - 1)


async def shift_into(dut, enable_sig, bits, nbits):
    """Serial shift honouring imem_ld_busy, which the CFGMEM loader asserts."""
    for i in range(nbits):
        while int(dut.imem_ld_busy.value) == 1:
            enable_sig.value = 0
            await RisingEdge(dut.clk)
            await settle(dut)
        enable_sig.value = 1
        dut.ld_in.value = (bits >> i) & 1
        await RisingEdge(dut.clk)
        await settle(dut)
    while int(dut.imem_ld_busy.value) == 1:
        enable_sig.value = 0
        await RisingEdge(dut.clk)
        await settle(dut)
    enable_sig.value = 0
    dut.ld_in.value = 0
    await settle(dut)


@cocotb.test()
async def multi_lockstep(dut):
    names = os.environ.get("MULTI_PROGS",
                           "uart_tx,uart_rx,spi,i2c,jtag").split(",")
    period = int(os.environ.get("BIT_PERIOD", "32"))
    cap = int(os.environ.get("MULTI_CYCLES", "2500"))
    nsm = len(names)

    machines = []
    for name in names:
        stash = capture_benchmark(name.strip(), period)
        core, w = stash["core"], stash["world"]
        words, decoded = encode_rows(core.p)
        core.p, core.row = decoded, 0
        machines.append(dict(name=name.strip(), core=core, w=w, words=words,
                             done=stash["done"], nslots=len(core.slots),
                             finished=False))

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())

    # ---- reset once, then load each machine in turn -----------------------
    dut.en.value = 0
    dut.imem_ld_en.value = 0
    dut.cfg_ld_en.value = 0
    dut.ld_in.value = 0
    dut.sm_sel.value = 0
    dut.tx_ne.value = 0
    dut.tx_data.value = 0

    pin_in = 0
    for k, m in enumerate(machines):
        m["w"].resolve()
        for i, netname in enumerate(m["core"].ins):
            pin_in |= (m["w"].nets[netname].value & 1) << (k * NIN + i)
    dut.pin_in.value = pin_in

    dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await settle(dut)

    for k, m in enumerate(machines):
        dut.sm_sel.value = k
        await settle(dut)
        await shift_into(dut, dut.cfg_ld_en, config_word(m["core"]), CFG_BITS)
        padded = list(m["words"]) + [0] * (STT_ROWS - len(m["words"]))
        bits = 0
        for i, word in enumerate(padded):
            bits |= word << (32 * i)
        await shift_into(dut, dut.imem_ld_en, bits, 32 * len(padded))

    dut.en.value = 1
    await settle(dut)

    # ---- all machines in lockstep, each against its own model -------------
    for m in machines:
        m["w"].resolve()
        for nname, n in m["w"].nets.items():
            if not m["w"].history[nname]:
                m["w"].history[nname].extend([n.value] * m["w"].sync)

    cycles = 0
    for t in range(cap):
        tx_ne_v = 0
        tx_data_v = 0
        for k, m in enumerate(machines):
            w = m["w"]
            w.t = t
            for d in w.devices:
                d.step(w)
            w.resolve()
            if w.tx_fifo:
                tx_ne_v |= 1 << k
                tx_data_v |= (w.tx_fifo[0] & 0xFF) << (k * SR_W)
            m["tx_before"] = len(w.tx_fifo)
            m["rx_before"] = len(w.rx_fifo)
        dut.tx_ne.value = tx_ne_v
        dut.tx_data.value = tx_data_v

        await settle(dut)
        pops = i_(dut.tx_pop, "tx_pop")
        pushes = i_(dut.rx_push, "rx_push")
        rxd = i_(dut.rx_data, "rx_data")

        pin_in = 0
        for k, m in enumerate(machines):
            w = m["w"]
            m["core"].step(w)
            w.resolve()
            for nname, n in w.nets.items():
                w.history[nname].append(n.value)
            for i, netname in enumerate(m["core"].ins):
                pin_in |= (w.nets[netname].value & 1) << (k * NIN + i)
        dut.pin_in.value = pin_in

        await RisingEdge(dut.clk)
        await settle(dut)
        cycles = t + 1

        raw = {f: i_(getattr(dut, "dbg_" + f), "dbg_" + f) for f in FIELDS}
        for k, m in enumerate(machines):
            core = m["core"]
            rtl = {f: slice_of(raw[f], k, WIDTHS[f]) for f in FIELDS}
            mdl = dict(row=core.row, link=core.link, sr=core.sr, cnt=core.cnt,
                       c2=core.c2, crc=core.crc, tcount=core.tcount,
                       pinv=sum((b & 1) << i for i, b in enumerate(core.pinv)))
            rtl["pinv"] &= (1 << m["nslots"]) - 1 if m["nslots"] else 0
            for f in FIELDS:
                if rtl[f] != mdl[f]:
                    raise Divergence(
                        f"machine {k} ({m['name']}): cycle {t}: {f} differs -- "
                        f"RTL {rtl[f]} vs model {mdl[f]}\n"
                        f"  RTL   {rtl}\n  model {mdl}\n"
                        f"  (the other machines are running different programs; "
                        f"a divergence here means this machine was disturbed)")
            popped = m["tx_before"] - len(m["w"].tx_fifo)
            pushed = len(m["w"].rx_fifo) - m["rx_before"]
            if ((pops >> k) & 1) != popped:
                raise Divergence(f"machine {k} ({m['name']}): cycle {t}: "
                                 f"tx_pop {(pops >> k) & 1} vs model {popped}")
            if ((pushes >> k) & 1) != pushed:
                raise Divergence(f"machine {k} ({m['name']}): cycle {t}: "
                                 f"rx_push {(pushes >> k) & 1} vs model {pushed}")
            if pushed and slice_of(rxd, k, SR_W) != (m["w"].rx_fifo[-1] & 0xFF):
                raise Divergence(f"machine {k} ({m['name']}): cycle {t}: rx_data "
                                 f"0x{slice_of(rxd, k, SR_W):02x} vs "
                                 f"0x{m['w'].rx_fifo[-1] & 0xFF:02x}")
            if not m["finished"] and m["done"](m["w"]):
                m["finished"] = True

    done_n = sum(1 for m in machines if m["finished"])
    dut._log.info(
        f"{nsm} machines in lockstep for {cycles} cycles, no divergence: "
        + ", ".join(f"{m['name']}({len(m['words'])}r)" for m in machines))
    dut._log.info(f"  benchmarks that reached their completion condition: "
                  f"{done_n}/{nsm}")
    assert cycles > 0
