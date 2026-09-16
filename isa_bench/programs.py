"""All benchmark programs. Each builder takes the timing parameter and returns (core, program).
Builders raise ValueError when a program cannot meet the requested timing."""
from pio import assemble as pio_asm, PioSM
from stt import Row, SttProgram, SttCore
from rm import assemble as rm_asm, RmCore


def pio_divider(total, lo, hi, step=1):
    """Pick the smallest clock divider D so total/D is an integer in [lo, hi]."""
    for d in range(1, total + 1):
        if total % d == 0 and lo <= total // d <= hi and (total // d) % step == 0:
            return d, total // d
    raise ValueError(f"no divider for {total}")


# =================================================================== UART TX
PIO_UART_TX = """
        pull        side 1 [P1-1]   ; stop bit / idle, wait for a byte
        set x, 7    side 0 [P1-1]   ; start bit
bitloop:
        out pins, 1                  ; data bit
        jmp x-- bitloop [P1-2]
"""


def pio_uart_tx(P):
    d, p1 = pio_divider(P, 2, 8)
    prog = pio_asm(PIO_UART_TX, side_set=1, side_opt=True, P1=p1)
    return PioSM(prog, ["tx"], divider=d, init_values=1, init_dirs=1), prog


def stt_uart_tx(P):
    prog = SttProgram([
        Row("IDLE", "fifo", "START", pins={0: "lo"}, act=["load", "cload", "trst"]),
        Row("START", "tmr", "DATA", pins={0: "sr"}),
        Row("DATA", "tmr", "CHECK", pins={0: "sr"}, act=["shift", "cdec"]),
        Row("CHECK", "cz", "STOP", "DATA"),
        Row("STOP", "tmr", "IDLE"),
    ])
    core = SttCore(prog, slots=[("tx", "pp")], period=P, shift="right", fill="1")
    return core, prog


RM_UART_TX = """
idle:   JFE idle
        POP r0
        PIN 0           ; C = 1 (line is idle high); becomes the stop bit
        TRST 0
        WAIT
        LDI r1, 9       ; 8 data bits + stop bit
        PCLR 0          ; start bit, 2 cycles after the tick
loop:   WAIT
        RCR r0          ; C = next bit, old C enters at the top
        POUT 0          ; 2 cycles after the tick
        DEC r1
        JNZ loop
        WAIT            ; end of stop bit
        JMP idle
"""


def rm_uart_tx(P):
    prog = rm_asm(RM_UART_TX)
    return RmCore(prog, pins=[("tx", "pp")], period=P), prog


# =================================================================== UART RX
PIO_UART_RX = """
start:  wait 0 pin 0                 ; start bit edge
        set x, 7        [D1]         ; delay to the middle of bit 0
bitloop:
        in pins, 1
        jmp x-- bitloop [P1-2]
        jmp pin good                 ; stop bit high?
        wait 1 pin 0                 ; framing error: wait for idle, drop byte
        jmp start
good:   in null, 24                  ; right-justify the byte
        push
"""


def pio_uart_rx(P):
    d, p1 = pio_divider(P, 2, 22, step=2)
    prog = pio_asm(PIO_UART_RX, P1=p1, D1=3 * p1 // 2 - 2)
    return PioSM(prog, ["rx"], divider=d, jmp_pin=0, in_shift_right=True), prog


def stt_uart_rx(P):
    prog = SttProgram([
        Row("IDLE", "in0l", "MID", act=["thalf"]),
        Row("MID", "tmr", "CHKST"),
        Row("CHKST", "in0l", "BIT", "IDLE", act=["cload"]),
        Row("BIT", "tmr", "CNT", act=["shift", "cdec"]),
        Row("CNT", "cz", "STOP", "BIT"),
        Row("STOP", "tmr", "STOPCK"),
        Row("STOPCK", "in0h", "IDLE", "BAD", act=["push"]),
        Row("BAD", "in0h", "IDLE"),
    ])
    core = SttCore(prog, slots=[], ins=["rx"], period=P, shift="right", fill="in0")
    return core, prog


RM_UART_RX = """
idle:   JPH 0, idle
        TRST 1          ; half period
        WAIT            ; middle of start bit
        JPH 0, idle     ; glitch, not a start bit
        LDI r1, 8
bit:    WAIT
        PIN 0
        RCR r0
        DEC r1
        JNZ bit
        WAIT            ; middle of stop bit
        JPL 0, bad
        PUSH r0
        JMP idle
bad:    JPL 0, bad      ; framing error: wait for idle
        JMP idle
"""


def rm_uart_rx(P):
    prog = rm_asm(RM_UART_RX)
    return RmCore(prog, pins=[("rx", "in")], period=P), prog


# =================================================================== SPI master
# pins: 0 MOSI, 1 SCK, 2 CS, 3 MISO.  P = cycles per bit = 2 * half period.
PIO_SPI = """
idle:   pull            side 2           ; CS high, wait for data
        nop             side 0 [H1-1]    ; CS low
byte:   out null, 24    side 0           ; left-justify the byte (MSB first)
        set x, 7        side 0
bit:    out pins, 1     side 0 [H1-1]    ; MOSI, SCK low
        in pins, 1      side 1 [H1-2]    ; SCK high, sample MISO
        jmp x-- bit     side 1
        push            side 0
        mov y, ~status  side 0           ; y = 0 if TX FIFO empty
        jmp !y idle     side 0
        pull            side 0
        jmp byte        side 0
"""


def pio_spi(P):
    if P % 2:
        raise ValueError("odd")
    d, h1 = pio_divider(P // 2, 2, 8)
    prog = pio_asm(PIO_SPI, side_set=2, H1=h1)
    sm = PioSM(prog, ["mosi", "sck", "cs", "miso"], in_base=3, out_base=0, side_base=1,
               out_shift_right=False, in_shift_right=False, divider=d,
               init_values=0b100, init_dirs=0b111)
    return sm, prog


def stt_spi(P):
    if P % 2:
        raise ValueError("odd")
    prog = SttProgram([
        Row("IDLE", "fifo", "RISE", pins={2: "lo", 0: "sr"}, act=["load", "cload", "trst"]),
        Row("RISE", "tmr", "FALL", pins={1: "hi"}, act=["shift", "cdec"]),
        Row("FALL", "tmr", "CNT", pins={1: "lo", 0: "sr"}),
        Row("CNT", "cz", "MORE", "RISE", act=["push"]),
        Row("MORE", "fifo", "RISE", "END", pins={0: "sr"}, act=["load", "cload"]),
        Row("END", "tmr", "IDLE", pins={2: "hi"}),
    ])
    core = SttCore(prog, slots=[("mosi", "pp"), ("sck", "pp"), ("cs", "pp")], ins=["miso"],
                   period=P // 2, shift="left", fill="in0", init_pins=[0, 0, 1])
    return core, prog


RM_SPI = """
idle:   JFE idle
        PCLR 2          ; CS low
        TRST 0
next:   POP r0
        LDI r1, 8
bit:    SHL r0
        POUT 0          ; MOSI
        WAIT
        PSET 1          ; SCK rise
        PIN 3           ; sample MISO
        RCL r2
        WAIT
        PCLR 1          ; SCK fall
        DEC r1
        JNZ bit
        PUSH r2
        JFE done
        JMP next
done:   WAIT
        PSET 2          ; CS high
        JMP idle
"""


def rm_spi(P):
    if P % 2:
        raise ValueError("odd")
    prog = rm_asm(RM_SPI)
    core = RmCore(prog, pins=[("mosi", "pp"), ("sck", "pp"), ("cs", "pp"), ("miso", "in")],
                  period=P // 2, init_pins=[0, 0, 1, 0])
    return core, prog


# =================================================================== I2C master
# pins: 0 SDA, 1 SCL (open drain).  P = nominal cycles per bit = 4 * quarter period.
# Host pushes [addr<<1, data...]; core pushes one status byte: 0 = all ACKed.
PIO_I2C = """
idle:   pull
        set pindirs, 1        [2*Q1-1]  ; START: SDA low, SCL high
        nop            side 1 [Q1-1]    ; SCL low
byte:   out null, 24                    ; left-justify
        mov osr, ~osr                   ; pindir = 1 pulls low, so invert the data
        set x, 7
bit:    out pindirs, 1        [Q1-1]    ; SDA = data bit
        nop            side 0           ; release SCL
        wait 1 pin 1          [2*Q1-1]  ; clock stretching, then hold high
        jmp x-- bit    side 1 [Q1-1]    ; SCL low
        set pindirs, 0        [Q1-1]    ; release SDA for ACK
        nop            side 0
        wait 1 pin 1          [Q1-1]
        jmp pin nack                    ; SDA high = NACK
        mov y, ~status side 1 [Q1-1]    ; SCL low; y = 0 if FIFO empty
        jmp !y stop
        pull
        jmp byte
nack:   set x, 0       side 1 [Q1-1]    ; SCL low; status will be ~0
drain:  mov y, ~status                  ; discard the rest of the transaction
        jmp !y stop
        pull
        jmp drain
stop:   set pindirs, 1        [Q1-1]    ; SDA low
        nop            side 0           ; release SCL
        wait 1 pin 1          [Q1-1]
        set pindirs, 0        [Q1-1]    ; SDA rises: STOP
        mov isr, ~x                     ; 0 after ACK path (x = ~0), ~0 after NACK
        push
"""


def pio_i2c(P):
    if P % 4:
        raise ValueError("P not multiple of 4")
    d, q1 = pio_divider(P // 4, 1, 4)
    prog = pio_asm(PIO_I2C, side_set=1, side_opt=True, side_pindirs=True, Q1=q1)
    sm = PioSM(prog, ["sda", "scl"], in_base=0, out_base=0, set_base=0, set_count=1,
               side_base=1, jmp_pin=0, out_shift_right=False, divider=d,
               init_values=0, init_dirs=0)
    return sm, prog


def stt_i2c(P):
    if P % 4:
        raise ValueError("P not multiple of 4")
    R = Row
    prog = SttProgram([
        R("IDLE", "fifo", "S1", pins={0: "lo"}, act=["load", "cload", "trst"]),
        R("S1", "tmr", "B0", pins={1: "lo"}),
        R("B0", "tmr", "B1", pins={0: "sr"}),
        R("B1", "tmr", "B2", pins={1: "hi"}),
        R("B2", "in1h", "B3", act=["trst"]),
        R("B3", "tmr", "B4", pins={1: "lo"}, act=["shift", "cdec"]),
        R("B4", "cz", "A0", "B0"),
        R("A0", "tmr", "A1", pins={0: "hi"}),
        R("A1", "tmr", "A2", pins={1: "hi"}),
        R("A2", "in1h", "A3", act=["trst"]),
        R("A3", "tmr", "A4"),
        R("A4", "in0l", "A5", "N1", act=["clr"]),
        R("A5", "tmr", "A6", pins={1: "lo"}),
        R("A6", "fifo", "B0", "P0", act=["load", "cload"]),
        R("N1", "tmr", "N2", pins={1: "lo"}),
        R("N2", "fifo", "N2", "N3", act=["load"]),
        R("N3", "always", "P0", act=["clr", "shift"]),
        R("P0", "tmr", "P1", pins={0: "lo"}),
        R("P1", "tmr", "P2", pins={1: "hi"}),
        R("P2", "in1h", "P3", act=["trst"]),
        R("P3", "tmr", "P4", pins={0: "hi"}),
        R("P4", "always", "IDLE", act=["push"]),
    ])
    core = SttCore(prog, slots=[("sda", "od"), ("scl", "od")], ins=["sda", "scl"],
                   period=P // 4, shift="left", fill="in0")
    return core, prog


RM_I2C = """
idle:   JFE idle
        LDI r2, 0
        TRST 0
        PCLR 0          ; START
        WAIT
        PCLR 1          ; SCL low
next:   POP r0
        LDI r1, 8
bit:    WAIT
        SHL r0
        POUT 0          ; SDA = bit
        WAIT
        CALL pulse
        PCLR 1
        DEC r1
        JNZ bit
        WAIT
        PSET 0          ; release SDA for ACK
        WAIT
        CALL pulse
        PIN 0           ; C = 1 on NACK
        RCL r2          ; r2 was 0, so Z = ACK
        PCLR 1
        JNZ drain
        JFE stop
        JMP next
drain:  JFE stop
        POP r0
        JMP drain
stop:   WAIT
        PCLR 0
        WAIT
        CALL pulse
        PSET 0          ; STOP
        PUSH r2
        JMP idle
pulse:  PSET 1          ; release SCL
hi:     JPL 1, hi       ; clock stretching
        TRST 0
        WAIT
        RET
"""


def rm_i2c(P):
    if P % 4:
        raise ValueError("P not multiple of 4")
    prog = rm_asm(RM_I2C)
    return RmCore(prog, pins=[("sda", "od"), ("scl", "od")], period=P // 4), prog


# =================================================================== USB LS token TX
# pins: 0 D+, 1 D-.  J = (0,1), K = (1,0), SE0 = (0,0).
# PIO gets a host-precomputed 32-bit word (SYNC, PID, field, CRC5): it cannot compute CRC.
PIO_USB = """
idle:   set pins, 2                 ; J
        pull
        set y, 5                    ; ones allowed before a stuffed bit
J:      jmp !osre Jd
        jmp eop [1]
Jd:     out x, 1
        jmp !x Jz
        jmp y-- Jh
        jmp Jz [P1-2]               ; sixth one: hold J, stuff a zero next slot
Jh:     jmp J [P1-5]
Jz:     set pins, 1                 ; transition to K
        set y, 5
        jmp K [P1-6]
K:      jmp !osre Kd
        jmp eop [1]
Kd:     out x, 1
        jmp !x Kz
        jmp y-- Kh
        jmp Kz [P1-2]
Kh:     jmp K [P1-5]
Kz:     set pins, 2                 ; transition to J
        set y, 5
        jmp J [P1-6]
eop:    set pins, 0 [2*P1-1]        ; SE0 for two bits
        set pins, 2 [P1-1]          ; J for one bit
"""


def pio_usb(P):
    d, p1 = pio_divider(P, 6, 16)
    prog = pio_asm(PIO_USB, P1=p1)
    sm = PioSM(prog, ["dp", "dm"], set_base=0, set_count=2, out_shift_right=True,
               divider=d, init_values=0b10, init_dirs=0b11)
    return sm, prog


def stt_usb(P):
    R = Row
    tg = {0: "tgl", 1: "tgl"}
    prog = SttProgram([
        R("I0", "fifo", "I1", act=["loadk", "cload", "c2load", "trst"]),
        R("I1", "always", "L0", "I2", act=["call"]),                       # SYNC
        R("I2", "always", "L0", "I3", act=["load", "cload", "call"]),      # PID
        R("I3", "always", "L0", "I4", act=["crcrst", "load", "cload", "call"]),
        R("I4", "always", "L0", "I5", act=["load", "cload_b", "call"]),    # 3 more bits
        R("I5", "always", "L0", "I6", act=["loadcrc", "cload_c", "call"]), # CRC5
        R("I6", "tmr", "I7", pins={0: "lo", 1: "lo"}),                     # SE0
        R("I7", "tmr", "I8"),
        R("I8", "tmr", "I0", pins={0: "lo", 1: "hi"}),                     # J
        # bit loop, called for each field
        R("L0", "srbit", "L1", "LZ", act=["c2dec"]),
        R("L1", "c2z", "LS", "LH"),
        R("LH", "tmr", "L6", act=["crcstep", "shift", "cdec"]),
        R("LZ", "tmr", "L6", pins=tg, act=["crcstep", "shift", "cdec", "c2load"]),
        R("LS", "tmr", "LS2", act=["crcstep", "shift", "cdec"]),
        R("LS2", "tmr", "L6", pins=tg, act=["c2load"]),
        R("L6", "cz", "ret", "L0"),
    ])
    core = SttCore(prog, slots=[("dp", "pp"), ("dm", "pp")], period=P, shift="right",
                   fill="0", cload=(8, 3, 5), c2load=6, loadk=0x80, init_pins=[0, 1])
    return core, prog


RM_USB = """
idle:   JFE idle
        LDI r3, 6       ; ones allowed before stuffing
        LDI r0, 0x80    ; SYNC
        LDI r1, 8
        TRST 0
        CALL send
        POP r0          ; PID
        LDI r1, 8
        CALL send
        LDI r2, 0x1F    ; CRC starts here
        POP r0
        LDI r1, 8
        CALL send
        POP r0
        LDI r1, 3
        CALL send
        MOV r0, r2
        XORI r0, 0x1F
        LDI r1, 5
        CALL send
        WAIT
        NOP
        NOP
        PORT 3, 0       ; SE0
        WAIT
        WAIT
        NOP
        NOP
        PORT 3, 2       ; J
        JMP idle
send:   SHR r0          ; C = bit
        JNC zero
        SHR r2          ; bit 1: CRC update
        JC one1
        XORI r2, 0x14
one1:   WAIT            ; hold level
        DEC r3
        JNZ next
        JMP stuff       ; sixth one: stuffed zero next tick
zero:   SHR r2          ; bit 0: CRC update
        JNC stuff
        XORI r2, 0x14
stuff:  WAIT
        PIN 0           ; C = D+ (1 means currently K)
        JC toJ
        PORT 3, 1       ; K
        JMP rst
toJ:    PORT 3, 2       ; J
rst:    LDI r3, 6
next:   DEC r1
        JNZ send
        RET
"""


def rm_usb(P):
    prog = rm_asm(RM_USB)
    return RmCore(prog, pins=[("dp", "pp"), ("dm", "pp")], period=P, init_pins=[0, 1]), prog


# ---- single-pin-op variants (at most one pin field per row; "pair" = slots 0 and 1)
def stt_spi_1pin(P):
    if P % 2:
        raise ValueError("odd")
    prog = SttProgram([
        Row("IDLE", "fifo", "IDLE2", pins={2: "lo"}, act=["load", "cload", "trst"]),
        Row("IDLE2", "always", "RISE", pins={0: "sr"}),
        Row("RISE", "tmr", "FALL", pins={1: "hi"}, act=["shift", "cdec"]),
        Row("FALL", "tmr", "FALL2", pins={1: "lo"}),
        Row("FALL2", "always", "CNT", pins={0: "sr"}),
        Row("CNT", "cz", "MORE", "RISE", act=["push"]),
        Row("MORE", "fifo", "RISE", "END", pins={0: "sr"}, act=["load", "cload"]),
        Row("END", "tmr", "IDLE", pins={2: "hi"}),
    ])
    core = SttCore(prog, slots=[("mosi", "pp"), ("sck", "pp"), ("cs", "pp")], ins=["miso"],
                   period=P // 2, shift="left", fill="in0", init_pins=[0, 0, 1])
    return core, prog


def stt_usb_1pin(P):
    core, prog = stt_usb(P)
    rows = []
    for r in prog.rows:
        pins = r.pins
        if pins == {0: "tgl", 1: "tgl"}:
            pins = {"pair": "tgl"}
        elif pins == {0: "lo", 1: "lo"}:
            pins = {"pair": "lo"}
        elif pins == {0: "lo", 1: "hi"}:
            pins = {"pair": "d0"}
        rows.append(Row(r.name, r.test, r.t, r.f, pins=pins, act=r.act))
    prog = SttProgram(rows)
    core.p = prog
    return core, prog


STT_1PIN = {"uart_tx": stt_uart_tx, "uart_rx": stt_uart_rx, "spi": stt_spi_1pin,
            "i2c": stt_i2c, "usb": stt_usb_1pin}


BUILDERS = {
    "PIO": {"uart_tx": pio_uart_tx, "uart_rx": pio_uart_rx, "spi": pio_spi,
            "i2c": pio_i2c, "usb": pio_usb},
    "STT": {"uart_tx": stt_uart_tx, "uart_rx": stt_uart_rx, "spi": stt_spi,
            "i2c": stt_i2c, "usb": stt_usb},
    "RM": {"uart_tx": rm_uart_tx, "uart_rx": rm_uart_rx, "spi": rm_spi,
           "i2c": rm_i2c, "usb": rm_usb},
}
