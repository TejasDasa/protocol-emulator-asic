"""The lockstep loop itself, shared by the reference-program test and the
mutation test.

Extracted so both drive the RTL through exactly the same sequence: a difference
between how the two tests clock the design would make the mutation results
incomparable with the reference results.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cocotb.triggers import RisingEdge, Timer

from lockstep import CFG_BITS, config_word

PERIOD_NS = 10
FIELDS = ("row", "link", "sr", "cnt", "c2", "crc", "tcount", "pinv")


class Divergence(AssertionError):
    pass


def i_(sig, name=None):
    """Read a signal, and treat X or Z as a failure rather than an exception.

    A random program once produced an X here and the caller logged it as "model
    raised ... not comparable, skipped". An X in the DUT is a bug, not an
    uncomparable case, so it must fail by name instead of being skipped.
    """
    v = sig.value
    try:
        return int(v)
    except ValueError:
        raise Divergence(f"RTL signal {name or sig._name} is not 0/1: {v!r}")


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


async def reset_and_load(dut, core, words, w):
    """Reset the DUT, then load the configuration and the program."""
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
    # level throughout the host's load sequence, which is hundreds of cycles.
    w.resolve()
    idle = 0
    for i, netname in enumerate(core.ins):
        idle |= (w.nets[netname].value & 1) << i
    dut.pin_in.value = idle

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

    # en high, but do NOT clock here: the first edge the machine sees must be
    # the one inside the loop, so that RTL cycle 0 is model cycle 0.
    dut.en.value = 1
    await settle(dut)


async def run_lockstep(dut, core, w, done, max_cycles, label, nslots, words, cov=None):
    """Step the model and the RTL together, comparing every cycle.

    Returns (cycles, finished). Raises Divergence on the first mismatch.
    """
    w.resolve()
    cycles = 0
    finished = False

    for t in range(max_cycles):
        w.t = t
        for d in w.devices:
            d.step(w)
        w.resolve()

        tx_ne = 1 if w.tx_fifo else 0
        dut.tx_ne.value = tx_ne
        dut.tx_data.value = (w.tx_fifo[0] & 0xFF) if w.tx_fifo else 0
        rx_before = len(w.rx_fifo)
        tx_before = len(w.tx_fifo)

        # Combinational outputs are valid now, before the edge ending the cycle.
        await settle(dut)
        executed = i_(dut.dbg_row, "dbg_row")
        if cov is not None:
            cov.record(words[executed])
        # Snapshot the internals that decide THIS cycle, before the edge. Reading
        # them in the failure handler instead would show the next cycle's values.
        pre = {n: repr(getattr(dut.u_core, n).value) for n in
               ("test_pass", "sr", "sr_next", "sr_mid", "srbit_pre", "f_test",
                "a_sr", "crc", "row")}
        rtl_tx_pop = i_(dut.tx_pop, "tx_pop")
        rtl_rx_push = i_(dut.rx_push, "rx_push")
        rtl_rx_data = i_(dut.rx_data, "rx_data")

        core.step(w)
        w.resolve()
        for nname, n in w.nets.items():
            w.history[nname].append(n.value)

        # SPEC section 8.3: a value on the pin at the end of cycle N is first
        # visible to a test in cycle N+2. Driving it here, before the edge that
        # ends cycle N, lands it in the first synchronizer flop at that edge.
        pin_in = 0
        for i, netname in enumerate(core.ins):
            pin_in |= (w.nets[netname].value & 1) << i
        dut.pin_in.value = pin_in

        await RisingEdge(dut.clk)
        # Sample after the edge has settled: reading immediately after
        # RisingEdge returns pre-update values for nonblocking assignments.
        await settle(dut)
        cycles = t + 1

        try:
            rtl = dict(row=i_(dut.dbg_row, "dbg_row"), link=i_(dut.dbg_link, "dbg_link"),
                       sr=i_(dut.dbg_sr, "dbg_sr"), cnt=i_(dut.dbg_cnt, "dbg_cnt"),
                       c2=i_(dut.dbg_c2, "dbg_c2"), crc=i_(dut.dbg_crc, "dbg_crc"),
                   tcount=i_(dut.dbg_tcount, "dbg_tcount"),
                   pinv=i_(dut.dbg_pinv, "dbg_pinv"))
        except Divergence as d:
            raise Divergence(
                f"{label}: cycle {t}: {d}\n"
                f"  row just executed: addr {executed}, word 0x{words[executed]:08x}\n"
                f"  model state: sr=0x{core.sr:02x} crc=0x{core.crc:02x} "
                f"cnt={core.cnt} c2={core.c2} tcount={core.tcount}\n"
                f"  config: shift={core.shift} fill={core.fill} w={core.w} "
                f"P={core.P}\n"
                f"  config: cfg_sr_width={dut.u_core.cfg_sr_width.value!r} "
                f"sr_mask={dut.u_core.sr_mask.value!r}\n"
                f"    PRE-EDGE (the values that decided this cycle):\n"
                + "".join(f"      {k}={v}\n" for k, v in pre.items()))
        mdl = dict(row=core.row, link=core.link, sr=core.sr, cnt=core.cnt,
                   c2=core.c2, crc=core.crc, tcount=core.tcount,
                   pinv=sum((b & 1) << i for i, b in enumerate(core.pinv)))
        rtl["pinv"] &= (1 << nslots) - 1 if nslots else 0

        for f in FIELDS:
            if rtl[f] != mdl[f]:
                raise Divergence(
                    f"{label}: cycle {t}: {f} differs -- RTL {rtl[f]} "
                    f"(0x{rtl[f]:x}) vs model {mdl[f]} (0x{mdl[f]:x})\n"
                    f"  full RTL   {rtl}\n  full model {mdl}\n"
                    f"  RTL row word 0x{i_(dut.row):08x} at addr {executed}, "
                    f"expected 0x{words[executed]:08x}\n"
                    f"  tx_ne={tx_ne} tx_pop={rtl_tx_pop} rx_push={rtl_rx_push}")

        popped = tx_before - len(w.tx_fifo)
        pushed = len(w.rx_fifo) - rx_before
        if rtl_tx_pop != popped:
            raise Divergence(f"{label}: cycle {t}: tx_pop {rtl_tx_pop} vs model {popped}")
        if rtl_rx_push != pushed:
            raise Divergence(f"{label}: cycle {t}: rx_push {rtl_rx_push} vs model {pushed}")
        if pushed and rtl_rx_data != (w.rx_fifo[-1] & 0xFF):
            raise Divergence(f"{label}: cycle {t}: rx_data 0x{rtl_rx_data:02x} vs "
                             f"model 0x{w.rx_fifo[-1] & 0xFF:02x}")

        if done(w):
            finished = True
            break

    return cycles, finished
