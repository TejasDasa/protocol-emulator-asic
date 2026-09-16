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
| **row** | One 32-bit instruction word, and the unit of execution. One row is evaluated per core clock cycle. |
| **state machine** | One independent instance of the programmable engine, with its own imem, registers and pins. Abbreviated **SM** only in tables. |
| **imem** | The instruction memory of one state machine: 32 rows, held in two **tile**s. |
| **tile** | One `CFGMEM_IHP16` macro: 16 words of 32 bits. Two tiles make one imem. |
| **action group** | One of the five mutually-exclusive fields (`sr`, `c1`, `c2`, `tm`, `xx`) that together encode a row's actions in 13 bits. |
| **test code** | The 4-bit field selecting the condition evaluated on entry to a row. |
| **host** | Whatever drives the chip's pins to load programs and exchange bytes. Off-chip. |
| **core clock cycle** | One period of the chip's single clock input. The unit of all timing in §8. |

Terms deliberately **not** used: *instruction* (say row), *opcode* (say test
code or action group), *word* (say row or tile word), *core* (say state
machine), *palette* (it does not exist — see §6).

---

## 2. Programmer's model

**SPECIFIED.** Every piece of architectural state in one state machine:

<!-- BEGIN GENERATED: state -->
<!-- END GENERATED: state -->

Reset values are traced to `SttCore.__init__` in `isa_bench/stt.py`.

**SPECIFIED.** Per-state-machine configuration, set at program load and not
encoded in rows:

<!-- BEGIN GENERATED: config -->
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
<!-- END GENERATED: row-format -->

Traced to `rowformat.Format.encode` with `pins="single5"`, `acts="grouped"`,
`tgt_bits=8`, and `rowenc.pack`, which places the first field at bit 0.

---

## 4. Test codes

**SPECIFIED.** The test code selects one condition, evaluated **on entry to the
row**, before any of the row's actions take effect.

<!-- BEGIN GENERATED: tests -->
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
<!-- END GENERATED: action-groups -->

Traced to `rowenc.GROUPS`.

### 6.1 Which action sets are encodable

**SPECIFIED.** Groups are mutually exclusive internally. An action set is
encodable in one row if and only if it satisfies every rule below. This is the
rule an implementer applies; it is not a statistic.

<!-- BEGIN GENERATED: action-rule -->
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
<!-- END GENERATED: pin-slots -->

**SPECIFIED.** Operations. Slot code 3 selects the D+/D− pair, which writes
slots 0 and 1 together and gives the pair-specific meanings in the right-hand
column:

<!-- BEGIN GENERATED: pin-ops -->
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
