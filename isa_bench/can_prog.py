"""CAN 2.0A base-frame transmitter, and the packing the host must do for it.

This is the program the SPEC section 9 wider units exist for. Two of them are
load-bearing and neither can be emulated with the live codes (isa_bench's
limits analysis): CAN needs a CRC-15 with polynomial 0x4599, where the legacy
`crc` unit is 5 bits wide with a hard-wired 0x14; and it needs a bit stuffer,
where nothing in the live action set chains one register into another, so the
run-length tracking has no register to live in.

Frame layout on the wire, MSB first:

    SOF(1) ID(11) RTR(1) IDE(1) r0(1) DLC(4) data(8*DLC) CRC15(15)
    CRCdelim(1) ACK(1) ACKdelim(1) EOF(7) IFS(3)

Stuffing covers SOF through the end of the CRC sequence. Everything from the
CRC delimiter on is raw, which the program gets by carrying `stuffrst` on
every trailer row: it clears the run so the stuffer never reaches its
threshold.

The 19-bit header is never byte aligned -- 19 + 8*DLC is always 3 mod 8 -- so
the frame is sent as a 3-bit head (`cload_b`) followed by 2+DLC whole bytes
(`cload`). Sending the ragged part first keeps the byte loop uniform.
"""
from stt import Row, SttProgram, SttCore


def pack_frame(ident, data, rtr=0, ide=0, r0=0):
    """Pack a base frame into the bytes the host pushes: 3 bits left-aligned
    in byte 0, then whole bytes. Returns (bytes, bit_list_of_frame_body)."""
    dlc = len(data)
    assert 0 <= ident < (1 << 11), "base frames carry an 11-bit identifier"
    assert dlc <= 8, "DLC is four bits and caps at 8 bytes"
    bits = [0]                                             # SOF, dominant
    bits += [(ident >> (10 - k)) & 1 for k in range(11)]
    bits += [rtr, ide, r0]
    bits += [(dlc >> (3 - k)) & 1 for k in range(4)]
    for byte in data:
        bits += [(byte >> (7 - k)) & 1 for k in range(8)]
    assert len(bits) == 19 + 8 * dlc
    head = bits[:3]
    out = [sum(b << (7 - i) for i, b in enumerate(head))]  # left-aligned
    rest = bits[3:]
    assert len(rest) % 8 == 0
    for j in range(0, len(rest), 8):
        out.append(sum(b << (7 - k) for k, b in enumerate(rest[j:j + 8])))
    return out, bits


def stt_can_tx(P, dlc=1):
    """One state machine, one open-drain pin. `dlc` fixes the frame length,
    because c2 reloads from a single configured constant."""
    prog = SttProgram([
        # -------- arm. Two resets, because crc16rst and stuffrst are both in
        # the `xx` group and cannot share a row.
        Row("IDLE",   "fifo",   "RST1"),
        Row("RST1",   "always", "RST2",   act=["crc16rst", "c2load"]),
        Row("RST2",   "always", "LOAD",   act=["stuffrst", "trst"]),
        Row("LOAD",   "always", "BITW",   act=["load", "cload_b"]),

        # -------- header + data. `stall` asks the stuffer whether this bit
        # period belongs to it; if so the row emits without consuming one.
        Row("BITW",   "tmr",    "SCK"),
        Row("SCK",    "stall",  "STUF",   "SEND"),
        Row("STUF",   "always", "BITW",   pins={0: "hi"}),
        # crc16step sees sr before `shift` and the pin sees it after (SPEC
        # 8.2), so the shift has to sit on its own row or the CRC would
        # cover a different bit than the one on the wire.
        Row("SEND",   "always", "ADV",    pins={0: "sr"},
            act=["crc16step", "cdec"]),
        Row("ADV",    "always", "CCK",    act=["shift"]),
        Row("CCK",    "cz",     "BYTEC",  "BITW"),
        Row("BYTEC",  "always", "BYTZ",   act=["c2dec"]),
        Row("BYTZ",   "c2z",    "CRCPH",  "RELOAD"),
        Row("RELOAD", "always", "BITW",   act=["load", "cload"]),

        # -------- CRC sequence: still stuffed, shifted out of the wide unit.
        Row("CRCPH",  "always", "CBW",    act=["cload_c"]),
        Row("CBW",    "tmr",    "CSCK"),
        Row("CSCK",   "stall",  "CSTF",   "CSEND"),
        Row("CSTF",   "always", "CBW",    pins={0: "hi"}),
        Row("CSEND",  "always", "CCK2",   pins={0: "crcb"}, act=["cdec"]),
        Row("CCK2",   "cz",     "TRAIL",  "CBW"),

        # -------- delimiters, ACK slot, EOF and IFS: 15 recessive bit times,
        # covering the 13 the protocol requires. TPAD only exists to put the
        # pin write the same two cycles after the tick as everywhere else.
        Row("TRAIL",  "always", "TBW",    act=["cload_c"]),
        Row("TBW",    "tmr",    "TPAD"),
        Row("TPAD",   "always", "TSEND"),
        Row("TSEND",  "always", "TCK",    pins={0: "hi"},
            act=["stuffrst", "cdec"]),
        Row("TCK",    "cz",     "IDLE",   "TBW"),
    ])
    core = SttCore(prog, slots=[("can", "od")], period=P,
                   shift="left", fill="1",
                   cload=(8, 3, 15), c2load=dlc + 3,
                   crc16_poly=0x4599, crc16_width=15,
                   stuff_n=5, stuff_slots=(0,), init_pins=[1])
    return core, prog


def register():
    """Expose the CAN transmitter as a benchmark so the rtl2 lockstep runs it.

    The random programs cover the wider units as CODES, with random
    polynomials and stuffing thresholds. This covers them as a PROTOCOL: a
    real CRC-15 over a real frame, with the stuffer inserting real bits, run
    against the RTL cycle by cycle.
    """
    import contextlib
    import io
    from collections import deque
    with contextlib.redirect_stdout(io.StringIO()):
        import bench
        from world import World

    def _run(isa, P):
        core, prog = stt_can_tx(P, dlc=2)
        w = World([("can", 1)])
        payload, _bits = pack_frame(0x2AA, [0x0F, 0xF0])
        w.tx_fifo = deque(payload)
        w.run(core, 70 * P, lambda _w: False)
        return prog, None

    bench.BENCHES["can_tx"] = _run
