"""Inter-pin skew on the signed-off gate netlist, with SDF back-annotation.

SPEC §16 records skew between a clock and its data -- SCK/MOSI, SCL/SDA,
TCK/TMS -- as unmeasured, because the Python models have no pin path at all.
They say when a machine DECIDES to change a pin. This says when the pin
changes.

Both pins of every pair are driven by registers on the same clock, so the skew
between them is the difference in their clock-to-output delays. That delay is
measured directly here, which also supplies the reference the measurement
needs: a clock-to-output delay is necessarily non-zero, so if it reads zero the
instrument is broken rather than the design being perfect. That is not
hypothetical -- Icarus quantized every delay to 1 ns until `prep_sdf.py` was
written, and reported exactly zero skew everywhere while doing it.

Everything runs in a SCALED time domain: SDF delays are multiplied by
SCALE and the clock period with them, because Icarus rounds annotated delays
to the cell's 1 ns time unit. Measured intervals are divided by SCALE to
recover real time. See rtl2/sdf/README.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Edge, RisingEdge, Timer
from cocotb.utils import get_sim_time

from lockstep import CFG_BITS, capture_benchmark, config_word, encode_rows
from pinmap import PinPlan

SCALE = int(os.environ.get("SDF_SCALE", "1000"))
PERIOD_NS = 20 * SCALE                 # 20 ns of real time, scaled
STT_ROWS = 32
NSM, NSLOT, NIN = 5, 3, 2

# slot -> pin. Push-pull slots go on uo_out (0..7); open drain must go on uio
# (8..15), because a uo_out pin is always driven and can never release (§11.1).
PP_PINS = [0, 1, 2]
OD_PINS = [8, 9, 10]
HOST_STB, HOST_DIN, HOST_DOUT = 15, 14, 13   # SPEC 11.2, on the uio side
FRAME = 16


async def shift_ctl(dut, enable_bit, bits, nbits):
    for i in range(nbits):
        while (int(dut.uo_out.value) & 1) if dut.uo_out.value.is_resolvable else 0:
            dut.ui_in.value = 0
            await RisingEdge(dut.clk)
        dut.ui_in.value = (1 << enable_bit) | (((bits >> i) & 1) << 4)
        await RisingEdge(dut.clk)
    dut.ui_in.value = 0
    await RisingEdge(dut.clk)


async def host_frame(dut, sel, wr, data):
    """One SPEC 11.2 transaction: 16 clocks of host_stb, MSB first.

    Every reference program measured here is a transmitter gated on the `fifo`
    test, so without host bytes they sit in their idle row forever and no pin
    ever moves. That is exactly what the first run of this test showed.
    """
    word = ((sel & 7) << 13) | ((wr & 1) << 12) | ((data & 0xFF) << 4)
    for k in range(15, -1, -1):
        dut.uio_in.value = (1 << (HOST_STB - 8)) | (((word >> k) & 1) << (HOST_DIN - 8))
        await RisingEdge(dut.clk)
    dut.uio_in.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def skew(dut):
    name = os.environ.get("PROG", "spi")
    period = int(os.environ.get("BIT_PERIOD", "32"))
    cycles = int(os.environ.get("SKEW_CYCLES", "1200"))

    stash = capture_benchmark(name, period)
    core = stash["core"]
    words, decoded = encode_rows(core.p)
    core.p, core.row = decoded, 0
    nslots = len(core.slots)
    od = [i for i, (_n, m) in enumerate(core.slots) if m == "od"]

    plan = PinPlan()
    pin_of = {}
    npp = nod = 0
    for s in range(nslots):
        if s in od:
            pin = OD_PINS[nod]; nod += 1
        else:
            pin = PP_PINS[npp]; npp += 1
        pin_of[s] = pin
        plan.drive(0, s, pin, od=(s in od))
    for m in range(NSM):
        for i in range(NIN):
            plan.read(m, i, 0)
    plan.host_port(dout_pin=HOST_DOUT, stb_pin=HOST_STB, din_pin=HOST_DIN)
    sel, nsel = plan.chain([core.p] + [None] * (NSM - 1))

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    dut.uio_in.value = 0
    await shift_ctl(dut, 1, config_word(core), CFG_BITS)
    padded = list(words) + [0] * (STT_ROWS - len(words))
    bits = 0
    for i, w in enumerate(padded):
        bits |= w << (32 * i)
    await shift_ctl(dut, 0, bits, 32 * len(padded))
    await shift_ctl(dut, 2, sel, nsel)
    dut._log.info(f"{name}: loaded, {len(words)} rows, slots->pins {pin_of}")

    # ---- measure ---------------------------------------------------------
    # For every pin transition, how long after the preceding clock edge did it
    # happen? That is the clock-to-output delay; the skew between two pins is
    # the difference of theirs.
    last_clk = [0]
    samples = {s: [] for s in range(nslots)}

    async def watch_clk():
        while True:
            await RisingEdge(dut.clk)
            last_clk[0] = get_sim_time("ps")

    def pin_handle(pin):
        return (dut.uo_out, pin) if pin < 8 else (dut.uio_out, pin - 8)

    async def watch_pin(slot):
        sig, bit = pin_handle(pin_of[slot])
        prev = None
        while True:
            await Edge(sig)
            if not sig.value.is_resolvable:
                continue
            v = (int(sig.value) >> bit) & 1
            if prev is not None and v != prev:
                d = get_sim_time("ps") - last_clk[0]
                if 0 < d < PERIOD_NS * 1000:
                    samples[slot].append(d)
            prev = v

    cocotb.start_soon(watch_clk())
    for s in range(nslots):
        cocotb.start_soon(watch_pin(s))

    async def feed():
        payload = [0xA5, 0x3C, 0x5A, 0xC3, 0x0F, 0xF0, 0x55, 0xAA]
        i = 0
        while True:
            await host_frame(dut, 0, 1, payload[i % len(payload)])
            i += 1
            for _ in range(40):
                await RisingEdge(dut.clk)

    cocotb.start_soon(feed())
    for _ in range(cycles):
        await RisingEdge(dut.clk)

    # ---- report ----------------------------------------------------------
    dut._log.info(f"RESULT program={name} corner={os.environ.get('CORNER','?')}")
    stats = {}
    for s in range(nslots):
        v = sorted(samples[s])
        nm = core.slots[s][0]
        if not v:
            dut._log.info(f"RESULT   slot{s} {nm:5s} pin{pin_of[s]:<2d} NO TRANSITIONS")
            continue
        real = [x / SCALE for x in v]          # scaled ps -> real ps
        stats[s] = (nm, real)
        dut._log.info(
            f"RESULT   slot{s} {nm:5s} pin{pin_of[s]:<2d} n={len(real):<4d} "
            f"clk->pin min={min(real):.1f}ps med={real[len(real)//2]:.1f}ps "
            f"max={max(real):.1f}ps")
    for a in stats:
        for b in stats:
            if a < b:
                na, va = stats[a]
                nb, vb = stats[b]
                med = va[len(va)//2] - vb[len(vb)//2]
                dut._log.info(
                    f"RESULT   SKEW {na} vs {nb}: median {med:+.1f} ps, "
                    f"worst {max(va)-min(vb):+.1f} / {min(va)-max(vb):+.1f} ps")
    assert stats, "no pin transitions recorded at all"
    for s, (nm, v) in stats.items():
        assert max(v) > 0, (
            f"{nm}: clock-to-output delay measured as zero, which is impossible "
            f"-- the instrument is quantizing, not the design being perfect")
