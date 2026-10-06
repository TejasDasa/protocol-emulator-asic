# Responding, not just initiating: the I2C target

Every protocol program in `isa_bench/` before this one either drives a bus
(I2C master, SPI master, USB token TX, UART TX) or watches one (UART RX, USB
RX). None of them had to answer anything. A test peer does: it has to ACK an
address, drive a line on the right edge, and do it inside a window somebody
else's clock defines.

This is the first program that does. The number that came out of it matters
more than the protocol, because it generalises to SPI target, USB device, and
anything else of this shape.

## 1. The answer

**Minimum response latency is 2 core clock cycles**, from an externally driven
edge to a driven output. It is exactly the input synchronizer of SPEC §8.3 and
nothing else.

Measured, not derived — `isa_bench/latency_check.py` drives an edge and reads
back the cycle the output net changed:

| rows between detecting the edge and driving | measured latency |
|---|---|
| 0 — one row tests the edge and drives | **2 cycles** |
| 1 | 3 cycles |
| 2 | 4 cycles |
| 3 | 5 cycles |

So the accounting is:

```
latency = 2  (SPEC 8.3 synchronizer)
        + N  (rows between the row that sees the edge and the row that drives)
```

with one cycle per row and no stalls. The floor is reachable because a row
tests one condition and drives a pin **in the same cycle**, so N can be 0.

### What that costs in program structure

N = 0 is only available if the decision is already made when the edge arrives.
The row that sees the eighth falling edge cannot also work out whether the
address matched — it can only act. So the comparison has to happen *during* the
address bits, and by the eighth falling edge the program is already sitting in
either the row that ACKs or the row that does not.

That is the generalisable design rule, and it is what the ISA's one-test-per-row
shape forces. Spending rows after the edge is what makes a peer late.

Confirmed on the real program, at four SCL rates
(`isa_bench/i2c_target_check.py`):

| SCL period (core cycles) | address ACK | setup before the 9th rising edge | data ACK |
|---|---|---|---|
| 8 | 2 cycles | 2 cycles | 2 cycles |
| 16 | 2 cycles | 6 cycles | 2 cycles |
| 64 | 2 cycles | 30 cycles | 2 cycles |
| 256 | 2 cycles | 126 cycles | 2 cycles |

Latency does not grow with the SCL rate. Only the margin shrinks.

## 2. The rate limit, and where it actually comes from

The ACK is not the binding constraint. Measured minimum SCL period is **8 core
cycles** (half-phase 4); 6 fails. At a half-phase of 3 the program **slips a
whole bit**: it reacts to a falling edge two cycles late, by which time the bus
has already risen again, so the next row catches the *following* edge and the
R/W bit is read out of the ACK slot.

```
max SCL = f_core / 8
```

At the 15.625 MHz the FPGA bring-up runs at, that is **1.95 MHz** — above
Fast-mode-plus. Turned around, the core clock each I2C mode needs:

| I2C mode | SCL | minimum f_core |
|---|---|---|
| Standard | 100 kHz | 0.8 MHz |
| Fast | 400 kHz | 3.2 MHz |
| Fast-mode-plus | 1 MHz | 8 MHz |

The ACK setup margin is `(half-period − 2)` core cycles. At 15.625 MHz driving
100 kHz, that is 76 cycles ≈ 4.9 µs, against the 250 ns `t_SU;DAT` the I2C
specification asks for. The deadline is met with about two orders of magnitude
to spare, which is the real answer to "can this architecture respond": for I2C,
latency was never going to be the problem, and now there is a measurement
saying so instead of an assumption.

An earlier version of the read path made the minimum period 10 rather than 8,
because it counted the remaining bits *after* the falling edge and so drove each
bit four cycles late. Moving the count into the preceding high phase — the same
trick the ACK uses — fixed it and removed a row. The binding constraint was the
read path, not the ACK.

## 3. Row budget

**30 rows written, 31 rows encoded, against the 32-row ceiling — one to spare.**

The encoded count is the one that matters and it is not the length of the
source: `rowenc.best_order` inserts a trampoline row wherever a row's two exits
cannot both be reached without one, and this program needs exactly one. The
check asserts the encoder's number, not the row list's.

## 4. What is not in it

Deliberately minimum scope: START, 7-bit address with R/W, address compare and
ACK/NACK, one data byte each way, STOP. Not implemented: multi-byte transfers,
repeated START as a distinct event, clock stretching (the target never drives
SCL — it has one open-drain slot, SDA), 10-bit addressing, general call.

STOP is handled by returning to idle rather than as a distinct detected event.
The START detector requires SDA high, then falling, then SCL still high, so a
data transition cannot trigger it and the program resynchronises after a STOP, a
NACK, or any transaction it declined. That it works is checked behaviourally:
three transactions back to back, with a foreign address in the middle, must
deliver the first and third bytes and skip the second.

## 5. Fault injection: what it would cost

The strongest argument for programs-as-peers is that a peer can be *wrong on
purpose*. A fixed UART or I2C block cannot send a bad CRC; a program can.

The cost is already known, because `isa_bench/mutlib.py` generates exactly these
edits — it is the mutation suite's corruption generator. The classes it emits
(`test`, `mode`, `target`, `act_drop`, `act_add`, `pinop`, `pinslot`) are the
same single-field changes a deliberate fault needs.

Costed below as *structure*, from the programs as written. These are **not
implemented and not measured**, except the two marked:

| malformed case | program | edit | extra rows |
|---|---|---|---|
| No ACK from the target | i2c_target | `WRA` pin op `lo` → `hold` | 0 |
| ACK a foreign address | i2c_target | `loadk` constant | 0 (config) |
| **Late ACK** | i2c_target | dead rows before the drive | 1–2 — **measured**: +1 gives 1 cycle of setup and trips the window check, +2 misses the window entirely |
| **NACK** | i2c_target | address that does not match | 0 — **measured**, it is the foreign-address case |
| Early STOP mid-byte | i2c master | retarget a bit row to `P0` | 0 |
| Short SCL pulse | i2c master | `tmr` → `always` on `B1`/`B3` | 0 |
| UART framing error | uart_tx | stop-bit pin op `hi` → `lo` | 0 |
| UART break | uart_tx | hold the line low | 0 |
| Bad USB CRC5 | usb token tx | drop one `crcstep` | 0 |
| Bit-stuff violation | usb token tx | `stuff_n` / `stuff_slots` | 0 (config) |
| Bad CAN CRC-15 | can | drop one `crcstep` | 0 |
| Clock stretching | i2c_target | a second open-drain slot for SCL, plus a row to release it | ~2 rows **and** a slot — the one case that does not come free, and this program has only 1 row spare |

So: almost every malformed case is a changed constant, pin op, or branch
target, not a bigger program. What is missing is not capability — it is a named
catalogue and the device-side checks that tell "we sent this deliberately" apart
from "we broke it". The clock-stretching case is the exception and would need
a row recovered from somewhere else.

## 6. What a passing run does not prove

`devices.I2cController` is **ours**, like every other device model here. It
checks the bus it was written to expect. Passing establishes that the target
meets the timing and the plumbing is right; it does not establish that our
reading of the I2C specification is right, and no part of this has run on
hardware. See `docs/validation.md`.
