# STT protocol emulator — instruction set specification

**Status: normative.** This document states what the chip does. It is the
single source of truth for RTL, verification, the assembler and the competition
submission.

It does not state *why*. The reasoning behind the row format is in
[`row-format-decision.md`](row-format-decision.md); how the area and integration
measurements were made, and the history of conclusions that were wrong, is in
[`area-study.md`](area-study.md). Neither is normative. This document carries no
area figures and no state-machine counts.

## 0. Authority, and how to read this document

**Authority.** Where the Python models in `isa_bench/` and the structural RTL in
`rtl/` disagree, **the Python models win**: they are the versions that pass the
benchmarks. At the time of writing they agree on every shared encoding constant,
verified by `spec/conformance.py`. The RTL implements a 21-bit row with a 5-bit
target and a palette; this specification describes the frozen 32-bit row with an
8-bit target and no palette, so the RTL is behind the specification by exactly
that change and is not a second opinion about it.

**Two kinds of statement**, and the distinction is the main value of this
document:

| marker | meaning |
|---|---|
| **SPECIFIED** | An implementation must do this. It is traced to code in `isa_bench/` or to a measurement in this repository. |
| **CURRENT BEHAVIOUR** | The models happen to do this, it is not pinned down, and an implementation that does something else is not yet wrong. Every instance is also listed in §16. |

Anything determinable from neither the models nor a measurement is listed in
§16 as unspecified. It is not guessed at here.

**The encoding tables are generated.** Every table in §3–§7 is emitted from
`spec/isa.json` by `spec/gen_spec.py`. Do not edit them in this file.
`make spec-check` fails if this document drifts from that source, and
`spec/conformance.py` fails if that source drifts from `isa_bench/`.

---

## 1. Overview and terminology

The chip contains some number of independent **state machines**. Each executes a
program of up to 32 **rows** held in its own **imem**. One row is evaluated per
**core clock cycle**: the row's **test code** is evaluated, and if it passes the
row's **action group** and **pin operation** take effect. Control then moves to
the row's true or false exit. A state machine never stalls and never skips a
cycle.

These terms are used throughout with exactly these meanings, and no synonym is
used anywhere in this document:

| term | meaning |
|---|---|
| **row** | One 32-bit program word, and the unit of execution. One row is evaluated per core clock cycle. |
| **state machine** | One independent instance of the programmable engine, with its own imem, registers and pins. Abbreviated **SM** only in tables. |
| **imem** | The instruction memory of one state machine: 32 rows, held in two **tile**s. |
| **tile** | One `CFGMEM_IHP16` macro: 16 words of 32 bits. Two tiles make one imem. |
| **action group** | One of the five mutually-exclusive fields (`sr`, `c1`, `c2`, `tm`, `xx`) that together encode a row's actions in 13 bits. |
| **test code** | The 4-bit field selecting the condition evaluated on entry to a row. |
| **host** | Whatever drives the chip's pins to load programs and exchange bytes. Off-chip. |
| **core clock cycle** | One period of the chip's single clock input. The unit of all timing in §8. |

Terms deliberately **not** used: *instruction* for a row (say row; "instruction
memory" remains the expansion of **imem**), *opcode* (say test
code or action group), *word* (say row or tile word), *core* (say state
machine), *palette* (it does not exist — see §6).

---

## 2. Programmer's model

**SPECIFIED.** Every piece of architectural state in one state machine:

<!-- BEGIN GENERATED: state -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| state    | width       | reset                | scope  | description                                                                |
|----------|-------------|----------------------|--------|----------------------------------------------------------------------------|
| `row`    | 8           | 0                    | per-SM | Row pointer. Indexes the imem.                                             |
| `link`   | 8           | 0                    | per-SM | Link register, written by the call action, read by target 255.             |
| `sr`     | 8           | 0                    | per-SM | Shift register.                                                            |
| `cnt`    | 8           | 0                    | per-SM | Counter 1. Decrements wrap modulo 256.                                     |
| `c2`     | 8           | 0                    | per-SM | Counter 2. Decrements wrap modulo 256.                                     |
| `crc`    | 5           | 0x1F                 | per-SM | CRC5 register, reflected polynomial 0x14.                                  |
| `tcount` | UNSPECIFIED | P-1                  | per-SM | Timer down-counter. Width is not fixed by the models; see SPEC section 16. |
| `pinv`   | 3           | configured init_pins | per-SM | Output slot values, one bit per slot.                                      |

<!-- END GENERATED: state -->

Reset values are traced to `SttCore.__init__` in `isa_bench/stt.py`.

**SPECIFIED.** Per-state-machine configuration, set at program load and not
encoded in rows:

<!-- BEGIN GENERATED: config -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| item         | description                                                                                  | used by                                  |
|--------------|----------------------------------------------------------------------------------------------|------------------------------------------|
| `P`          | Timer reload period, in core clock cycles.                                                   | `tmr`, `trst`, `thalf`                   |
| `shift`      | Shift direction, left or right. Selects which end of the shift register is the serial bit.   | `shift`, `srbit`                         |
| `fill`       | Fill bit source for shift: constant 0, constant 1, or synchronized input 0.                  | `shift`                                  |
| `sr_width`   | Shift register width.                                                                        | `shift`, `srbit`, `load`, `loadk`, `clr` |
| `cload_abc`  | The three counter 1 reload constants.                                                        | `cload`, `cload_b`, `cload_c`            |
| `c2load_val` | Counter 2 reload constant.                                                                   | `c2load`                                 |
| `loadk`      | The constant K loaded by loadk.                                                              | `loadk`                                  |
| `init_pins`  | Reset value of each output slot.                                                             | —                                        |
| `slot_modes` | Per slot: push-pull or open-drain. In open-drain a 1 releases the net and a 0 drives it low. | —                                        |

<!-- END GENERATED: config -->

Configuration is not part of the 32-bit row and is not counted in program size.

**CURRENT BEHAVIOUR — timer width.** `tcount` is an unbounded Python integer in
the models, so its width is not fixed by them. The structural RTL uses 16 bits.
An implementation must make it wide enough for the required reload period `P`;
nothing here pins the width. See §16.

**SPECIFIED — FIFO depth and scope.**

<!-- BEGIN GENERATED: fifo -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| property                | value                                                                  |
|-------------------------|------------------------------------------------------------------------|
| depth                   | 4 entries                                                              |
| width                   | 8 bits                                                                 |
| scope                   | per state machine                                                      |
| binding case            | uart_rx at 3 cycles per bit, 10 bits per byte = a byte every 30 cycles |
| host latency at depth 4 | 120 cycles                                                             |

<!-- END GENERATED: fifo -->

**Per machine, not shared.** The models give every `SttCore` its own queues. A
shared buffer with round-robin arbitration — which `rtl/stt_hostbuf.v` implements
and `area-study.md` priced — loses a machine's `push` on any cycle it loses the
arbiter, and §8.1 forbids stalling to retry, so the byte is gone. That is
timing-dependent data loss, and cycle-exact lockstep against a per-machine model
could not hold. At depth 4 the cost is 5 × 2 × 4 × 8 = 320 storage flops plus
pointers, against roughly 100 shared. It buys determinism.

**Why 4.** The binding case is not the slowest protocol but the fastest
*receiver*. Measured at each program's minimum working bit period: `uart_rx` at
3 cycles/bit and 10 bits/byte delivers a byte every **30 cycles**, against SPI's
52 and I²C's 53. Four entries therefore give a host **120 cycles** — 2.55 µs at
the 47 MHz of §14 — to service a byte before one is lost. Depth is a parameter
(`FIFO_DEPTH`), so this can move without touching anything else.

> **A capture mode would not be served by more depth.** If a future program
> pushed one entry per *edge* rather than per byte, an edge can arrive every 3
> cycles: depth 4 gives 12 cycles, and even depth 32 gives 96. No plausible FIFO
> lets a polling host keep up. That capability needs a different mechanism —
> deeper dedicated capture storage, or in-loop compression by the machine, which
> is what the CRC and bit-stuffer units of §9 exist for. Sizing this FIFO for it
> would be wasted area.

**SPECIFIED — overflow and underflow are no-ops, and sticky.** A `push` onto a
full RX FIFO leaves it unchanged and **drops the byte**; the row's other actions,
its pin operation and its branch still happen. This is the same rule already
given above for `load` from an empty TX FIFO, so the two are one rule — *an
action that cannot be performed is not performed* — rather than two special
cases. Stalling is not available (§8.1: a row costs exactly one cycle and a
machine never stalls), and dropping the **oldest** instead would silently corrupt
an in-order byte stream.

Neither event is silent. Each FIFO sets a **sticky flag**, cleared only by reset,
so a host can tell that a byte was lost rather than discovering it as corrupt
protocol data.

**CURRENT BEHAVIOUR — FIFO depth.** The models use unbounded queues for the TX
and RX FIFOs, so no depth is specified. See §9 and §16.

---

## 3. Row format

**SPECIFIED.** A row is 32 bits. Field 0 occupies the least significant bits.

<!-- BEGIN GENERATED: row-format -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| bits    | width | field      | meaning                                                                      |
|---------|-------|------------|------------------------------------------------------------------------------|
| [3:0]   | 4     | `test`     | Test code selecting the condition evaluated on entry to the row.             |
| [5:4]   | 2     | `mode`     | Branch mode: how the true and false exits are derived from the target field. |
| [13:6]  | 8     | `target`   | Branch target row index, or 255 meaning return to the link register.         |
| [15:14] | 2     | `pin_slot` | Which output slot the pin operation applies to; 3 selects the D+/D- pair.    |
| [18:16] | 3     | `pin_op`   | Pin operation applied to the selected slot.                                  |
| [21:19] | 3     | `act_sr`   | Action group: shift register.                                                |
| [24:22] | 3     | `act_c1`   | Action group: counter 1.                                                     |
| [26:25] | 2     | `act_c2`   | Action group: counter 2.                                                     |
| [28:27] | 2     | `act_tm`   | Action group: timer.                                                         |
| [31:29] | 3     | `act_xx`   | Action group: CRC and call.                                                  |

Total **32 bits**.

<!-- END GENERATED: row-format -->

Traced to `rowformat.Format.encode` with `pins="single5"`, `acts="grouped"`,
`tgt_bits=8`, and `rowenc.pack`, which places the first field at bit 0.

---

## 4. Test codes

**SPECIFIED.** The test code selects one condition, evaluated **on entry to the
row**, before any of the row's actions take effect.

<!-- BEGIN GENERATED: tests -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| code | name     | true when                                                                                                        |
|------|----------|------------------------------------------------------------------------------------------------------------------|
| 0    | `always` | Unconditionally true.                                                                                            |
| 1    | `c2z`    | True when counter 2 reads zero.                                                                                  |
| 2    | `cz`     | True when counter 1 reads zero.                                                                                  |
| 3    | `fifo`   | True when the TX FIFO is not empty.                                                                              |
| 4    | `in0h`   | True when synchronized input 0 reads 1.                                                                          |
| 5    | `in0l`   | True when synchronized input 0 reads 0.                                                                          |
| 6    | `in1h`   | True when synchronized input 1 reads 1.                                                                          |
| 7    | `in1l`   | True when synchronized input 1 reads 0.                                                                          |
| 8    | `srbit`  | True when the shift register serial bit reads 1.                                                                 |
| 9    | `tmr`    | True on the cycle the timer reaches zero (the tick).                                                             |
| 10   | `stall`  | True while the bit stuffer will insert a bit rather than accept one, so the program can hold the shift register. |

<!-- END GENERATED: tests -->

Traced to `SttCore._test` in `isa_bench/stt.py`. Code 10 is `stall`, the bit
stuffer test of §9; it is implemented in the models and in `rtl2`. Codes
11–15 are unassigned; see §16.

Three of these need their sampling point stated precisely, and §8 does so:

- `in0h`, `in0l`, `in1h`, `in1l` read through the input synchronizer, not the
  pin directly (§8.3).
- `tmr` is true on the single cycle the timer reads zero, not for the whole bit
  period (§8.4).
- `srbit` reads the shift register **before** this row's actions, because the
  test is evaluated first (§8.2).

---

## 5. Branch modes and target resolution

**SPECIFIED.** Each row has a true exit and a false exit. The mode field selects
how both are derived from the single target field, which is what allows one
target to encode two exits.

<!-- BEGIN GENERATED: branch-modes -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| code | name     | test true | test false | meaning                                                                        |
|------|----------|-----------|------------|--------------------------------------------------------------------------------|
| 0    | `WAIT`   | target    | self       | Stay on this row until the test passes, then go to target.                     |
| 1    | `BRANCH` | target    | next       | Take the target when the test passes, otherwise fall through.                  |
| 2    | `SKIP`   | next      | target     | Fall through when the test passes, otherwise take the target.                  |
| 3    | `STEP`   | next      | self       | Fall through when the test passes, otherwise stay. The target field is unused. |

<!-- END GENERATED: branch-modes -->

where:

- **target** is the row index in the target field;
- **self** is the row currently executing;
- **next** is the row at index + 1.

Traced to `rowenc.rebuild` and the mode table in the `rowenc` module docstring.

**SPECIFIED.** The target field is 8 bits, so target values 0–254 address rows
and **255 means return**: control goes to the row index held in the link
register. The link register is written by the `call` action (§6), which stores
**the row's false exit**, not the next row.

**SPECIFIED.** The imem holds 32 rows (§12), so rows 0–31 are addressable and
reachable. An 8-bit target reaches every row with the return encoding to spare;
no row is unreachable.

**SPECIFIED — `RET` applies to whichever exit the target field feeds.** In
`WAIT` and `BRANCH` that is the true exit; in `SKIP` it is the **false** exit, so
a `SKIP` row with target 255 returns when its test *fails*. In `STEP` the target
field is unused and 255 has no meaning. The rule is the field's, not the exit's.

`SttCore` resolved `ret` only on the true exit until 2026-09-16 and raised
`KeyError` on a `SKIP` row with target 255; it now applies the same rule to
either exit. No reference program contains such a row, which is why the gap
survived: it is reachable only from a program nobody had written. The random
program suite in `rtl2/tb/` generates `RET` on all four modes and the RTL and
the model agree.

**SPECIFIED — `next`, including from the last row.**

<!-- BEGIN GENERATED: next-row-rule -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

**`next` = `next = (row + 1) mod 32`.**

next from row 31 wraps to row 0. Taken from rtl/stt_decode.v:73, which needs no program-length register. isa_bench/rowenc.py:182 wraps at the end of the PROGRAM instead; the two differ only for a program shorter than 32 rows that takes next from its own last row, which no reference program does -- all six end on a WAIT row, whose exits are both explicit.

<!-- END GENERATED: next-row-rule -->

This resolves what earlier revisions left undefined. It is the rule the
structural RTL already implements, it needs no program-length register, and no
reference program can tell the difference: all six end on a `WAIT` row, whose
exits are both explicit. The alternatives considered were halt and trap; both
need architectural state (a halted flag, or a fault vector) that nothing else in
the ISA uses, and neither is required by any program. Measured by
`isa_bench/nextrow.py`.

---

## 6. Action group encoding

There is **no palette and no action-set lookup table**. A row's actions are
encoded inline, in the 13 bits of the five action groups, and are decoded
directly. A reader coming from an earlier document should note that the 24-entry
fixed palette and the 8 loadable entries described there do not exist.

**SPECIFIED.** The five groups:

<!-- BEGIN GENERATED: action-groups -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

**Group `sr`** — row bits [21:19], group-local [2:0]. Shift register. At most one choice per row.

| code | actions        | meaning                                                                                                            |
|------|----------------|--------------------------------------------------------------------------------------------------------------------|
| 0    | —              | No shift-register action.                                                                                          |
| 1    | `load`         | Load a byte popped from the TX FIFO. On an EMPTY TX FIFO the shift register holds its value and no byte is popped. |
| 2    | `loadk`        | Load the configured constant K.                                                                                    |
| 3    | `loadcrc`      | Load the complement of the CRC register, 5 bits.                                                                   |
| 4    | `clr`          | Clear to zero.                                                                                                     |
| 5    | `shift`        | Shift one place in the configured direction, inserting the fill bit.                                               |
| 6    | `clr`, `shift` | Clear then shift.                                                                                                  |
| 7    | `push`         | Push the shift register to the RX FIFO.                                                                            |

**Group `c1`** — row bits [24:22], group-local [5:3]. Counter 1. At most one choice per row.

| code | actions   | meaning                                   |
|------|-----------|-------------------------------------------|
| 0    | —         | No counter 1 action.                      |
| 1    | `cload`   | Load counter 1 from configured value A.   |
| 2    | `cload_b` | Load counter 1 from configured value B.   |
| 3    | `cload_c` | Load counter 1 from configured value C.   |
| 4    | `cdec`    | Decrement counter 1, wrapping modulo 256. |

**Group `c2`** — row bits [26:25], group-local [7:6]. Counter 2. At most one choice per row.

| code | actions  | meaning                                   |
|------|----------|-------------------------------------------|
| 0    | —        | No counter 2 action.                      |
| 1    | `c2load` | Load counter 2 from its configured value. |
| 2    | `c2dec`  | Decrement counter 2, wrapping modulo 256. |

**Group `tm`** — row bits [28:27], group-local [9:8]. Timer reload override. At most one choice per row.

| code | actions | meaning                                          |
|------|---------|--------------------------------------------------|
| 0    | —       | No timer action; the timer free-runs.            |
| 1    | `trst`  | Reload the timer with P-1 (a full bit period).   |
| 2    | `thalf` | Reload the timer with P/2-1 (half a bit period). |

**Group `xx`** — row bits [31:29], group-local [12:10]. CRC and call. At most one choice per row.

| code | actions          | meaning                                                              |
|------|------------------|----------------------------------------------------------------------|
| 0    | —                | No action.                                                           |
| 1    | `crcrst`         | Reset the CRC register to all ones.                                  |
| 2    | `crcstep`        | Advance the CRC by the shift register serial bit.                    |
| 3    | `call`           | Write the row's false exit into the link register.                   |
| 4    | `crcrst`, `call` | Reset the CRC and link, in that order.                               |
| 5    | `crc16rst`       | Seed the shared 16-bit CRC from its configured seed. Frame boundary. |
| 6    | `crc16step`      | Advance the shared CRC by the shift register serial bit.             |
| 7    | `stuffrst`       | Flush the bit stuffer's run counter. Frame boundary.                 |

<!-- END GENERATED: action-groups -->

Traced to `rowenc.GROUPS`.

### 6.1 Which action sets are encodable

**SPECIFIED.** Groups are mutually exclusive internally. An action set is
encodable in one row if and only if it satisfies every rule below. This is the
rule an implementer applies; it is not a statistic.

<!-- BEGIN GENERATED: action-rule -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| group | rule                                                                                                                           |
|-------|--------------------------------------------------------------------------------------------------------------------------------|
| `sr`  | at most one of `clr`, `load`, `loadcrc`, `loadk`, `push`, `shift`; except {`clr`, `shift`} may appear together                 |
| `c1`  | at most one of `cdec`, `cload`, `cload_b`, `cload_c`                                                                           |
| `c2`  | at most one of `c2dec`, `c2load`                                                                                               |
| `tm`  | at most one of `thalf`, `trst`                                                                                                 |
| `xx`  | at most one of `call`, `crc16rst`, `crc16step`, `crcrst`, `crcstep`, `stuffrst`; except {`crcrst`, `call`} may appear together |

An action set is encodable in one row if and only if it satisfies every rule above. That makes **2880** distinct action sets reachable.

Every code in that count is implemented: the wider shared units of §9 are live, not reserved, so there is no second count.

<!-- END GENERATED: action-rule -->

### 6.2 What a program does when it needs a forbidden set

**SPECIFIED.** A set that violates any rule in §6.1 cannot be encoded in one
row. The program must split it across consecutive rows, preserving the order in
§6.3. The reference splitter is `rowformat.split_rows`, which takes the longest
encodable prefix of the ordered actions, emits it as one row, and repeats. The
rows it emits carry the original test on the first row and `always` on the rest,
and place pin operations that read the shift register on the last row of the
chain so they observe the completed sequence.

Splitting costs rows, and rows are the scarce resource (§12).

### 6.3 Order of effect within a row

**SPECIFIED.** When a row's test passes, its actions take effect in this fixed
order, regardless of the order of the group fields:

<!-- BEGIN GENERATED: action-order -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

Within a row, actions take effect in this fixed order:

`load` → `loadk` → `loadcrc` → `clr` → `crcrst` → `crcstep` → `crc16rst` → `crc16step` → `stuffrst` → `shift` → `push` → `cload` → `cload_b` → `cload_c` → `cdec` → `c2load` → `c2dec` → `trst` → `thalf` → `call`

<!-- END GENERATED: action-order -->

Traced to `stt.ACT_ORDER` and the iteration order in `SttCore.step`.

Because the groups are mutually exclusive, at most one action from
`{load, loadk, loadcrc, clr, shift, push}` occurs per row, so the only ordering
that is observable in practice is:

- **`crcstep` sees the shift register before `shift`**, because `crcstep`
  precedes `shift` in the order above;
- **pin operations see the shift register after `shift`**, because all actions
  complete before any pin operation (§7).

---

## 7. Pin operations

**SPECIFIED.** A row performs **at most one pin write**. The row names one slot
and one operation; there is no way to drive two slots independently in a single
row. A program that must change two pins uses two rows.

This is a real constraint on protocols whose signals must move together, and it
is why a state-machine protocol costs more rows than a bit loop (§13).

**SPECIFIED.** Slots:

<!-- BEGIN GENERATED: pin-slots -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| code | slot    | meaning                                        |
|------|---------|------------------------------------------------|
| 0    | `slot0` | Output slot 0.                                 |
| 1    | `slot1` | Output slot 1.                                 |
| 2    | `slot2` | Output slot 2.                                 |
| 3    | `pair`  | The D+/D- pair: writes slots 0 and 1 together. |

<!-- END GENERATED: pin-slots -->

**SPECIFIED.** Operations. Slot code 3 selects the D+/D− pair, which writes
slots 0 and 1 together and gives the pair-specific meanings in the right-hand
column:

<!-- BEGIN GENERATED: pin-ops -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| code | op     | single slot                                                                                      | pair slot (code 3)                             |
|------|--------|--------------------------------------------------------------------------------------------------|------------------------------------------------|
| 0    | `hold` | No write. The slot keeps its value.                                                              | No write.                                      |
| 1    | `lo`   | Drive 0.                                                                                         | Drive (0,0).                                   |
| 2    | `hi`   | Drive 1.                                                                                         | Drive (1,1).                                   |
| 3    | `sr`   | Drive the shift register serial bit.                                                             | Drive (srbit, NOT srbit).                      |
| 4    | `tgl`  | Invert the slot.                                                                                 | Invert both slots.                             |
| 5    | `d0`   | No write; the slot holds. d0/d1 are pair-only ops and the encoder rejects them on a single slot. | Drive (0,1).                                   |
| 6    | `d1`   | No write; the slot holds. d0/d1 are pair-only ops and the encoder rejects them on a single slot. | Drive (1,0).                                   |
| 7    | `crcb` | Drive the shared CRC serial bit, advancing the register.                                         | Drive the shared CRC serial bit on both slots. |

<!-- END GENERATED: pin-ops -->

Traced to `rowformat.PINOPS`, `rowformat.SLOTS` and the pin handling in
`SttCore.step`.

**SPECIFIED.** `hold` (code 0) means no write at all, independent of the slot
field. A row that performs no pin operation encodes `hold`.

**SPECIFIED.** Slot drive mode is per-slot configuration, not a row field. In
**open-drain** mode a 1 releases the net and a 0 drives it low; in **push-pull**
mode both values are driven. Traced to the `mode` handling at the end of
`SttCore.step`.

**SPECIFIED — `d0` and `d1` on a single slot: no write; the slot holds.**
Codes 5 and 6 name the two halves of the pair. On a single slot both the model
(`SttCore.step` handles them in the pair branch only) and the structural RTL
(`rtl/stt_datapath.v:271`, where `single_we` defaults to 0) write nothing. The
two agree, so specifying the no-op costs no hardware and changes no
implementation.

A program that asks for it still has a bug, and the ISA has no trap mechanism
to report one, so the check lives in the toolchain instead: **`SttProgram`
rejects a single-slot `d0`/`d1` at construction** with `d0/d1 are pair-only`.
Hardware is permissive, the encoder is strict, and `hold` remains the way to
write nothing on purpose.

> A second pin-op list exists in `isa_bench/rowenc.py` with only five entries
> and no `d0`/`d1`. It is used by older encoding schemes that this
> specification does not describe. The list that applies here is
> `rowformat.PINOPS`, which `spec/conformance.py` checks.

---

## 8. Timing model

This is the property the chip exists to provide, and the place the models, the
RTL and silicon are most likely to diverge. It is written to be read literally.

**What was actually verified.** The benchmarks in `isa_bench/` are
cycle-accurate and check protocol timing at the pins: UART TX, UART RX and USB
assert zero jitter, and SPI and I²C assert minimum clock-phase lengths against
the programmed bit period. Everything in §8.1–§8.5 is traced to that model and
those assertions. **No static timing analysis has been run, and no
SDF-annotated simulation.** The model has no pin path, so it cannot speak to
propagation delay, inter-pin skew or Fmax; see §14 and §16.

### 8.1 The cycle

**SPECIFIED.** One row is evaluated per core clock cycle. A state machine never
stalls, never skips a cycle and never takes more than one cycle per row. **A
row costs exactly one core clock cycle**, whether or not its test passes.

**SPECIFIED.** Within a cycle, in this order, traced to `SttCore.step`:

1. The **timer tick** is sampled: `tmr` is true if and only if the timer reads
   zero at this point, before anything else in the cycle.
2. The row's **test code** is evaluated (§4). Inputs are read through the
   synchronizer (§8.3); `srbit` reads the shift register as it stands now,
   before any of this row's actions.
3. **If and only if the test passes**, the row's actions take effect in the
   order of §6.3.
4. **If and only if the test passes**, the row's pin operation is applied. It
   observes the shift register **after** step 3.
5. The next row is selected: the true exit if the test passed, the false exit
   otherwise (§5).
6. The **timer is updated** (§8.4). This happens whether or not the test passed.
7. The output slots are driven with their current values.

A failing test therefore changes nothing except the row pointer and the timer.

### 8.1.1 What the no-stall rule forbids

**SPECIFIED — nothing a row can invoke may be shared between state machines.**
This follows from §8.1 alone and is stated here because it has already been
rediscovered twice, each time as a surprise.

A row costs exactly one cycle. A resource shared by N machines can be reached by
N rows on the same cycle, and serving them needs arbitration; arbitration means
at least one machine waits; §8.1 leaves nowhere for that wait to go. There is no
stall signal in this architecture, no back-pressure into the row sequencer, and
no way for a row to take two cycles. So the only shareable thing is something no
row can reach.

The test is mechanical. **If any row field can invoke it, it replicates.**

| reached by | example | consequence |
|---|---|---|
| an action | `push`, `load`, `crc16step`, `stuffrst` | per machine |
| a test | `fifo`, `stall` | per machine |
| a pin op | `crcb` | per machine |
| configuration only | the period `P`, the CRC polynomial | may be per machine for other reasons, but not for this one |
| the host, between machines | the pin assignment chain, the loader | may be shared |

Where it has bitten: the TX and RX FIFOs are per machine because `fifo` is a
test and `push` and `load` are actions (§9), and the wide CRC and the bit
stuffer are per machine because `crc16step`, `stall` and `crcb` reach them
(§9). Both were first priced as single shared blocks, and both cost the machine
count instead. A third instance should not be a surprise.

This is a rule about **state machines**, not about the chip. The host byte port
of §11.2 is shared by all five machines and is not a counterexample: no row can
invoke it. A row reaches its own FIFO, and the port reaches the FIFOs.

### 8.2 Ordering that programs can observe

**SPECIFIED.** Two consequences of §8.1 that a program can rely on:

- **`crcstep` sees the shift register before `shift`.** Both are step 3, and
  `crcstep` precedes `shift` in §6.3.
- **The pin operation sees the shift register after `shift`.** Step 4 follows
  step 3. A row that both shifts and drives `sr` emits the *new* serial bit.

**SPECIFIED.** A test reads state as it was at the **start** of the cycle. A row
whose test is `cz` and whose action is `cdec` tests the counter *before* its own
decrement.

### 8.3 The input synchronizer

**SPECIFIED.** Input pins are not read directly. Every input passes through a
**two-cycle synchronizer**: a value present on the pin at the end of cycle *N*
is first visible to a test code in cycle *N+2*.

Measured, not asserted: driving an input high at cycle 5 makes the net read 1
from cycle 5, the core's test read 1 from cycle 7, and the resulting row change
take effect for cycle 8. Traced to `World.read_sync` with `sync=2`.

**SPECIFIED — what the synchronizer holds after reset.** Both stages reset to 0,
so every input reads **0 for the first two cycles** after reset deasserts,
whatever the pin is actually doing. An implementation must therefore not enable a
state machine until its inputs have been stable for at least two cycles. In
practice that is free: a machine cannot run until its configuration and program
have been shifted in, which takes hundreds of cycles, by which time the
synchronizer has long since tracked the pins.

The Python model does not model this. `World.read_sync` falls back to the net's
*current* value while its history is shorter than the synchronizer depth, which
gives the model **zero lag on cycles 0 and 1** — something hardware cannot do.
The two agree from cycle 2 onward. `rtl2/tb/steps.py` seeds the history with two
idle samples so the model lags the same way; without it, four of sixty random
programs disagreed on cycle 0 with the RTL, in every case because a device drove
a pin on cycle 0.

**SPECIFIED.** This applies to `in0h`, `in0l`, `in1h`, `in1l`, and to the `fill`
configuration when it selects input 0 as the shift-in source. It does not apply
to `fifo`, `cz`, `c2z`, `srbit` or `tmr`, which read internal state.

**Consequence for programs.** An edge cannot be responded to sooner than two
cycles after it occurs, and a program that samples an input a fixed number of
cycles after driving an output must budget for it.

### 8.4 The timer

**SPECIFIED.** The timer is a down-counter with reload period `P`, configured
per state machine (§2).

- It **free-runs**: on every cycle, if it reads zero it reloads to `P−1`,
  otherwise it decrements. **This happens whether or not the row's test
  passed**, and whether or not the row has a timer action.
- `tmr` is true on **exactly one cycle in `P`** — the cycle the counter reads
  zero, not the whole bit period.
- `trst` reloads it to `P−1` and `thalf` to `P/2−1`, and **only on a row whose
  test passed**. They override that cycle's free-running update.
- At reset it holds `P−1`.

Measured at `P=4`: free-running gives `tcount` = 3,2,1,0,3,2,1,0 with `tmr` true
one cycle in four; `trst` on a passing row every cycle pins it at 3; `thalf`
pins it at 1; and `trst` on a **failing** row changes nothing — the counter
free-runs as if the action were absent.

**Consequence for programs.** `thalf` is how a program lands a sampling point in
the middle of a bit cell: reload half a period so the next tick falls at the
half-bit boundary.

### 8.5 Output timing

**SPECIFIED.** A pin operation applied in cycle *N* is visible on the output net
at the end of cycle *N*. Output slots hold their value until another row writes
them; there is no automatic return to an idle level.

**SPECIFIED.** In open-drain mode a slot value of 1 releases the net and 0
drives it low, so the resting level is whatever the external pull-up provides.

**CURRENT BEHAVIOUR — everything below the net.** The model drives an ideal net
with zero propagation delay. Pad delay, board delay, rise and fall times and
skew between pins are outside it. In a synchronous design a uniform pad delay
shifts every edge equally and does not change a phase length, but **skew between
two pins does change the relationship between a clock and its data**, and that
is unmeasured. See §14 and §16.

---

## 9. Per-machine units

**SPECIFIED — CRC5, per state machine.** Each state machine has a 5-bit CRC
register, reset to `0x1F`, driven by three actions:

| action | effect |
|---|---|
| `crcrst` | Set the register to `0x1F`. |
| `crcstep` | Advance by the shift register serial bit: if `(crc XOR bit)` is odd, `crc = (crc >> 1) XOR 0x14`, else `crc = crc >> 1`. |
| `loadcrc` | Load the shift register with `(NOT crc) AND 0x1F`. |

This is a reflected CRC5 with polynomial `0x14`, which is the USB CRC5
(x⁵+x²+1, reflected). Traced to `SttCore.step`. It is fixed, not programmable.

**SPECIFIED — every unit in this section is PER STATE MACHINE, not shared.**
This section used to be called "shared units", because `crc_lfsr16.v` and
`bit_stuffer.v` were written as single blocks in `rtl/` and the configuration C
floorplan instantiates one of each for the whole chip. That is not implementable
and the name was wrong.

Sharing is ruled out by §8.1.1, not by cost, and by the general rule stated
there rather than by anything specific to these two units. Both units hold per-stream state — the
CRC register and the stuffer's run length and last bit — and two machines
emitting bits into one stuffer would interleave into a single run counter and
corrupt each other's stuffing. Serializing access needs arbitration, and
arbitration means one machine waits. §8.1 says a machine never stalls and takes
exactly one cycle per row, so there is nowhere for that wait to go. Five machines
running five different protocols is the architecture; a single polynomial and a
single run counter cannot serve it.

The cost is real and is charged per machine: 22 flops of state in `stt_core`
(16 of CRC, 6 of stuffer) and 31 in `stt_config` for the polynomial, width,
direction, seed, threshold and slot routing.

**Context — the four blocks in `rtl/`.** `rtl/` also contains a 16-bit
programmable-polynomial CRC/LFSR (`crc_lfsr16.v`), a configurable bit stuffer
(`bit_stuffer.v`), shared TX/RX FIFOs with a round-robin arbiter
(`stt_hostbuf.v`) and a pin multiplexer (`stt_iomux.v`). These were written and
synthesised to price them, and `row-format-decision.md` §6 recommends keeping
the CRC unit and the stuffer on capability grounds.

The USB reference program uses the per-SM CRC5 above (`crcrst` once, `loadcrc`
once, `crcstep` three times); every action in §6 is used by at least one
reference program. The reachability question below is about the two *wider*
units only.

**SPECIFIED — `hostbuf` and `iomux` are reached through existing row fields.**
These two are not a gap and never were. `stt_hostbuf`'s state-machine-side
control inputs are `tx_pop`, `rx_push` and `tx_ne`, which are exactly the
`load` and `push` actions (§6) and the `fifo` test (§4). `stt_iomux`'s are
`sm_out`, `sm_oe` and `sm_in`, which are every pin operation (§7) and the `in0`
/ `in1` tests. Their remaining inputs — the host byte port and the
pin-assignment registers — are host-side configuration carried on the serial
chain that already exists (§10). A row needs no new field to use either.

**SPECIFIED, BUT NOT IMPLEMENTED — reaching the wider units.** `crc_lfsr16`
(16-bit programmable polynomial) and `bit_stuffer` (configurable insert/remove)
genuinely have no path from a row. In `rtl/stt_chip.v` their control inputs are
tied to raw `ui_in`/`uio_in` bits and their outputs reach nothing a row can
read; that wiring exists only to satisfy the area harness's rule that every
input be driven, and is not an architecture.

Taking every control input from the two module port lists and asking where each
one has to live, **7 of 12 are per-program constants** that the existing serial
configuration chain carries, and **5 need a row to be able to say them**. Those
five need a row code, and get one here:


**This costs zero row bits.** Every code is appended to a field that had spare
capacity: `test` 10→11 of 16, `pin_op` 7→8 of 8, `act_xx` 5→8 of 8. Because the
codes are appended rather than inserted, no existing code index moves.
`isa_bench/freeze_check.py` holds the packed words of all six reference
programs and `make check` fails if any of them moves: **84 rows, all identical,
all still 32 bits wide**. The row format of §3 is unchanged.

**The residual cost is mutual exclusion, not space.** `act_xx` and `pin_op` are
now full. A row that wants `crc16step` together with `call`, `crcrst` or
`crcstep` must split into two rows; `act_xx` is already non-zero on 8 of 59
reference rows, all of them in USB. `crcb` replaces a slot write rather than
competing with one, so filling `pin_op` costs nothing today and only forecloses
a ninth pin op. `act_sr` was already full at 8 of 8 and the amendment
deliberately avoids it: the CRC residue leaves through `crcb` onto a pin, which
is how CRCs are actually transmitted, rather than through a shift-register load.

**Status: implemented.** These codes are live in `spec/isa.json`, in the models
and in `rtl2`, and `spec/conformance.py` checks them alongside every other
code. A conforming implementation must provide them.

The capability they were added for is measured, not assumed. `isa_bench/can_prog.py`
transmits a CAN 2.0A base frame in **24 of 32 rows**, checked against the `CanRx`
receiver in `isa_bench/jtag_can.py` over five identifier/payload combinations,
with the CRC-15 cross-checked against an independent polynomial reduction and
the receiver shown to reject corrupted frames at seven glitch positions.

**What they cost.** Measured by synthesising `rtl2` against `sg13cmos5l` before
and after, with `stt_core` standalone to separate the core from its
configuration:

| | before | after | delta |
|---|---|---|---|
| `stt_core` flops | 62 | 84 | +22 (`crc16` 16, stuffer 6) |
| `stt_config` flops | 69 | 100 | +31 (polynomial, width, thresholds) |
| `stt_top` cell area | 94,583.16 | 100,806.85 | **+6.58%** |

`crc16` is reset to zero rather than to its configured seed, and takes the seed
in the load branch instead. Seeding it asynchronously would make it the only
register in the design with a non-constant asynchronous reset, which yosys maps
to 16 `$_ALDFFE_PNP_` async-load flops that the standard cell library has no
cell for. Avoiding that costs 0.92% of `stt_top` and is worth it.

Neither unit is a convenience. The legacy `crc` unit is 5 bits wide with a
hard-wired 0x14 polynomial, so CAN’s CRC-15 cannot be computed with the live
codes at any row count. Bit stuffing in rows costs **54 rows** against a 32-row
ceiling (`isa_bench/can_soft.py`), and it cannot cover the CRC sequence at all:
no test reads the wide CRC register, so a program cannot see the bit `crcb`
emits and cannot track its run length. See §16.

**SPECIFIED — `load` on an empty TX FIFO.** The shift register **holds its
value** and **no byte is popped**. The row is otherwise unaffected: its other
actions and its pin operation still happen, and the branch still resolves. The
model records an error for the programmer's benefit (`"stt: load from empty
FIFO"`) but changes no state, and the RTL does the same. Found by the mutation
suite in `rtl2/tb/`, which reached the case through a corrupted `uart_tx` that
drains the FIFO faster than it refills.

> The models use unbounded queues and do not model a full RX FIFO at all, so
> the overflow rule above is a property of the hardware that the models cannot
> express. A test that lets the RX FIFO overflow will diverge from the model,
> correctly: the model kept a byte the hardware dropped.

---

## 10. Host interface

**SPECIFIED — program load.** The imem is written by a **serial shift-in**. The
host presents one bit per cycle with the load enable asserted. A staging
register assembles a row least-significant bit first, matching `rowenc.pack`;
when the bit counter wraps, the staged row is written and the write pointer
advances.

<!-- BEGIN GENERATED: load-protocol -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| requirement   | rule                                                                                                                                                                                                 |
|---------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **bit order** | One bit per cycle with the load enable asserted, least-significant bit of the row first.                                                                                                             |
| **busy**      | After each 32-bit row the loader walks a one-hot enable down the latch chain, 16 rows x 3 clocks = 48 cycles, and asserts `ld_busy`. The host MUST NOT present the next bit while `ld_busy` is high. |
| **full load** | The host MUST load all 32 rows, padding beyond the program's length. A tile that receives fewer than 16 words holds them at the wrong chain positions and reads back scrambled.                      |
| **order**     | Rows are loaded in ascending address order starting at row 0. There is no random access and no read-back path.                                                                                       |

| quantity                  | value           |
|---------------------------|-----------------|
| row width                 | 32 bits         |
| imem depth                | 32 rows         |
| tiles                     | 2 x 16 words    |
| walk after each row       | 48 cycles       |
| shift-in per row          | 32 cycles       |
| **total to load 32 rows** | **2560 cycles** |

<!-- END GENERATED: load-protocol -->

**Why there is a busy signal and a full-load rule.** Both are consequences of
what `CFGMEM_IHP16` is, not choices. The macro is a **shift chain, not a
random-access array**: only row 0 can be written from `Di0`, and every other row
takes its predecessor. Three independent confirmations —

- the DFFRAM netlist: `SLICE[i].STORAGE` has `.D(Di0_in[i])`, `.Q(Di0_in[i+1])`;
- prism's reference model (`src/user_peripherals/cfgmem/cfgmem.v`):
  `le = WROW & {16{WE0}}`, row 0 takes `Di0`, row *i* takes row *i−1*;
- prism's loader comment: a write "takes DEPTH\*3 clocks to walk the WROW
  pulses".

So a row is written by walking a one-hot enable from row 15 **down** to row 0 —
backwards, so each row is written while its source still holds the old value.
Opening every row at once ripples the value down the whole chain; an even/odd
two-phase split fails because whichever half runs second reads rows the first
half already updated. Both were tried and `rtl2/tb/test_imem.py` rejected both.

The full-load rule has the same origin. Writing *k* words into a tile leaves
them at chain rows 0…*k*−1, so the read mapping — address *a* at chain row
15−*a* — holds only when a tile receives all 16. A short program loaded as-is
reads back scrambled. Padding costs nothing: the imem is 32 rows whatever the
program's length, and rows a program never branches to are never executed.

> This was found by swapping the behavioural memory for the macro and running
> the existing suites. The failure pattern named the cause: the six reference
> programs failed **except USB**, which has exactly 16 rows, and the random
> programs, which all have 32. Everything that passed was a multiple of 16.

**CURRENT BEHAVIOUR — the structural RTL cannot do this.**
`rtl/stt_imem_cfgmem.v` drives a **one-hot** `WROW` as though the macro were a
random-access array. Against a shift chain that copies the previous row into the
selected one instead of writing it, so that module would not work at all. It was
synthesised for area and never simulated (§16.2). `rtl2/stt_imem_cfgmem.v` is
the working implementation.

**SPECIFIED — state machine select.** When more than one state machine is
present, `uio_in[7:5]` selects which one the load enables address, so exactly
one is programmed at a time. Traced to `rtl/stt_chip.v`.

> This is not only an interface convenience. Without a per-state-machine select
> every instance receives the same serial stream and holds identical state,
> which lets synthesis merge them — a real measurement error found and
> documented in `area-study.md`.

**SPECIFIED — configuration load.** The per-state-machine configuration of §2 is
written by the same kind of serial chain, with its own enable.

**SPECIFIED — bring-up order.** A state machine must not be enabled until its
inputs have been stable for **at least two cycles**, because the input
synchronizer resets to 0 and reads every input low until then (§8.3). Enabling
earlier makes the machine's first two cycles act on inputs that read low
whatever the pins are doing, which for a `WAIT` on `in0l` means taking the exit
immediately.

In practice this costs nothing and needs no delay loop: configuration and
program are shifted in first, which takes 69 + 32 x *rows* cycles — hundreds —
and the synchronizer tracks the pins throughout. The requirement is stated
because a bring-up sequence that enabled a machine straight out of reset, with
the program already resident, would violate it.

**CURRENT BEHAVIOUR — run/halt and reconfiguration.** `stt_chip.v` has an
`ena` input that gates execution, and the load enables are separate from it, so
a program can be shifted in while the machine is held. The models have no notion
of halt: `SttCore` steps whenever called. Whether a state machine may be
reprogrammed while running, and what its state is on the first cycle after a
reload, is **not specified**. See §16.

**There is no palette load.** Earlier designs shifted 8 loadable action-set
entries into each state machine at startup. The frozen row format encodes
actions inline (§6), so that chain does not exist and reconfiguration is a row
load and nothing else.

---

## 11. Chip boundary

**SPECIFIED.** The chip presents the standard Tiny Tapeout boundary and nothing
else:

| group | width | direction | notes |
|---|---|---|---|
| `ui_in` | 8 | input only | Load enables, serial data, host strobes. |
| `uo_out` | 8 | output only | Always driven; cannot be tri-stated. |
| `uio` | 8 | bidirectional | The **only** pins that can be inputs, outputs or high-impedance, each with its own output-enable. |
| `clk` | 1 | input | The single core clock. All timing in §8 is in its cycles. |
| `rst_n` | 1 | input | Active-low reset. |
| `ena` | 1 | input | Tile enable. |

Traced to `rtl/stt_chip.v` and the Tiny Tapeout template used in
`area-study.md` §1.

**SPECIFIED.** Because only the 8 `uio` pins are bidirectional, **a protocol
needing a bidirectional signal must be assigned to a `uio` pin**. An
open-drain slot (§7) driven onto a `uo_out` pin cannot release the net. I²C's
SDA and SCL, and any protocol reading back on a line it also drives, are
therefore constrained to `uio`.

**CURRENT BEHAVIOUR — reset.** `rst_n` clears the state in §2 to the reset
values listed there. What the output pins do between power-up and the first
clock edge is not modelled. See §16.

### 11.1 Pin assignment

**SPECIFIED.** A state machine's slots and inputs are not wired to fixed pins.
Every drivable pin carries a select field naming the one driver that drives it,
and every machine input carries a select field naming the one pin it reads.
Both fields ride the serial configuration chain (§10).

<!-- BEGIN GENERATED: pin-map -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| group    | width | pin index | can drive | can be read |
|----------|-------|-----------|-----------|-------------|
| `uo_out` | 8     | 0-7       | yes       | no          |
| `uio`    | 8     | 8-15      | yes       | yes         |
| `ui_in`  | 8     | 0-7       | no        | yes         |

At **5 state machines**:

| quantity                        | value        | from                  |
|---------------------------------|--------------|-----------------------|
| drivers to place                | 15           | 5 machines x 3 slots  |
| output-capable pins             | 16           | `uo_out` + `uio`      |
| inputs to source                | 10           | 5 machines x 2 inputs |
| input-capable pins              | 16           | `ui_in` + `uio`       |
| output select field             | 4 bits       | ceil(log2(15))        |
| output select chain             | 64 bits      | 16 pins x 4 bits      |
| input select field              | 4 bits       | ceil(log2(16))        |
| input select chain              | 40 bits      | 10 inputs x 4 bits    |
| `run` flag                      | 1 bit        | §11.1                 |
| host port enable                | 1 bit        | §11.2                 |
| host port pin selects           | 8 bits       | 2 pins x 4 bits       |
| **pin-assignment config total** | **114 bits** |                       |

<!-- END GENERATED: pin-map -->

**SPECIFIED — the output side is pin-centric, and that settles contention.**
Each of the 16 output-capable pins selects exactly one driver, where a driver is
a (machine, slot) pair numbered `machine * 3 + slot`. The consequence is
structural rather than a rule anyone has to enforce: **two machines cannot
target the same pin, because a pin does not choose two drivers.** The question
of what happens on contention does not arise, and no arbitration exists or is
needed.

The following all follow from the same shape and are **SPECIFIED**:

- **Several pins may select the same driver.** One slot can appear on many pins.
  This is legal and is how a signal is fanned out.
- **A machine may have any number of its slots mapped, from none to all three.**
  There is no per-machine limit. The only limit is that 16 pins exist.
- **A driver no pin selects is simply unobserved.** It is not an error. A
  machine whose slots are all unmapped still runs, still counts and still tests;
  it just drives nothing.
- **The output enable follows the same select.** A `uio` pin is driven when its
  selected driver's slot has its output enable asserted, and is high-impedance
  otherwise. `uo_out` pins ignore the output enable and are always driven (§11),
  so an open-drain slot (§7) mapped to a `uo_out` pin cannot release the net.
- **Reset value.** All select fields reset to zero, so before the chain is
  loaded every pin selects driver 0, which is machine 0 slot 0. An
  implementation must load the pin-assignment chain before enabling the
  machines; the reset state is defined but is not useful.

**SPECIFIED — the boundary caps how many slots can be mapped at once.** There
are 16 output-capable pins and a driver per (machine, slot), so **at most 16
drivers can be mapped simultaneously**. At five machines that is 15 of 16, and
every slot of every machine can be on a pin at the same time. At six it would be
18, so at least two slots would have to stay unmapped — legal, per the rule
above, but it means six machines cannot all use three pins. This is a constraint
on the boundary, entirely independent of whether six machines route, and it
points the same way.

**SPECIFIED — `run`, and why the pin budget depends on it.** One bit in the
configuration chain separates configuration from operation. It is cleared by
`rst_n` and set by the host as the last step of configuration; nothing clears it
but reset, so live reprogramming means asserting `rst_n` (§16).

While `run` = 0, these pins carry control and are not available to the iomux:

<!-- BEGIN GENERATED: pin-config-mode -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| pin           | role while `run` = 0                              |
|---------------|---------------------------------------------------|
| `ui_in[2:0]`  | load enables: imem, configuration, pin assignment |
| `ui_in[3]`    | reserved                                          |
| `ui_in[4]`    | serial load data                                  |
| `ui_in[6:5]`  | host TX write and RX read strobes                 |
| `uio_in[7:5]` | state-machine select for the load chains          |

<!-- END GENERATED: pin-config-mode -->

While `run` = 1 **none of them is reserved**: all 8 `ui_in` and all 8 `uio` bits
are available as machine inputs, and all 8 `uio` pins are bidirectional.

This bit is load-bearing, not a convenience. Without it those pins would be
consumed permanently, leaving `uo_out[7:0]` plus `uio[4:0]` — **13
output-capable pins for 15 drivers**. Five machines with three slots each would
not fit on the boundary at all. With it, 15 drivers have 16 pins.

**SPECIFIED — the machines start two cycles after `run`, not on it.** Setting
`run` releases the pins to the iomux immediately; the machines are enabled two
cycles later. This is how §8.3's two-cycle input-stability requirement is met
**by construction** rather than being an obligation the host can forget.

It cannot be met any other way. `run` is the last bit of the pin-assignment
chain, so `ui_in` is carrying chain data right up to the moment it goes high and
the input synchronizers are full of it. Without the delay a machine's first row
acts on leftover configuration traffic — `uart_rx` read a chain bit as a start
bit and took its branch on cycle 0.

**SPECIFIED — `uo_out[0]` reports loader busy while `run` is low.** The boundary
has no spare pin for the busy signal §10 requires the host to honour, and before
`run` the iomux outputs are meaningless because no assignment has been loaded.
So `uo_out` carries loader status until `run` goes high, after which the iomux
owns all 16 pins. A host must not read `uo_out[0]` as busy once `run` is set: it
is then whichever driver pin 0 selects, which for a machine idling high reads 1
forever.

**IMPLEMENTED in `rtl2/stt_iomux.v` and `rtl2/stt_chip.v`**, and verified
through the pins by `rtl2/tb/test_chip.py`: five machines configured over
`ui_in` with machine select on `uio_in[7:5]`, then the pin-assignment chain,
then `run`, then 1200 cycles with every machine checked against its own model
and every assigned driver checked on its assigned pin.

`rtl/stt_iomux.v` is the older measurement harness and does NOT implement this.
Its inputs are a fixed tap — machine *m* reads `ui_in[2m]` and `ui_in[2m+1]`,
wrapping into `uio_in` past 8, which at five machines gives machine 4
`uio_in[1:0]` and collides with the control pins — and `rtl/stt_chip.v` has no
`run` flag at all. See §16.

---

### 11.2 The host byte port

**SPECIFIED.** §9 gives every machine a TX and an RX FIFO and §10 gives the host
a way to load programs, but until this section the byte itself had no path to a
pin in either direction. This settles it.

**It is serialized, because the boundary leaves no choice.** There are 8 `ui_in`
bits and §11.1 already spends seven of them while `run` = 0. An 8-bit parallel
data path does not fit, and no rearrangement makes it fit. So a byte is shifted
one bit per clock, the same way the imem, the configuration and the pin
assignment are already loaded. A transaction costs 16 clocks instead of 1, which
for a host polling a 4-deep FIFO is irrelevant: §9's binding case is a byte every
30 cycles.

**It is optional and pin-selected, not reserved.** This is the part that matters
for the budget. Reserving three pins permanently would leave 13 output-capable
pins for 15 drivers — precisely the failure §11.1 introduced `run` to avoid. So
the host port is named by selects like everything else:

<!-- BEGIN GENERATED: host-port -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| pin         | direction | assigned by                                     |
|-------------|-----------|-------------------------------------------------|
| `host_stb`  | in        | host_stb_sel, 4 bits, any input-capable pin     |
| `host_din`  | in        | host_din_sel, 4 bits, any input-capable pin     |
| `host_dout` | out       | output select code 15 on any output-capable pin |

One transaction is **16 clocks** of `host_stb`, MSB first.

| bits    | field in | meaning                                             |
|---------|----------|-----------------------------------------------------|
| `15:13` | `sel`    | state machine index                                 |
| `12`    | `wr`     | 1 = push `data` onto the selected machine's TX FIFO |
| `11:4`  | `data`   | the byte to push, MSB first                         |
| `3:0`   | `pad`    | ignored on input                                    |

| bits    | field out | meaning                                                        |
|---------|-----------|----------------------------------------------------------------|
| `15:12` | `zero`    | driven 0: `sel` has not arrived yet                            |
| `11:4`  | `rxdata`  | the selected machine's oldest RX byte, MSB first, 0 when empty |
| `3:0`   | `status`  | rx_ne, tx_full, rx_ovf, tx_unf of the selected machine         |

<!-- END GENERATED: host-port -->

`host_dout` uses **output select code 15**, which exists and means nothing
today: there are 15 drivers, numbered 0–14, and a 4-bit field. A pin whose
select is 15 currently matches no driver and reads 0. Assigning it to the host
costs no new field anywhere.

**The pin arithmetic works out exactly.** Put `host_stb` and `host_din` on
`ui_in` pins, which are input-only and are not drivers, and the only
output-capable pin the host consumes is the one carrying `host_dout`:

| | without host port | with host port on `ui_in` |
|---|---|---|
| output-capable pins | 16 | 15 |
| drivers to place | 15 | 15 |
| input-capable pins | 16 | 14 |
| machine inputs to source | 10 | 10 |

Fifteen drivers still have fifteen pins. A design that sets `host_en` = 0 pays
nothing at all and keeps all 16. The host port may equally live on `uio` pins,
since after `run` nothing is reserved and all 8 are bidirectional and
input-capable; that costs an output-capable pin per `uio` pin used for input,
which is why `ui_in` is the recommended placement.

**Framing.** `host_stb` gates the shift: on each rising clock edge where the
selected strobe pin reads 1, one bit enters on `host_din` and one bit leaves on
`host_dout`. Sixteen such clocks are one transaction. The chip counts them
itself, so the host does not send a frame delimiter; lowering `host_stb`
mid-frame abandons the transaction and the counter resets.

Both directions carry useful traffic in the same 16 clocks. `sel` arrives first
so that by the time the data field is going out, the chip knows which machine's
RX FIFO to read; `status` goes out last, when everything it reports is known.
The four leading output bits are driven 0 because `sel` has not arrived yet, and
carry no information.

**Effects land at the end of the frame, not during it.** On the sixteenth clock:
if `wr` = 1 and the selected TX FIFO is not full, `data` is pushed; if the
selected RX FIFO was not empty, the byte just shifted out is popped. An
abandoned frame has no effect. 

**A write onto a full TX FIFO is dropped, and the host finds out in the same
frame.** §9 drops the incoming byte rather than the oldest queued one, and the
TX FIFO's overflow flag is not among the four status bits. What the host gets
instead is `tx_full` in that frame's own `status`, captured **before** the write
lands: if it reads 1, the write just sent was dropped. That is enough for flow
control and costs no extra pin, but it is a report after the fact, not a
handshake — a host that wants never to lose a byte leaves one frame of slack,
writing only when the previous frame reported `tx_full` = 0.

**Reading an empty RX FIFO returns zero and does not pop.** The host
distinguishes that from a genuine 0x00 byte by the `rx_ne` bit in `status`,
which reports the state **before** the frame's pop. This is the same choice §9
makes for `load` on an empty FIFO: report it, do not invent data.

**IMPLEMENTED in `rtl2/stt_hostport.v`,** with the pin selects in
`rtl2/stt_iomux.v`, and verified through the real boundary by
`rtl2/tb/test_hostport.py`.


## 12. Memory organization

**SPECIFIED.** One state machine's imem holds **32 rows of 32 bits**, built from
**two `CFGMEM_IHP16` tiles** of 16 words × 32 bits each. The row index selects
the tile by its high address bit and the word within it by the low four.

**SPECIFIED.** Reads are **asynchronous**: the row at the current index is
available in the same cycle it is addressed, which is what allows one row per
cycle (§8.1) with no fetch stage. `CFGMEM_IHP16` is a latch array and reads
asynchronously.

**SPECIFIED.** The load path that surrounds the tiles, and which the tiles do
**not** provide, is: the staging register, the bit counter, the write pointer,
the one-hot write-row decode required by the macro's `WROW` port, and the read
multiplexer across tiles. Traced to `rtl/stt_imem_cfgmem.v`.

**SPECIFIED — exceeding 32 rows.** A program of more than 32 rows is invalid.
The toolchain must reject it: `SttProgram` raises `ValueError` when given more
than `MAX_ROWS` rows.

**CURRENT BEHAVIOUR — what hardware does with a 33rd row.** The write pointer is
5 bits and wraps, so shifting in a 33rd row overwrites row 0. That is the
structural RTL's behaviour, not a decision, and an implementation that instead
ignores the write or flags an error is not violating anything stated here. See
§16.

**Depth is quantised.** The tile is 16 words, so imem depth comes in multiples
of 16. A program needing a 33rd row does not cost one more row, it costs a third
and fourth tile. The consequences are in `row-format-decision.md` §5.2 and §5.4.

---
---

# Informative sections

**Nothing below this line is normative.** §13–§15 record what is currently true
and how to check it; §16 records what this specification does not settle. An
implementation is judged against §1–§12.

---

## 13. Reference programs (informative)

Six programs encode and pass against the device models at the frozen row format.
Measured with `Format("single5", "grouped", tgt_bits=8)` and re-run through the
models on the **decoded** rows, so the encoding is proven lossless:

| program | rows | program bits | cycles/bit | result |
|---|---|---|---|---|
| UART TX | 5 | 160 | 2 | PASS |
| UART RX | 8 | 256 | 3 | PASS |
| SPI mode 0 | 8 | 256 | 6.525 | PASS |
| I²C master | 22 | 704 | 5.875 | PASS |
| USB LS token TX | 16 | 512 | 5 | PASS |
| JTAG TAP | 25 | 800 | — | PASS |
| **total** | | **2688** | | |

**The worst case is JTAG at 25 rows of 32.** The binding resource is rows, and
what consumes them is the single-pin-write rule of §7: a TAP walk must move TMS,
TDI and TCK, and each costs a row. Bit-loop protocols are cheap in rows;
state-machine protocols are not.

Reproduce with `cd isa_bench && python3 widthsweep.py` and
`python3 jtag_bench.py`.

---

## 14. Implementation constraints (informative)

These are properties of the target process and flow, not of the ISA. They are
recorded because they constrain any implementation of §12. Full detail is in
`pdn_test/README.md` and `row-format-decision.md` §5.4.

**Macro placement is quantised, and this is the load-bearing physical
constraint of the whole design.** Get it wrong and nothing else matters: the
power grid is sourceless, IR-drop analysis cannot run, and the design cannot be
signed off. It is stated first here because it was the single hardest thing to
find.

A `CFGMEM_IHP16` tile carries its power on **Metal4**, the same layer as the
Tiny Tapeout PDN's only stripes, and pdngen trims its stripes around macros. A
tile's power pins are reached only by a stripe running over them, which an
`ExtendPowerStripes`-style step must draw back.

**What must land on the grid is the macro's POWER PIN COLUMNS, not the macro
origin.** This distinction is the whole constraint. A stripe drawn on a pin
column that coincides with no tile stripe gets no rail vias and is electrically
isolated — and because every such stripe is isolated, the power network has no
path to a source at all.

| parameter | value | why |
|---|---|---|
| `FP_PDN_VPITCH` | 44.96 | the tile's own VPWR column pitch |
| `FP_PDN_VSPACING` | 3.52 | tile VPWR→VGND centres are 5.62 µm apart, minus the 2.1 µm stripe width |
| macro x origin | `TILE_X0 - PIN_OFF` | **derived, never chosen** |
| `TILE_X0` | 53.99 | pdngen's first vertical stripe on this die |
| `PIN_OFF` | 11.44 | first VPWR pin, macro-relative, from `CFGMEM_IHP16.lef` |

Measured both ways on the five-machine design, changing nothing but the macro x:

| | 45.43 (off grid by 2.88 µm) | 42.55 (on grid) |
|---|---|---|
| plugin alignment warnings | 143 | **0** |
| `PSM-0038` unconnected shapes | 25 | **0** |
| `PSM-0069` | **fails — IR drop cannot run** | absent |
| worst-case IR drop | unmeasurable | **1.92e-04 V (0.02%)** |
| `design__lvs_error__count` | 2 | **0** |
| `magic__drc_error__count` | 0 | 0 |
| Metal4 routing resource | 95,479 | **105,560 (+10.6%)** |
| Metal2 / Metal3 GRT overflow | 1174 / 389 | **1107 / 352** |

So the misalignment cost routing resource as well as power connectivity, and the
aligned design is the first in either row format to report **zero on every
signoff check**.

Two warnings for anyone re-deriving this:

- **A constant from another floorplan is not a constant.** The offset was
  exactly 2.88 µm = `CORE_X0` = `LEFT_MARGIN_MULT` × `SITE_W`, because `X0` was
  carried over from `pdn_test`, whose core origin differs. It is now derived
  from the stripe grid and the LEF, with an assertion in
  `floorplan/gen_config.py` that fails naming the offending pin column.
- **Asserting that the macro ORIGIN is on a grid is not enough.** The origin was
  on its own grid the whole time. Only the pin columns matter.

**The PDN needs a non-default flow.** An `ExtendPowerStripes`-style step must run
after `OpenROAD.GeneratePDN` to draw stripes back across the pin columns, and
`PDN_MACRO_CONNECTIONS` must **not** be set — it makes pdngen build a per-macro
grid that is necessarily empty at that point and fails hard. With the recipe in
`pdn_test/`, one state machine with two tiles hardens with zero power-grid
violations, zero DRC errors and LVS reporting "Circuits match uniquely".

**Target clock, and what STA says about it.** The Tiny Tapeout template sets
`CLOCK_PERIOD` to 20 ns, i.e. **50 MHz**. That target is **not met worst-case**,
and grid alignment — the constraint above — is what costs it. Post-route STA on
the five-machine format D design, changing nothing but the macro x:

| | macros off grid (45.43) | macros on grid (42.55) |
|---|---|---|
| setup, slow 1.08 V 125 °C | **+1.678 ns MET** | **−2.200 ns VIOLATED** |
| setup, typ 1.20 V 25 °C | +7.100 ns MET | +4.695 ns MET |
| hold, worst corner | +0.105 ns MET | +0.108 ns MET |
| implied worst-case Fmax | ~54.6 MHz | **~45.1 MHz** |
| max-slew violations, slow | 26 | 48 |
| max-cap violations | 7 | 13 |
| signoff DRC + LVS | LVS 2 errors, IR drop blocked | **all zero** |

**The trade is not actually a choice.** A design that cannot be signed off
cannot be taped out, so the aligned floorplan wins regardless of the 9.5 MHz.
The protocols this chip emulates have large headroom at either clock: the
fastest reference program, SPI, needs 6.525 cycles per bit.

**Attribution is measured, not assumed.** The aligned result is bit-identical at
`OPENROAD_THREADS` unset and at 4 (−2.1996929345071647 both times), so the flow
is deterministic in thread count and the loss is alignment, not flow noise.

**−2.200 ns is a violation, not merely a lower Fmax, and may not be a floor.**
`RUN_POST_GRT_DESIGN_REPAIR` and `RUN_POST_GRT_RESIZER_TIMING` were the obvious
lever, and **they were tried and made everything worse**, post-route on the same
aligned design:

| | repair off | repair on |
|---|---|---|
| setup slack, slow | **−2.200** | −2.798 |
| max slew | 48 | 97 |
| max capacitance | 13 | 22 |
| max fanout | 622 | 624 |
| router DRC | 0 | 0 |

So the resizer's post-route insertions cost delay rather than recovering it, and
the fanout tail is untouched. **−2.200 ns is the floor for this configuration**,
not an artifact of a missing repair pass, and ~45 MHz is the number.

Earlier configuration C numbers, for continuity: −1.266 ns slow, about 47 MHz,
with 115 max-fanout and an observability port that XOR-reduced every machine
into one pin. That design is not this row format and its critical paths differ.

---

## 15. Conformance (informative)

An implementation is considered correct when it passes all of:

| check | command | current result |
|---|---|---|
| Encoding matches the models | `python3 spec/conformance.py` | 55/55 entries |
| Document matches its source | `python3 spec/gen_spec.py --check` | 10/10 blocks |
| All reference programs | `cd isa_bench && python3 bench.py` | 15 runs PASS, 0 FAIL |
| JTAG | `cd isa_bench && python3 jtag_bench.py` | PASS, 25 rows |
| Mutation score ≥ 85% | `cd isa_bench && python3 mutate.py --gate` | 89.1% (312/350) |

**The mutation floor is the important one.** A benchmark suite that cannot fail
proves nothing, so `mutate.py` corrupts each program one point at a time — wrong
test code, wrong branch mode, shifted target, dropped or added action, wrong pin
op or slot — and requires the benchmarks to catch them. The gate also fails if
the mutant *count* drops, which catches a benchmark being removed (that would
raise the percentage while testing less).

**Timing assertions are part of conformance.** UART TX and USB require zero
jitter; SPI and I²C require every clock phase to last at least its nominal
minus a stated tolerance. These were added after the suite revealed that SPI and
I²C had never checked bit timing at all.

Row-order mutants are reported separately and excluded from the score: branch
targets resolve by name, so most adjacent swaps produce a semantically identical
program.

---

## 16. Open items and known limits (informative)

Everything this specification does not settle. Each entry says what is missing
and where the evidence stops.

### 16.1 Not specified — an implementation must choose, and record its choice

| item | what is missing | where |
|---|---|---|
| **Timer width** | `tcount` is an unbounded integer in the models. The structural RTL uses 16 bits. Must cover the required reload period `P`. | §2, §8.4 |
| **Test codes 11–15** | Unassigned. The models would raise on decode. Code 10 and pin op code 7 are now implemented (§9). | §4, §7 |
| **A 33rd row in hardware** | The toolchain rejects it. The structural RTL's 5-bit write pointer wraps and overwrites row 0. | §12 |
| **Live reprogramming** | §11.1 specifies that the `run` flag is cleared only by `rst_n`, so reprogramming means asserting reset. What a machine does on the first cycle after a reload short of reset is still undefined. | §10, §11.1 |
| **Power-up before the first clock edge** | Output pin state between power-up and reset is not modelled. | §11 |

### 16.2 Specified but unverified

| item | status |
|---|---|
| **Format D is hardened** | RUN, at five machines, grouped macros, density 60. Post-route **`route__drc_errors` = 0**, zero antenna violations, 59.4% instance utilization (40.3% standard cell), and all ten CFGMEM macros geometrically verified as powered from the routed DEF (`pdn_test/verify_macro_power.py`). Setup **meets** 50 MHz at every corner: worst slack **+1.678 ns** slow, +7.100 typ, +10.116 fast. Hold meets everywhere, worst slack +0.105 ns. The flow stops where configuration C's did, at `PSM-0069` IR-drop connectivity on `VPWR` — a plugin gap, not a property of the design (`floorplan/README.md`). |
| **D is bigger than C, and faster** | Synthesis at five machines: D 189,435 µm² and 1862 flops, against C's 152,039 µm² and 1565. `docs/row-format-decision.md` §2 predicted the opposite, because it priced the §9 units as shared; they cannot be (§9). Timing went the other way: C missed 50 MHz post-route by −1.266 ns, D makes it by +1.678 ns, which is what removing the palette lookup from the critical path buys. |
| **Slew, capacitance and fanout** | Not clean on the signed-off five-machine D design, post-route at the slow corner: **48 max-slew**, **13 max-capacitance**, **622 max-fanout**. Routing, setup/hold and all signoff checks are clean; these are not. Broken down rather than totalled: **320 of the 622 fanout violations are one repeated structure inside the vendored macro** — `SLICE[n].ROW_AND` and `SLICE[n].SELBUF`, 16 slices x 2 cells x 10 instances, every one driving 33 loads against a limit of 8. Nothing in our netlist can buffer those. **That is CFGMEM_IHP16 as shipped, not this design**, confirmed independently: `pdn_test` — one machine, a different top and a different floorplan — reports **64** of them with two macros, same fanout 33, same limit 8, same −25 slack. It is exactly **32 per macro instance** (16 slices x 2 cells) and scales with macro count alone: 2 macros → 64, 10 macros → 320. A reviewer seeing 622 should read 320 of them as a characteristic of the vendored macro. Of the 302 that are ours, **162 are at fanout 9, one load over**, and the rest sit between 10 and 17. So this is a long tail of small overages plus one vendored structure, not a missing buffer tree: the worst single net we own is 9 loads over, and `u_imem.do_tile` — which an earlier revision of this row named as the concentration, from the *unaligned* design — accounts for exactly 1 slew, 1 cap and 1 fanout violation here. `RUN_POST_GRT_DESIGN_REPAIR` and `RUN_POST_GRT_RESIZER_TIMING` were tried and do **not** close the tail: fanout went 622 → 624 while slew went 48 → 97 and setup slack −2.200 → −2.798. A synthesis-level fanout constraint was tried and is **not** a lever: `MAX_FANOUT_CONSTRAINT` writes `set_max_fanout` into the SDC, which the OpenROAD steps consume, but never reaches yosys — taking it 10 → 8 left the netlist **byte-identical** and every metric unchanged, and the checker was already using the liberty's `default_max_fanout : 8` regardless. So the 302 are not a constraint that is merely set too loose. |
| **Every physical result describes configuration C** | Superseded for the five-machine point by the row above, and still true of everything else on record. `floorplan/gen_config.py` takes a tree argument: C generates `stt_chip_cfgmem.v` from `rtl/stt_chip.v`, the 21-bit palette format, and D hardens `tt_um_stt` from `rtl2/`. What those runs establish is a property of the physical problem and carries over: ten macros of this size place on the grid, a design of roughly this cell count routes at five machines and not at six, and the timing regime is post-route setup −1.266 ns at the slow corner (about 47 MHz) with hold met at every corner (§14). What does NOT carry over is D's own critical paths and D's own congestion. D's per-machine logic is smaller than C's (`docs/row-format-decision.md` §2), so the substitution is conservative in the direction that matters, but it is a substitution. **No `rtl2` design has ever been hardened.** |
| **Signoff DRC and LVS** | Signoff DRC is **clean in both formats**: `magic__drc_error__count` 0, `klayout__drc_error__count` 0 and `magic__illegal_overlap__count` 0, on the five-machine C design and on the five-machine D design (`RUN_2026-09-17_16-23-34`), which also has `route__drc_errors` 0 and zero antenna violations. LVS reports exactly **2 errors, both unmatched pins**, with `lvs_net_difference` 0, `lvs_device_difference` 0, `lvs_unmatched_device` 0 and `lvs_unmatched_net` 0. The two are `VPWR` and `VGND`, and D reports exactly the same: `lvs_error` 2, `lvs_unmatched_pin` 2, every other LVS count 0, `critical_disconnected_pin` 10 and `disconnected_pin` 20. Nothing about the extracted circuit differs — only the two power pins fail to match, which is the signature of the annotation gap below and not of a wiring fault. |
| **`PSM-0069`** | **FIXED.** Cause: the macro power pin columns sat 2.88 um -- exactly `CORE_X0` -- off pdngen's stripe grid, so the full-height stripes `ExtendPowerStripes` drew on them coincided with no tile stripe, got no rail vias and were electrically isolated. PSM was reporting that correctly. `X0` in `floorplan/gen_config.py` was carried over from `pdn_test`, whose core origin differs; it is now derived as `TILE_X0 - PIN_OFF` and an assertion fails loudly if any pin column leaves the grid. With the macros aligned, IR-drop analysis runs and passes: `PSM-0040 All shapes on net VPWR are connected`, worst-case IR drop **1.92e-04 V (0.02%)** on VPWR at the typical corner, total power 8.49 mW, and zero `PSM-0038`/`PSM-0039`/`PSM-0069`. The plugin printed `pin column at x=... is 2.880 um off the nearest tile stripe` for all 24 columns in every affected run, in both C and D, and it went unread. |
| **Alignment also recovered routing resource** | Aligning the macros raised Metal4 routing resource from 95,479 to 105,560 (+10.6%) and lowered global-routing overflow (Metal2 1174 -> 1107, Metal3 389 -> 352), because the off-grid stripes had been occupying tracks that duplicated pdngen's own. The misalignment cost routing resource as well as power connectivity. |
| **Device-model edge alignment** | PARTLY CLOSED, on the input side. `devices.UartDriver` now builds its waveform from bit-boundary TIMES rather than fixed-length runs, so it takes a fractional `period`, an arbitrary `phase`, and per-boundary `jitter`. With the defaults every boundary lands exactly where the old construction put it, checked at four periods by `isa_bench/phase_check.py`, so no existing result moved. Sweeping phase over a bit period does what the finding predicted: the detector's mutation kill rate goes 71.2% → 74.2%, and the two survivors it removes are exactly `drop action thalf` and `swap true/false exits` on the row that does the mid-bit alignment. Jitter of 1.5 cycles on top adds nothing further, which is worth knowing — phase was the whole gap here. The detector's negative cases are swept too -- `TogglerDriver` and `SquareDriver` take a phase as well, so "rejects this waveform" now means at every alignment rather than at one, and all seven cases still hold. The reference `uart_rx` is swept separately by `isa_bench/phase_sweep.py`: correct at 16/16 phases, and correct under per-edge jitter up to +/-8 cycles of a 32-cycle bit (25%), failing at +/-10 (31%). STILL OPEN: the §8 SPI/I²C assertions are NOT fixed by this and were mis-described as if they would be — there the machine is the master, so the waveform being measured is its own output and there is no independent phase to vary. What is unmeasured there is inter-pin skew and target response jitter, which is the row below. |
| **Inter-pin skew** | CLOSED for outputs, **statically**. Measured from the signed-off design with OpenSTA (`docs/skew-report.md`): worst skew **1.88 ns** for SPI SCK-MOSI, JTAG TCK-TDI and USB D+/D-, **1.00 ns** for I2C SCL-SDA, **0.13 ns** for JTAG TCK-TMS. Every pair passes with two to three orders of magnitude of margin, because skew does not compare against a setup requirement directly -- it erodes the separation the program creates. The SPI program puts MOSI 15 cycles (~333 ns) ahead of the SCK rise, so setup at the pin is ~331 ns against the 1 ns that a W25Q128JV requires (t_DVCH, datasheet Rev C 27 March 2018); I2C is ~1 ns of skew against t_SU;DAT of 250 ns (UM10204 Rev 7.0). Two limits: the figures are for OUTPUT pins only, so setup and hold on pins a machine reads (MISO, TDO) is still unmeasured; and they are static, because gate-level simulation annotated SDF successfully but never reached a state where the machines drive pins (`rtl2/sdf/README.md`). |
| **Multi-state-machine floorplan** | SETTLED at five, in both formats. C and D each place and route ten macros and five machines with zero router DRC errors. Six fails global routing in both: in D it finishes with **2,846 GCells of overflow** (Metal2 1,973 at 50.2% usage, Metal3 664 at 54.1%, Metal4 209 at 13.1%), against C's failure at far lower layer usage. D is larger per machine than C (§9), so six was never going to come back — and it did not. **Five machines is the answer, measured in the format that ships.** |
| **The structural RTL** | `rtl/` was written to measure area. It implements the *previous* row format (21-bit, 5-bit target, palette) and has never passed a functional test. **It is not an implementation of this specification and is not a gap in one.** Everything it lacks -- no `run` flag, an input tap that collides with the control pins, and an `stt_imem_cfgmem.v` that drives a one-hot `WROW` as though CFGMEM_IHP16 were a random-access array rather than a shift chain -- is a property of that tree, not of this document. `rtl2/` implements all of it. `rtl/stt_core` also carries `fixed_entry_i[*]`, an external-palette input that is dead with the palette gone and would appear as 13 disconnected pins in a hardened design; `rtl2/stt_core` does not have it. |

### 16.3 Reachable but unexercised

| item | status |
|---|---|
| **The 32-row ceiling** | JTAG sits at 25 of 32 and CAN at 24 of 32. The next row costs a third and fourth tile, not one row (§12). No protocol in the conformance set exceeds 32, but the ceiling does bind: the software-stuffing CAN variant in `isa_bench/can_soft.py` needs 54 rows and is unimplementable because of it. |
| **I²C START/STOP timing** | Six timer mutants survive. They change pin timing but never below the bit-period minimum, because those rows govern setup and hold intervals that I²C specifies separately (`t_SU;STA`, `t_HD;STA`, `t_SU;STO`) and the benchmark does not check. |

### 16.4 How this document can go wrong

The encoding tables cannot drift: they are generated from `spec/isa.json`, which
is checked against the models (§0). The **prose** has no such guard. One prose
assertion in this repository was carried for weeks with no code behind it and
propagated into planning before anyone checked — the history is in
`area-study.md` §8. Treat an unmarked prose claim here the same way: if it is
not marked **SPECIFIED** with a trace, or **CURRENT BEHAVIOUR**, it has not been
checked.
