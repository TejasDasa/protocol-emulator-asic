"""The Tiny Tapeout boundary: pin assignment, the run flag, and five machines.

test_multi.py proved the machines are independent with their pins wired straight
out. This proves the layer above: that a machine's slots actually appear on the
pins they were assigned, that its inputs actually read the pins they were
assigned, and that the run flag does what SPEC section 11.1 says.

Three things are checked every cycle, on top of the per-machine lockstep:

  * each assigned driver's value appears on its pin;
  * the run flag is low through configuration and high after;
  * before run, uo_out carries loader status rather than machine outputs.

The pin assignment is deliberately NOT the identity. Drivers are packed onto
pins in use-order, so machine 3's slot 0 lands on whatever pin is next free --
an identity map would pass even if the select fields were ignored.
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
NSM = 5
NOUT, NPIN = 16, 16
OSELW = 4          # ceil(log2(NSM * NSLOT)) = ceil(log2(15))
ISELW = 4          # ceil(log2(16))
OBITS = NOUT * OSELW
IBITS = NSM * NIN * ISELW
FIELDS = ("row", "link", "sr", "cnt", "c2", "crc", "tcount", "pinv")
WIDTHS = dict(row=ADDR_W, link=ADDR_W, sr=SR_W, cnt=CNT_W, c2=CNT_W,
              crc=5, tcount=TIMER_W, pinv=NSLOT)


def slice_of(val, k, width):
    return (val >> (k * width)) & ((1 << width) - 1)


async def wait_idle(dut, where, limit=200):
    """Wait for uo_out[0] (imem busy) to fall.

    BOUNDED on purpose. An unbounded busy-wait that never clears does not fail,
    it hangs -- this one ran 10 million cycles before a timeout killed it, which
    is far less useful than an error naming where it stuck. The walk is 48
    cycles, so anything past 200 is broken.
    """
    # uo_out[0] reports busy ONLY while run is low; once run is set the pin
    # belongs to the iomux and bit 0 is machine 0 slot 0, which for uart_tx
    # idles high. Waiting on it after run would never return.
    if i_(dut.dbg_run, "dbg_run"):
        return 0
    n = 0
    while i_(dut.uo_out, "uo_out") & 1:
        dut.ui_in.value = 0
        await RisingEdge(dut.clk)
        await settle(dut)
        n += 1
        if n > limit:
            raise AssertionError(
                f"imem busy (uo_out[0]) still high after {limit} cycles at "
                f"{where}; the loader is stuck or uo_out is not reporting busy")
    return n


async def shift_ctl(dut, enable_bit, bits, nbits, where=""):
    """Shift on ui_in, honouring uo_out[0] = imem busy."""
    for i in range(nbits):
        await wait_idle(dut, f"{where} bit {i}")
        dut.ui_in.value = (1 << enable_bit) | (((bits >> i) & 1) << 4)
        await RisingEdge(dut.clk)
        await settle(dut)
    await wait_idle(dut, f"{where} end")
    dut.ui_in.value = 0
    await settle(dut)


@cocotb.test()
async def chip_lockstep(dut):
    names = os.environ.get("CHIP_PROGS",
                           "uart_tx,uart_rx,spi,i2c,jtag").split(",")
    period = int(os.environ.get("BIT_PERIOD", "32"))
    cap = int(os.environ.get("CHIP_CYCLES", "2000"))

    machines = []
    for name in names:
        stash = capture_benchmark(name.strip(), period)
        core, w = stash["core"], stash["world"]
        words, decoded = encode_rows(core.p)
        core.p, core.row = decoded, 0
        machines.append(dict(name=name.strip(), core=core, w=w, words=words,
                             nslots=len(core.slots), nins=len(core.ins)))

    # ---- build a non-identity pin assignment -------------------------------
    # Outputs: every slot a program actually drives gets the next free pin.
    out_map = {}                       # pin -> driver index
    drv_pin = {}                       # driver index -> pin
    drv_od  = {}                       # driver index -> open drain?
    # SPEC section 11: an open-drain slot MUST be on a uio pin. A uo_out pin is
    # always driven and cannot release the net, so I2C would not work there.
    # Open-drain slots therefore take uio (pins 8..15) and push-pull slots take
    # uo_out (pins 0..7). Within each group they are packed in use-order, so
    # the map is still not the identity.
    nxt_pp, nxt_od = 0, 8
    for k, m in enumerate(machines):
        for s in range(m["nslots"]):
            drv = k * NSLOT + s
            od = (m["core"].slots[s][1] == "od")
            drv_od[drv] = od
            if od:
                pin, nxt_od = nxt_od, nxt_od + 1
            else:
                pin, nxt_pp = nxt_pp, nxt_pp + 1
            out_map[pin] = drv
            drv_pin[drv] = pin
    assert nxt_pp <= 8 and nxt_od <= NOUT, (
        f"{nxt_pp} push-pull slots (max 8) and {nxt_od - 8} open-drain (max 8)")

    # Inputs: every input a program actually reads gets the next free ui_in pin,
    # which is pins 0..7 (uio would collide with the outputs above).
    in_pin = {}                        # (machine, input) -> pin
    nxt_i = 0
    for k, m in enumerate(machines):
        for i in range(m["nins"]):
            in_pin[(k, i)] = nxt_i
            nxt_i += 1
    assert nxt_i <= 8, f"{nxt_i} inputs in use, only 8 ui_in pins"

    sel = 1                            # bit 0 = run, and it is sent FIRST
    for pin, drv in out_map.items():
        sel |= drv << (1 + pin * OSELW)
    for (k, i), pin in in_pin.items():
        sel |= pin << (1 + OBITS + (k * NIN + i) * ISELW)

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.tx_ne.value = 0
    dut.tx_data.value = 0
    dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await settle(dut)

    assert i_(dut.dbg_run, "dbg_run") == 0, "run must be 0 out of reset"

    for k, m in enumerate(machines):
        dut.uio_in.value = k << 5
        await settle(dut)
        await shift_ctl(dut, 1, config_word(m["core"]), CFG_BITS, f"cfg m{k}")
        padded = list(m["words"]) + [0] * (STT_ROWS - len(m["words"]))
        bits = 0
        for i, word in enumerate(padded):
            bits |= word << (32 * i)
        await shift_ctl(dut, 0, bits, 32 * len(padded), f"imem m{k}")
        assert i_(dut.dbg_run, "dbg_run") == 0, (
            f"run went high during machine {k}'s load")

    await shift_ctl(dut, 2, sel, 1 + OBITS + IBITS, "pinsel")
    assert i_(dut.dbg_run, "dbg_run") == 1, (
        "run should be set by the last bit of the pin-assignment chain")

    dut.uio_in.value = 0

    # Drive the machines' real idle inputs and wait for the chip to start them.
    # stt_chip delays machine enable two cycles after run precisely so the
    # synchronizers fill with this rather than with leftover chain data.
    ui = 0
    for k, m in enumerate(machines):
        m["w"].resolve()
        for i, netname in enumerate(m["core"].ins):
            ui |= (m["w"].nets[netname].value & 1) << in_pin[(k, i)]
    dut.ui_in.value = ui
    await settle(dut)
    waited = 0
    while not i_(dut.dbg_en, "dbg_en"):
        await RisingEdge(dut.clk)
        await settle(dut)
        waited += 1
        assert waited < 20, "machines never started after run went high"
    dut._log.info(f"machines started {waited} cycles after run")

    # ---- lockstep, plus the pins -------------------------------------------
    for m in machines:
        m["w"].resolve()
        for nname, n in m["w"].nets.items():
            if not m["w"].history[nname]:
                m["w"].history[nname].extend([n.value] * m["w"].sync)

    cycles = 0
    for t in range(cap):
        for m in machines:
            w = m["w"]
            w.t = t
            for d in w.devices:
                d.step(w)
            w.resolve()

        tx_ne_v = 0
        tx_data_v = 0
        for k, m in enumerate(machines):
            if m["w"].tx_fifo:
                tx_ne_v |= 1 << k
                tx_data_v |= (m["w"].tx_fifo[0] & 0xFF) << (k * SR_W)
            m["tx_before"] = len(m["w"].tx_fifo)
            m["rx_before"] = len(m["w"].rx_fifo)
        dut.tx_ne.value = tx_ne_v
        dut.tx_data.value = tx_data_v
        await settle(dut)
        pops = i_(dut.tx_pop, "tx_pop")
        pushes = i_(dut.rx_push, "rx_push")

        for m in machines:
            m["core"].step(m["w"])
            m["w"].resolve()
            for nname, n in m["w"].nets.items():
                m["w"].history[nname].append(n.value)

        # ui_in is driven from the POST-step net values, matching what
        # World.read_sync records. Driving it before the step samples the net
        # before the core's own contribution, which is invisible for a machine
        # reading an external driver and wrong for one that drives the wires it
        # reads -- i2c diverged at cycle 26 on exactly that.
        ui = 0
        for k, m in enumerate(machines):
            for i, netname in enumerate(m["core"].ins):
                ui |= (m["w"].nets[netname].value & 1) << in_pin[(k, i)]
        dut.ui_in.value = ui

        await RisingEdge(dut.clk)
        await settle(dut)
        cycles = t + 1

        raw = {f: i_(getattr(dut, "dbg_" + f), "dbg_" + f) for f in FIELDS}
        pins = (i_(dut.uio_out, "uio_out") << 8) | i_(dut.uo_out, "uo_out")
        oes = i_(dut.uio_oe, "uio_oe")
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
                        f"RTL {rtl[f]} vs model {mdl[f]}")
            popped = m["tx_before"] - len(m["w"].tx_fifo)
            pushed = len(m["w"].rx_fifo) - m["rx_before"]
            if ((pops >> k) & 1) != popped:
                raise Divergence(f"machine {k} ({m['name']}): cycle {t}: "
                                 f"tx_pop {(pops >> k) & 1} vs model {popped}")
            if ((pushes >> k) & 1) != pushed:
                raise Divergence(f"machine {k} ({m['name']}): cycle {t}: "
                                 f"rx_push {(pushes >> k) & 1} vs model {pushed}")
            # every assigned driver must appear on its pin
            for s in range(m["nslots"]):
                drv = k * NSLOT + s
                pin = drv_pin[drv]
                pv = (mdl["pinv"] >> s) & 1
                od = drv_od[drv]
                # stt_core drives pin_out = pinv & ~od and oe = ~od | ~pinv, so an
                # open-drain slot holding 1 RELEASES the net: it drives 0 with the
                # enable off, and the external pull-up supplies the level.
                want = 0 if od else pv
                got = (pins >> pin) & 1
                if got != want:
                    raise Divergence(
                        f"machine {k} ({m['name']}) slot {s} "
                        f"({'open-drain' if od else 'push-pull'}) is on pin {pin}: "
                        f"cycle {t}: pin reads {got}, expected {want} "
                        f"(pinv={pv})\n  pins=0x{pins:04x}")
                if pin >= 8:
                    want_oe = 1 if not od else (0 if pv else 1)
                    got_oe = (oes >> (pin - 8)) & 1
                    if got_oe != want_oe:
                        raise Divergence(
                            f"machine {k} ({m['name']}) slot {s} on uio pin "
                            f"{pin - 8}: cycle {t}: oe reads {got_oe}, expected "
                            f"{want_oe} (pinv={pv}, open-drain={od})")

    assert i_(dut.dbg_run, "dbg_run") == 1
    dut._log.info(
        f"{NSM} machines through the TT boundary for {cycles} cycles, "
        f"no divergence and every assigned pin correct")
    dut._log.info(f"  output pins used: {sorted(out_map)}  "
                  f"input pins used: {sorted(in_pin.values())}")
