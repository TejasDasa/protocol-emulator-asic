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

| code | name     | true when                                            |
|------|----------|------------------------------------------------------|
| 0    | `always` | Unconditionally true.                                |
| 1    | `c2z`    | True when counter 2 reads zero.                      |
| 2    | `cz`     | True when counter 1 reads zero.                      |
| 3    | `fifo`   | True when the TX FIFO is not empty.                  |
| 4    | `in0h`   | True when synchronized input 0 reads 1.              |
| 5    | `in0l`   | True when synchronized input 0 reads 0.              |
| 6    | `in1h`   | True when synchronized input 1 reads 1.              |
| 7    | `in1l`   | True when synchronized input 1 reads 0.              |
| 8    | `srbit`  | True when the shift register serial bit reads 1.     |
| 9    | `tmr`    | True on the cycle the timer reaches zero (the tick). |

<!-- END GENERATED: tests -->

Traced to `SttCore._test` in `isa_bench/stt.py`. Codes 10–15 are not assigned;
see §16.

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

**CURRENT BEHAVIOUR — `next` from the last row.** In the models the encoder
wraps `next` to row 0 at the end of the program (`rowenc.rebuild`), but that
depends on the program length, which the hardware does not know. **No benchmark
exercises it**: all six reference programs end on a `WAIT` row, whose exits are
both explicit. An implementation must define this and it is not defined here.
See §16.

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

| code | actions        | meaning                                                              |
|------|----------------|----------------------------------------------------------------------|
| 0    | —              | No shift-register action.                                            |
| 1    | `load`         | Load a byte popped from the TX FIFO.                                 |
| 2    | `loadk`        | Load the configured constant K.                                      |
| 3    | `loadcrc`      | Load the complement of the CRC register, 5 bits.                     |
| 4    | `clr`          | Clear to zero.                                                       |
| 5    | `shift`        | Shift one place in the configured direction, inserting the fill bit. |
| 6    | `clr`, `shift` | Clear then shift.                                                    |
| 7    | `push`         | Push the shift register to the RX FIFO.                              |

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

| code | actions          | meaning                                            |
|------|------------------|----------------------------------------------------|
| 0    | —                | No action.                                         |
| 1    | `crcrst`         | Reset the CRC register to all ones.                |
| 2    | `crcstep`        | Advance the CRC by the shift register serial bit.  |
| 3    | `call`           | Write the row's false exit into the link register. |
| 4    | `crcrst`, `call` | Reset the CRC and link, in that order.             |

<!-- END GENERATED: action-groups -->

Traced to `rowenc.GROUPS`.

### 6.1 Which action sets are encodable

**SPECIFIED.** Groups are mutually exclusive internally. An action set is
encodable in one row if and only if it satisfies every rule below. This is the
rule an implementer applies; it is not a statistic.

<!-- BEGIN GENERATED: action-rule -->
<!-- generated from spec/isa.json by spec/gen_spec.py -- do not edit by hand -->

| group | rule                                                                                                           |
|-------|----------------------------------------------------------------------------------------------------------------|
| `sr`  | at most one of `clr`, `load`, `loadcrc`, `loadk`, `push`, `shift`; except {`clr`, `shift`} may appear together |
| `c1`  | at most one of `cdec`, `cload`, `cload_b`, `cload_c`                                                           |
| `c2`  | at most one of `c2dec`, `c2load`                                                                               |
| `tm`  | at most one of `thalf`, `trst`                                                                                 |
| `xx`  | at most one of `call`, `crcrst`, `crcstep`; except {`crcrst`, `call`} may appear together                      |

An action set is encodable in one row if and only if it satisfies every rule above. That makes **1800** distinct action sets reachable.

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

`load` → `loadk` → `loadcrc` → `clr` → `crcrst` → `crcstep` → `shift` → `push` → `cload` → `cload_b` → `cload_c` → `cdec` → `c2load` → `c2dec` → `trst` → `thalf` → `call`

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

| code | op     | single slot                                          | pair slot (code 3)        |
|------|--------|------------------------------------------------------|---------------------------|
| 0    | `hold` | No write. The slot keeps its value.                  | No write.                 |
| 1    | `lo`   | Drive 0.                                             | Drive (0,0).              |
| 2    | `hi`   | Drive 1.                                             | Drive (1,1).              |
| 3    | `sr`   | Drive the shift register serial bit.                 | Drive (srbit, NOT srbit). |
| 4    | `tgl`  | Invert the slot.                                     | Invert both slots.        |
| 5    | `d0`   | UNSPECIFIED for a single slot (see SPEC section 16). | Drive (0,1).              |
| 6    | `d1`   | UNSPECIFIED for a single slot (see SPEC section 16). | Drive (1,0).              |

<!-- END GENERATED: pin-ops -->

Traced to `rowformat.PINOPS`, `rowformat.SLOTS` and the pin handling in
`SttCore.step`.

**SPECIFIED.** `hold` (code 0) means no write at all, independent of the slot
field. A row that performs no pin operation encodes `hold`.

**SPECIFIED.** Slot drive mode is per-slot configuration, not a row field. In
**open-drain** mode a 1 releases the net and a 0 drives it low; in **push-pull**
mode both values are driven. Traced to the `mode` handling at the end of
`SttCore.step`.

**CURRENT BEHAVIOUR — `d0` and `d1` on a single slot.** Codes 5 and 6 are
defined only for the pair slot. `SttCore.step` handles them in the pair branch
only, so on a single slot they fall through and write nothing. That is an
artifact of the model's structure, not a decision. See §16.

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

## 9. Shared units

**SPECIFIED — CRC5, per state machine.** Each state machine has a 5-bit CRC
register, reset to `0x1F`, driven by three actions:

| action | effect |
|---|---|
| `crcrst` | Set the register to `0x1F`. |
| `crcstep` | Advance by the shift register serial bit: if `(crc XOR bit)` is odd, `crc = (crc >> 1) XOR 0x14`, else `crc = crc >> 1`. |
| `loadcrc` | Load the shift register with `(NOT crc) AND 0x1F`. |

This is a reflected CRC5 with polynomial `0x14`, which is the USB CRC5
(x⁵+x²+1, reflected). Traced to `SttCore.step`. It is fixed, not programmable.

**CURRENT BEHAVIOUR — the wider shared units.** `rtl/` also contains a 16-bit
programmable-polynomial CRC/LFSR (`crc_lfsr16.v`), a configurable bit stuffer
(`bit_stuffer.v`), shared TX/RX FIFOs with a round-robin arbiter
(`stt_hostbuf.v`) and a pin multiplexer (`stt_iomux.v`). These were written and
synthesised to price them, and `row-format-decision.md` §6 recommends keeping
the CRC unit and the stuffer on capability grounds.

**They have no model in `isa_bench/`, no benchmark uses them, and no row field
reaches them.** How a program starts a CRC over the wider unit, or routes a bit
through the stuffer, is **not specified** — no mechanism for it exists in the
row format described in §3. Their RTL interfaces are recorded in the source
files. Until a row field or host command reaches them, an implementation that
omits them is not violating this specification. See §16.

**CURRENT BEHAVIOUR — FIFOs.** The models use unbounded queues, so no depth is
specified. `load` on an empty TX FIFO raises an error in the model
(`"stt: load from empty FIFO"`); what hardware does is not specified. `push`
onto a full RX FIFO is not modelled at all. See §16.

---

## 10. Host interface

**SPECIFIED — program load.** The imem is written by a **serial shift-in**. The
host presents one bit per cycle with the load enable asserted. A staging
register assembles a row least-significant bit first, matching `rowenc.pack`;
when the bit counter wraps, the staged row is written to the address in the
write pointer and the pointer advances. Traced to `rtl/stt_imem.v` and
`rtl/stt_imem_cfgmem.v`, whose load paths are identical.

Loading therefore starts at row 0 and proceeds in order; there is no random
access and no read-back path.

**SPECIFIED — state machine select.** When more than one state machine is
present, `uio_in[7:5]` selects which one the load enables address, so exactly
one is programmed at a time. Traced to `rtl/stt_chip.v`.

> This is not only an interface convenience. Without a per-state-machine select
> every instance receives the same serial stream and holds identical state,
> which lets synthesis merge them — a real measurement error found and
> documented in `area-study.md`.

**SPECIFIED — configuration load.** The per-state-machine configuration of §2 is
written by the same kind of serial chain, with its own enable.

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

---

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

**Macro placement is quantised.** A `CFGMEM_IHP16` tile carries its power on
**Metal4**, the same layer as the Tiny Tapeout PDN's only stripes, and pdngen
trims its stripes around macros. A tile's power pins are reached only by a
stripe running over them, so tile placement must land on the stripe grid:

| parameter | value | why |
|---|---|---|
| `FP_PDN_VPITCH` | 44.96 | the tile's own VPWR column pitch |
| `FP_PDN_VSPACING` | 3.52 | tile VPWR→VGND centres are 5.62 µm apart, minus the 2.1 µm stripe width |
| tile x origin | on the 44.96 µm grid | so pin columns coincide with stripes |

**The PDN needs a non-default flow.** An `ExtendPowerStripes`-style step must run
after `OpenROAD.GeneratePDN` to draw stripes back across the pin columns, and
`PDN_MACRO_CONNECTIONS` must **not** be set — it makes pdngen build a per-macro
grid that is necessarily empty at that point and fails hard. With the recipe in
`pdn_test/`, one state machine with two tiles hardens with zero power-grid
violations, zero DRC errors and LVS reporting "Circuits match uniquely".

**Target clock.** The Tiny Tapeout template sets `CLOCK_PERIOD` to 20 ns, i.e.
**50 MHz**. **Fmax is not verified**: no STA has been run on this design at any
frequency. 50 MHz is the target, not a result.

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
| **FIFO depth** | The models use unbounded queues. No depth, and no behaviour for `push` onto a full RX FIFO. | §2, §9 |
| **`load` from an empty TX FIFO** | The model raises an error; hardware behaviour is undefined. | §9 |
| **`next` from the last row** | The encoder wraps to row 0 using the program length, which hardware does not know. No reference program exercises it — all six end on a `WAIT` row. | §5 |
| **`d0`/`d1` on a single slot** | Defined only for the pair slot. On a single slot the model writes nothing, as a side effect of its structure. | §7 |
| **Test codes 10–15, pin op code 7** | Unassigned. The models would raise on decode. | §4, §7 |
| **A 33rd row in hardware** | The toolchain rejects it. The structural RTL's 5-bit write pointer wraps and overwrites row 0. | §12 |
| **Run/halt and live reprogramming** | Whether a state machine may be reprogrammed while running, and its state on the first cycle after a reload. | §10 |
| **Power-up before the first clock edge** | Output pin state between power-up and reset is not modelled. | §11 |

### 16.2 Specified but unverified

| item | status |
|---|---|
| **Static timing analysis** | Never run, at any frequency. 50 MHz is a target. This is the largest verification gap. |
| **Inter-pin skew** | The model has no pin path. Skew between a clock and its data — SCK/MOSI, SCL/SDA — is the failure mode that matters in silicon and is entirely unmeasured. |
| **Multi-state-machine floorplan** | Single-machine integration is demonstrated and LVS-clean. Several machines with their tiles on the placement grid, each machine's logic near its own tiles, is untested. |
| **The structural RTL** | `rtl/` was written to measure area. It implements the *previous* row format (21-bit, 5-bit target, palette) and has never passed a functional test. It is not an implementation of this specification. |

### 16.3 Reachable but unexercised

| item | status |
|---|---|
| **The wider shared units** | `crc_lfsr16`, `bit_stuffer`, `hostbuf`, `iomux` exist in RTL and were priced, but no row field reaches them and no benchmark uses them (§9). |
| **The 32-row ceiling** | JTAG sits at 25 of 32. The next row costs a third and fourth tile, not one row (§12). No protocol has been written that exceeds 32. |
| **CAN** | A device model exists (`isa_bench/jtag_can.py`); no program was written. The obstacle is recorded: there is no "same as the previous bit" test, so in-loop run detection for bit stuffing needs duplicated paths. |
| **I²C START/STOP timing** | Six timer mutants survive. They change pin timing but never below the bit-period minimum, because those rows govern setup and hold intervals that I²C specifies separately (`t_SU;STA`, `t_HD;STA`, `t_SU;STO`) and the benchmark does not check. |
| **`fixed_entry_i[*]`** | `stt_core` carries an external-palette input used only when `EXT_FIXED=1`. With the palette gone it is dead, and it appears as 13 disconnected pins in a hardened design. A real multi-machine top must not expose it. |

### 16.4 How this document can go wrong

The encoding tables cannot drift: they are generated from `spec/isa.json`, which
is checked against the models (§0). The **prose** has no such guard. One prose
assertion in this repository was carried for weeks with no code behind it and
propagated into planning before anyone checked — the history is in
`area-study.md` §8. Treat an unmarked prose claim here the same way: if it is
not marked **SPECIFIED** with a trace, or **CURRENT BEHAVIOUR**, it has not been
checked.
