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
O_HEN = 1 + OBITS + IBITS      # host_en, then host_stb_sel, host_din_sel
# SPEC section 11.2. The strobe and data pins are uio, so they never collide
# with the ui_in pins the machines read; the output pin takes the free select
# code 15, which no driver uses.
HOST_STB_PIN  = 15             # uio_in[7]
HOST_DIN_PIN  = 14             # uio_in[6]
HOST_DOUT_PIN = 13             # uio_out[5]
HOST_CODE = 15
FRAME = 16
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
    assert nxt_od <= HOST_DOUT_PIN, (
        f"open-drain slots reached pin {nxt_od - 1}, colliding with the host "
        f"port's output pin {HOST_DOUT_PIN}")
    sel |= HOST_CODE << (1 + HOST_DOUT_PIN * OSELW)
    sel |= 1 << O_HEN
    sel |= HOST_STB_PIN << (O_HEN + 1)
    sel |= HOST_DIN_PIN << (O_HEN + 1 + ISELW)
    NSEL = O_HEN + 1 + 2 * ISELW

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
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

    await shift_ctl(dut, 2, sel, NSEL, "pinsel")
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

    # The benchmarks preload the whole TX payload into an UNBOUNDED model queue --
    # uart_tx queues 7 bytes at cycle 0 -- and the hardware FIFO is 4 deep. So the
    # payload is taken out of the model queue and fed to BOTH sides together, as
    # space allows, which is what a real host does. Model and RTL then hold
    # identical queues and the lockstep stays exact.
    hp = dict(k=0, sel=len(machines) - 1, wr=False, byte=0, word=0, rx=0, st=0)
    for m in machines:
        m["pending"] = []
        m["tx_full_seen"] = False
        m["model_q"] = 0          # bytes we have fed and the model has not popped
        m["drained"] = 0

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

        for m in machines:
            # Intercept whatever the benchmark's Host device just queued. It fires
            # inside the loop, not before it, and dumps the whole payload at once
            # -- uart_tx queues 7 bytes on cycle 0 against a 4-deep FIFO. Anything
            # beyond what we have fed is taken for `pending` and released to both
            # sides together as the hardware has room.
            extra = len(m["w"].tx_fifo) - m["model_q"]
            if extra > 0:
                newly = [m["w"].tx_fifo.pop() for _ in range(extra)]
                m["pending"].extend(reversed(newly))
            m["tx_before"] = len(m["w"].tx_fifo)
            m["rx_before"] = len(m["w"].rx_fifo)

        # The host talks over the SPEC section 11.2 serial port, so servicing a
        # machine costs 16 clocks instead of 1. Five machines round robin means
        # each is serviced every 80 cycles, against a byte every 30 at the
        # fastest receiver and a 4-deep FIFO holding 120 cycles' worth -- which
        # is why depth 4 still holds once the port is serialized.
        if hp["k"] == 0:
            hp["sel"] = (hp["sel"] + 1) % len(machines)
            ms = machines[hp["sel"]]
            hp["wr"] = bool(ms["pending"]) and not ms["tx_full_seen"]
            hp["byte"] = ms["pending"][0] if hp["wr"] else 0
            hp["word"] = ((hp["sel"] & 7) << 13) | (int(hp["wr"]) << 12) \
                | ((hp["byte"] & 0xFF) << 4)
            hp["rx"] = 0
            hp["st"] = 0
        ms = machines[hp["sel"]]
        k = hp["k"]
        dut.uio_in.value = (1 << (HOST_STB_PIN - 8)) \
            | ((((hp["word"] >> (15 - k)) & 1)) << (HOST_DIN_PIN - 8))
        await settle(dut)
        # Frame out bit 15-k: zeros, then the RX byte, then the status nibble.
        ob = (i_(dut.uio_out, "uio_out") >> (HOST_DOUT_PIN - 8)) & 1
        if 4 <= k <= 11:
            hp["rx"] = (hp["rx"] << 1) | ob
        elif k >= 12:
            hp["st"] = (hp["st"] << 1) | ob
        will_write = False
        if k == FRAME - 1:
            rx_ne   = (hp["st"] >> 3) & 1
            tx_full = (hp["st"] >> 2) & 1
            ms["tx_full_seen"] = bool(tx_full)
            will_write = hp["wr"] and not tx_full
            if rx_ne:
                want = ms["w"].rx_fifo[ms["drained"]] & 0xFF
                if hp["rx"] != want:
                    raise Divergence(
                        f"machine {hp['sel']} ({ms['name']}): cycle {t}: host "
                        f"read byte {ms['drained']} as 0x{hp['rx']:02x} over the "
                        f"serial port, model pushed 0x{want:02x}")
                ms["drained"] += 1
        pops = i_(dut.tx_pop, "tx_pop")
        pushes = i_(dut.rx_push, "rx_push")

        for m in machines:
            m["core"].step(m["w"])
            m["w"].resolve()
            for nname, n in m["w"].nets.items():
                m["w"].history[nname].append(n.value)
            # Taken HERE, before the host's byte is appended below: measuring it
            # after would see the queue grow and report a negative pop count.
            m["popped"] = m["tx_before"] - len(m["w"].tx_fifo)
            m["pushed"] = len(m["w"].rx_fifo) - m["rx_before"]

        # The byte the host wrote lands in the RTL FIFO at the coming edge, so the
        # model queue gets it now, after the model has stepped: both then see it
        # from the next cycle.
        for m in machines:
            m["model_q"] -= m["popped"]
        if will_write:
            ms["w"].tx_fifo.append(ms["pending"].pop(0))
            ms["model_q"] += 1
        hp["k"] = (hp["k"] + 1) % FRAME

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
            popped = m["popped"]
            pushed = m["pushed"]
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
    dut._log.info("  over the section 11.2 serial port: "
                  + ", ".join(f"{m['name']} read {m['drained']}"
                              for m in machines))
