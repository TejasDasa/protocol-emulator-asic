"""cocotb test: rtl2 against SttCore, cycle by cycle, for each reference program.

Select the program with the PROG environment variable; rtl2/tb/run_tests.py
runs all six.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from lockstep import CFG_BITS, capture_benchmark, config_word, encode_rows

PERIOD_NS = 10


def _i(sig):
    return int(sig.value)


async def settle(dut):
    """Move just past the edge so the next writes are applied well before it.

    cocotb applies a .value write at the start of the next timestep, so setting
    a signal and awaiting RisingEdge in the same breath races the edge. Driving
    1 ns after an edge gives 9 ns of setup instead.
    """
    await Timer(1, unit="ns")


async def shift_in(dut, enable_sig, bits, nbits):
    """Present `nbits` of `bits` on ld_in, LSB first, one per cycle."""
    for i in range(nbits):
        enable_sig.value = 1
        dut.ld_in.value = (bits >> i) & 1
        await RisingEdge(dut.clk)
        await settle(dut)
    enable_sig.value = 0
    dut.ld_in.value = 0
    await settle(dut)


class Divergence(AssertionError):
    pass


@cocotb.test()
async def lockstep(dut):
    name = os.environ.get("PROG", "uart_tx")
    period = int(os.environ.get("BIT_PERIOD", "32"))

    stash = capture_benchmark(name, period)
    core, w, done, max_cycles = (stash["core"], stash["world"],
                                 stash["done"], stash["max_cycles"])

    # SPEC section 13 runs the models on the DECODED rows, which is what proves
    # the encoding lossless. It also means the model and the RTL index rows the
    # same way: the encoder reorders rows and may add trampolines.
    words, decoded = encode_rows(core.p)
    core.p, core.row = decoded, 0
    nslots = len(core.slots)

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())

    # ---- reset, then load configuration and program -----------------------
    dut.en.value = 0
    dut.imem_ld_en.value = 0
    dut.cfg_ld_en.value = 0
    dut.ld_in.value = 0
    dut.tx_ne.value = 0
    dut.tx_data.value = 0
    # Prime the input synchronizer with the pins' idle levels before reset.
    #
    # SPEC section 8.3 specifies a two-cycle synchronizer but not what it holds
    # before two cycles have elapsed. The model resolves that implicitly:
    # World.read_sync falls back to the net's CURRENT value while its history is
    # shorter than the synchronizer depth, i.e. it starts out already seeing the
    # idle level. Physically that is what happens -- the pins sit at their idle
    # level throughout the host's load sequence, which is hundreds of cycles, so
    # the flops are long since primed by the time the machine is enabled. Driving
    # 0 here instead would make the RTL start out seeing every input low, which
    # is how uart_rx used to take its start-bit branch on cycle 0.
    w.resolve()
    idle_in = 0
    for i, netname in enumerate(core.ins):
        idle_in |= (w.nets[netname].value & 1) << i
    dut.pin_in.value = idle_in
    dut.rst_n.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    await settle(dut)

    await shift_in(dut, dut.cfg_ld_en, config_word(core), CFG_BITS)
    prog_bits = 0
    for i, word in enumerate(words):
        prog_bits |= word << (32 * i)
    await shift_in(dut, dut.imem_ld_en, prog_bits, 32 * len(words))

    assert _i(dut.imem_ld_addr) == len(words) % 32, (
        f"write pointer is {_i(dut.imem_ld_addr)} after loading {len(words)} rows")

    # en high, but do NOT clock here: the first edge the machine sees must be the
    # one inside the loop below, so that RTL cycle 0 is model cycle 0.
    dut.en.value = 1
    await settle(dut)

    # ---- lockstep ---------------------------------------------------------
    # Mirrors World.run, with the RTL stepped alongside. The comment in
    # lockstep.py explains why the model drives the world and the RTL shadows.
    w.resolve()
    fields = ("row", "link", "sr", "cnt", "c2", "crc", "tcount", "pinv")
    cycles = 0
    finished = False

    for t in range(max_cycles):
        w.t = t
        for d in w.devices:
            d.step(w)
        w.resolve()

        # Present the host byte interface as the model will see it this cycle.
        tx_ne = 1 if w.tx_fifo else 0
        dut.tx_ne.value = tx_ne
        dut.tx_data.value = (w.tx_fifo[0] & 0xFF) if w.tx_fifo else 0
        rx_before = len(w.rx_fifo)
        tx_before = len(w.tx_fifo)

        # Combinational outputs are valid now, before the edge that ends the cycle.
        await Timer(1, unit="ns")
        executed = _i(dut.dbg_row)
        rtl_tx_pop = _i(dut.tx_pop)
        rtl_rx_push = _i(dut.rx_push)
        rtl_rx_data = _i(dut.rx_data)

        core.step(w)
        w.resolve()
        for nname, n in w.nets.items():
            w.history[nname].append(n.value)

        # SPEC section 8.3: the value on the pin at the end of cycle N is first
        # visible to a test in cycle N+2. Driving it here, before the edge that
        # ends cycle N, lands it in the first synchronizer flop at that edge and
        # makes it readable in cycle N+2 -- the same cycle read_sync returns it.
        pin_in = 0
        for i, netname in enumerate(core.ins):
            pin_in |= (w.nets[netname].value & 1) << i
        dut.pin_in.value = pin_in

        await RisingEdge(dut.clk)
        # Sample after the edge has settled: reading immediately after
        # RisingEdge returns pre-update values for nonblocking assignments.
        await settle(dut)
        cycles = t + 1

        # ---- compare the whole architectural state ------------------------
        rtl = dict(row=_i(dut.dbg_row), link=_i(dut.dbg_link), sr=_i(dut.dbg_sr),
                   cnt=_i(dut.dbg_cnt), c2=_i(dut.dbg_c2), crc=_i(dut.dbg_crc),
                   tcount=_i(dut.dbg_tcount), pinv=_i(dut.dbg_pinv))
        mdl = dict(row=core.row, link=core.link, sr=core.sr, cnt=core.cnt,
                   c2=core.c2, crc=core.crc, tcount=core.tcount,
                   pinv=sum((b & 1) << i for i, b in enumerate(core.pinv)))
        # The RTL always has 3 slots; the model has as many as the program uses.
        rtl["pinv"] &= (1 << nslots) - 1 if nslots else 0

        for f in fields:
            if rtl[f] != mdl[f]:
                raise Divergence(
                    f"{name}: cycle {t}: {f} differs -- RTL {rtl[f]} "
                    f"(0x{rtl[f]:x}) vs model {mdl[f]} (0x{mdl[f]:x})\n"
                    f"  full RTL   {rtl}\n  full model {mdl}\n"
                    f"  RTL row word 0x{_i(dut.row):08x} at addr {executed}, "
                    f"expected 0x{words[executed]:08x}\n"
                    f"  tx_ne={tx_ne} tx_pop={rtl_tx_pop} rx_push={rtl_rx_push}")

        # FIFO operations
        popped = tx_before - len(w.tx_fifo)
        pushed = len(w.rx_fifo) - rx_before
        if rtl_tx_pop != popped:
            raise Divergence(f"{name}: cycle {t}: tx_pop {rtl_tx_pop} vs model {popped}")
        if rtl_rx_push != pushed:
            raise Divergence(f"{name}: cycle {t}: rx_push {rtl_rx_push} vs model {pushed}")
        if pushed and rtl_rx_data != (w.rx_fifo[-1] & 0xFF):
            raise Divergence(f"{name}: cycle {t}: rx_data 0x{rtl_rx_data:02x} vs "
                             f"model 0x{w.rx_fifo[-1] & 0xFF:02x}")

        if done(w):
            finished = True
            break

    dut._log.info(f"{name}: {cycles} cycles in lockstep, "
                  f"{'benchmark completed' if finished else 'ran to max_cycles'}, "
                  f"{len(words)} rows, no divergence")
    assert cycles > 0, "no cycles ran"
