# USB LS receive: what the ISA can and cannot express

Written before any USB RX program, because the design question turned out to
be answerable from the instruction set rather than from a row count. The
conclusion is a blocker, so it is stated first and the evidence follows.

## The blocker: a computed bit cannot enter the shift register

**Every bit that enters `sr` comes from one of five places, and none of them
is a value the program worked out.** The `sr` action group has eight codes
(§6, the group is full at 8 of 8) and only one of them introduces a new bit:

| code | what it puts in `sr` |
|---|---|
| `load` | a byte popped from the TX FIFO |
| `loadk` | the configured constant K |
| `loadcrc` | the complement of the CRC register |
| `clr` | zero |
| `shift` | **the fill bit** |
| `clr`,`shift` | zero, then the fill bit |
| `push` | nothing — it reads |

And the fill bit is **configuration, not a row field**: §2 gives `fill` as
"constant 0, constant 1, or synchronized input 0", a 2-bit per-machine value
fixed at load time. In the RTL this is the whole of it —

```
wire fill_bit = (cfg_fill == 2'd0) ? 1'b0
              : (cfg_fill == 2'd1) ? 1'b1
                                   : in_s[0];
```

— and `in_s[0]` is the only path from any pin into data anywhere in
`stt_core.v`. Every other use of an input is a *test* (`in0h`, `in0l`,
`in1h`, `in1l`), which steers control flow and cannot deposit a value.

### Why that stops USB receive specifically

USB is NRZI: a transmitted **0** is a transition and a **1** is no
transition, so

> decoded bit = NOT (current D+ XOR previous D+)

which is a function of two samples. It is not any pin's level at any instant,
so it cannot be the fill bit, so it cannot enter `sr`.

It has to enter `sr`, for two independent reasons:

1. the token's fields (PID, address, endpoint) are assembled there and pushed
   from there;
2. **`crcstep` CRCs the shift register, not the pin.** In `stt_core.v` the
   CRC input is `srbit_mid`, the shift register's serial bit after the loads.
   So a CRC5 check over the decoded stream requires the decoded stream to be
   in `sr` first.

Putting the *raw* NRZI stream in `sr` with `fill = in0` does not help. The
transmitter computes CRC5 over the decoded data — `crcstep` runs in the bit
loop on `sr`, and NRZI is applied afterwards by the `tgl` pin op — so a CRC
taken over raw line states is a CRC of a different message.

## The bit stuffer does not apply here, and is not needed

The task asked whether USB destuffing should use the §9 `bit_stuffer` the way
CAN does. It cannot, and it does not need to.

**It cannot: the unit is transmit-only.** It lives entirely in step 4, the pin
operation. `stall_mid` gates `emit`, and the run counter advances on what was
*emitted*. §4's table defines the `stall` test as "true while the bit stuffer
will insert a bit rather than accept one, so the program can hold the shift
register" — that is a statement about an output. There is no path by which a
received bit is examined or dropped by the unit.

**It does not need to.** CAN's destuffing is expensive because its rule is
*any* identical run, so a receiver must track the polarity of the run as well
as its length, and that is what costs 36 rows of control flow
(`docs/writeup.md` §3). USB's rule is a run of **ones only**, after NRZI
decoding. A run of ones is a countdown: the existing `usb_ls_token_tx` already
does exactly this on the transmit side with `c2load = 6`, `c2dec` and the
`c2z` test, in four rows and without the unit. The receiver can use the same
three codes.

So USB RX would be the first hardware exercise of the **pair slot** and
**NRZI**, but not of `bit_stuffer` — and `crc_lfsr16` is not involved either,
since the token uses the 5-bit per-machine CRC, not the wide one. Both of
those units remain untested on hardware.

## This is not a row-count problem

Worth separating, because the task asked for a row count against the ceiling.
The 32-row ceiling is not what blocks this. A sketch that assembles fields,
counts a run of ones, checks CRC5 and detects SE0 is comfortably inside 32
rows; the NRZI state itself costs a duplicated sample step, which is a handful
of rows. **No row budget helps, because the operation needed does not exist at
any budget.**

## Three ways forward

| | what it costs | what it changes |
|---|---|---|
| **A. Give `fill` a fourth source** | `fill` is 2 bits with **code 3 already unassigned** (§2, §16.1), so the encoding has room and the frozen row format does not move | a SPEC change, and a real one: it has to be a source that makes the decoded bit available. "Last test result" does **not** work — actions only run when the test passed, so that source is always 1 |
| **B. Two machines** | machine A decodes NRZI and re-emits NRZ on a pin; machine B receives it with `fill = in0`. Two programs, two extra pins, and B must be phase-locked to A | no spec change; costs a machine and pins |
| **C. Self-loopback of one pin** | one machine drives the decoded bit on an output pin and reads it back into `in0` through the §8.3 synchronizer, then shifts it in | no spec change, one machine, but the capability then **requires an external wire** on the real ASIC, which is a constraint worth stating plainly rather than burying |

C is the cheapest and needs nothing new, and on the FPGA the internal
loopback route already built for the UART test makes the wire free. Its
honesty cost is that "this chip can receive USB" would carry a footnote: *with
one pin strapped back to an input*.

A is the only one that leaves the ISA able to express NRZI receive on its own,
and the free `fill` code is the natural place for it — but what that fourth
source should be is a design decision, not a transcription, and it is a change
to a normative document.

---

# The receiver, as built

Written against the self-loopback route. **24 rows of 32**, working at bit
periods **9 to 32 cycles with no gaps**, verified by
`isa_bench/usb_rx_check.py` (`make check-usb-rx`, inside `make check`).

The stimulus is the reference transmitter itself — `stt_usb_1pin` drives dp/dm
and `stt_usb_rx` reads dp, machine to machine in one `World`, exactly as the
FPGA wires them. Nothing is a hand-built waveform, so a decoder that agrees
here agrees with the program that already passes its own benchmark. All four
`run_usb` packets decode, including `(0x69, 0x7FF)`, whose all-ones field is
what forces bit stuffing.

| received | field |
|---|---|
| byte 0 | SYNC, `0x80` |
| byte 1 | PID |
| byte 2 | ADDR and the low bit of ENDP |
| byte 3 | the top three bits of ENDP, then CRC5 |

## Three things it cannot do, and why

**It does not check CRC5 itself.** The ISA has no test that reads the CRC
register — the test codes are `always`, `c2z`, `cz`, `fifo`, `in0h`, `in0l`,
`in1h`, `in1l`, `srbit`, `tmr`, `stall`. `loadcrc` moves the CRC into the
shift register where five `srbit` tests could walk it, but that is ten-odd
rows to reach a verdict the host gets for free from byte 3. The CRC arrives as
data and is checked by the caller.

**It cannot see SE0.** End of packet is both halves low, and the receiver has
two inputs with both spent: one on D+, one on the decoded-bit loopback that
NRZI needs. So D− is invisible and SE0 cannot be told from a differential 0.

**Which means it needs an idle gap between packets.** It ends a packet by
noticing the line has gone idle, read as a run of ones longer than stuffing
permits — seven. The transmitter emits SE0, SE0, J and then starts the next
packet immediately, so back to back there is **one** idle bit and the run
never builds; the receiver runs the two packets together. `IDLE_BITS = 12` in
the checker is the gap a host must leave. Any real host leaves far more, but
it is a requirement of this receiver and not of USB, so it is stated rather
than assumed.

## What it costs, structurally

Half the program is the line-state duplication: NRZI decodes against the
previous line state, and the row pointer is the only place to keep one bit, so
the sample/drive/shift machinery exists twice, once for J and once for K. That
is eleven rows per copy.

Three of those rows per copy are slack — `V`, `W`, `X` — doing nothing but
waiting for the decoded bit to come back through the §8.3 synchronizer before
`shift` takes it. **That is the price of the loopback showing up as rows**, and
it is also what puts the floor at nine cycles per bit.

Destuffing is four codes and no extra rows, using the `c2` countdown the
transmitter already uses: `c2load = 6`, `c2dec` on each decoded 1, `c2z` to
find the stuffed cell. The §9 `bit_stuffer` is not involved, for the reasons
above — so this program is **not** a first exercise of that unit, and not of
`crc_lfsr16` either.
