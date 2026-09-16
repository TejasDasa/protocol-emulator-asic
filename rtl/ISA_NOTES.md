# STT row format — field layout and semantics

Extracted from the Python models in `isa_bench/`, which are the source of truth.
Written before any RTL. Everything below is traceable to a line of Python; the
"Ambiguities" section at the end lists what the Python does **not** pin down.

Primary sources:

| File | What it fixes |
|---|---|
| `isa_bench/rowformat.py` | the 21-bit row: field order, widths, pin encoding |
| `isa_bench/rowenc.py` | branch modes, `RET`, the 13-bit grouped action entry, `TESTS` order |
| `isa_bench/stt.py` | execution semantics of every test, action and pin op |
| `isa_bench/hybridsweep.py` | the 24 fixed + 8 loadable palette split |
| `isa_bench/programs.py` | the five benchmark programs and their core configuration |

Reproduce the palette extraction below with:

```bash
cd isa_bench && python3 ../scripts/dump_isa.py
```

## 1. Row = 21 bits

`rowformat.py::Format.encode` with `pins="single5"`, `acts="palette"`,
`storage="silicon"` appends fields in this order, and `rowenc.pack()` places the
first field at bit 0:

```
f  = [(TESTS.index(r.test), 4), (x["mode"], 2), (tgt, 5)]
f += [(SLOTS.index(slot), 2), (PINOPS.index(op), 3)]
f += [(pal.index(self.key(r)), k)]          # k = bits_for(32) = 5
```

| Bits | Width | Field |
|---|---|---|
| `[3:0]`   | 4 | test select |
| `[5:4]`   | 2 | branch mode |
| `[10:6]`  | 5 | branch target (31 = RET) |
| `[12:11]` | 2 | pin slot |
| `[15:13]` | 3 | pin op |
| `[20:16]` | 5 | action-set (palette) index |

Total 21 bits. This matches `isa_bench/README.md`
("21-bit row: test 4 | branch mode 2 | target 5 | pin slot 2 | pin op 3 |
action-set index 5") and the measured `row_width=21` in
`hybrid_results.json` / `generalization_results.json`.

## 2. Test field — 4 bits

`rowenc.py`: `TESTS = sorted(TESTS_V2)`. Alphabetical, so the codes are fixed:

| Code | Test | Condition (`stt.py::SttCore._test`) |
|---|---|---|
| 0 | `always` | `1` |
| 1 | `c2z`    | counter 2 == 0 |
| 2 | `cz`     | counter 1 == 0 |
| 3 | `fifo`   | TX FIFO not empty |
| 4 | `in0h`   | synchronized input pin 0 == 1 |
| 5 | `in0l`   | synchronized input pin 0 == 0 |
| 6 | `in1h`   | synchronized input pin 1 == 1 |
| 7 | `in1l`   | synchronized input pin 1 == 0 |
| 8 | `srbit`  | shift-register serial bit == 1 |
| 9 | `tmr`    | timer count == 0 **this cycle** (the tick) |
| 10–15 | — | not assigned by the Python |

`srbit` = `sr[w-1]` when the core is configured `shift="left"`, else `sr[0]`
(`_test` calls `_srbit`). Input pins are read through `World.read_sync`, a
2-cycle synchronizer (`isa_bench/README.md`, "Rules used").

## 3. Branch mode — 2 bits, and target — 5 bits

From the `rowenc.py` module docstring and `rowenc.rebuild`:

| Code | Name | test true | test false |
|---|---|---|---|
| 0 | `WAIT`   | target | self |
| 1 | `BRANCH` | target | next |
| 2 | `SKIP`   | next   | target |
| 3 | `STEP`   | next   | self (target field unused) |

`next` = the physically following row; the last row's `next` wraps to row 0
(`rebuild`: `nxt = names[i+1] if i+1 < len(names) else names[0]`).

Target value `RET = 31` means "return to the link register" (`rowenc.py`,
`rebuild`: `"ret" if x["target"] == RET`). `link` is written by the `call`
action.

## 4. Pin field — 2-bit slot + 3-bit op

`rowformat.py` module level:

```python
PINOPS = ["hold", "lo", "hi", "sr", "tgl", "d0", "d1"]
SLOTS  = [0, 1, 2, "pair"]
```

(Note: `rowenc.py` defines a *different*, shorter `PINOPS` list. The 21-bit
format is encoded and decoded by `rowformat.py`, so `rowformat.PINOPS` is the
one that applies. `rowenc.PINOPS` is only used by the older `OneTarget`/
`Palette` schemes in `encsweep.py`.)

Slot codes 0/1/2 address one output slot. Slot code 3 is the D+/D- pair, which
writes slots 0 and 1 together.

Op code 0 (`hold`) means **no pin write at all**, independent of the slot field
(`Format.encode` decode path: `if rest[1]: pins = {SLOTS[rest[0]]: PINOPS[rest[1]]}`).

Single-slot ops (`stt.py::step`):

| Code | Op | Effect on slot *s* |
|---|---|---|
| 0 | `hold` | no write |
| 1 | `lo`   | `pin[s] <= 0` |
| 2 | `hi`   | `pin[s] <= 1` |
| 3 | `sr`   | `pin[s] <= srbit` |
| 4 | `tgl`  | `pin[s] <= ~pin[s]` |
| 5 | `d0`   | not defined for a single slot |
| 6 | `d1`   | not defined for a single slot |

Pair ops (slot code 3), writing `(pin0, pin1)`:

| Code | Op | `(pin0, pin1)` |
|---|---|---|
| 1 | `lo`  | `(0, 0)`  — USB SE0 |
| 2 | `hi`  | `(1, 1)` |
| 3 | `sr`  | `(srbit, ~srbit)` |
| 4 | `tgl` | `(~pin0, ~pin1)` — USB NRZI transition |
| 5 | `d0`  | `(0, 1)` — USB J |
| 6 | `d1`  | `(1, 0)` — USB K |

Slot drive mode (push-pull vs open-drain) is core configuration, not a row
field: `SttCore(slots=[("sda","od"), ("scl","od")])`. In open-drain a `1`
releases the net and a `0` drives it low.

## 5. Action-set palette — 5-bit index into 32 entries

Each palette entry is a **13-bit grouped action code** (`rowenc.GROUP_BITS == 13`,
confirmed by running the model). Five mutually-exclusive groups:

| Group | Bits | Choices (code order) |
|---|---|---|
| `sr` | 3 | —, `load`, `loadk`, `loadcrc`, `clr`, `shift`, `clr+shift`, `push` |
| `c1` | 3 | —, `cload`, `cload_b`, `cload_c`, `cdec` |
| `c2` | 2 | —, `c2load`, `c2dec` |
| `tm` | 2 | —, `trst`, `thalf` |
| `xx` | 3 | —, `crcrst`, `crcstep`, `call`, `crcrst+call` |

3+3+2+2+3 = 13.

`hybridsweep.py`: `FIXED, LOADABLE, ENTRY_BITS = 24, 8, 13`. Entries 0–23 are
frozen at tapeout; entries 24–31 are loaded per program, so the loadable palette
is **8 x 13 = 104 flops**.

### The 24 fixed entries

`fixed = [()] + sorted(SINGLES) + [s for s,_ in freq.most_common(24-1-17)]`

* entry 0: the empty set
* entries 1–17: the 17 single actions, in `sorted()` order:
  `c2dec, c2load, call, cdec, cload, cload_b, cload_c, clr, crcrst, crcstep,
  load, loadcrc, loadk, push, shift, thalf, trst`
* entries 18–23: the six most frequent multi-action sets in the training
  programs. Training on all five benchmarks (`mode = "in-sample"`) gives, as a
  set:

  | # | Action set |
  |---|---|
  | 1 | `shift, cdec` |
  | 2 | `load, cload, trst` |
  | 3 | `load, cload` |
  | 4 | `shift, cdec, crcstep` |
  | 5 | `clr, shift` |
  | 6 | `loadk, cload, c2load, trst` |

  The first 18 entries are identical across every in-sample and leave-one-out
  run. The tail of six is identical for all five in-sample runs; only its
  *order* varies with `Counter.most_common` tie-breaking, which does not affect
  area. The leave-one-out runs produce different tails — see Ambiguity A3.

## 6. Execution semantics of one row

From the `stt.py` module docstring and `SttCore.step`:

> When the test passes, actions run (in the fixed order below), then pin ops
> (which see the updated shift register), then control goes to next_true.
> Otherwise nothing happens and control goes to next_false.

Action order within a cycle (`stt.py::ACT_ORDER`) — this matters because
`shift` and `crcstep` both read the shift register:

```
load, loadk, loadcrc, clr, crcrst, crcstep, shift, push,
cload, cload_b, cload_c, cdec, c2load, c2dec, trst, thalf, call
```

Because the groups are mutually exclusive, at most one of
`{load, loadk, loadcrc, clr, shift, clr+shift, push}` can appear in one row, so
the only real ordering constraint the RTL must honour is
**`crcstep` sees the pre-`shift` value of the shift register, and the pin ops
see the post-`shift` value.**

| Action | Effect |
|---|---|
| `load`    | `sr <= tx_fifo.pop()` (model errors on empty) |
| `loadk`   | `sr <= K` (config constant) |
| `loadcrc` | `sr <= (~crc) & 0x1F` |
| `clr`     | `sr <= 0` |
| `crcrst`  | `crc <= 0x1F` |
| `crcstep` | `b = srbit; crc <= (crc>>1) ^ 0x14 if (crc^b)&1 else (crc>>1)` (CRC5, reflected 0x14) |
| `shift`   | right: `sr <= (sr>>1) \| (f << w-1)`; left: `sr <= (sr<<1) \| f`; `f` from the `fill` config (`'0'`, `'1'`, or input pin 0) |
| `push`    | `rx_fifo.append(sr)` |
| `cload` / `cload_b` / `cload_c` | `cnt <= cvals[0/1/2]` (three config registers) |
| `cdec`    | `cnt <= (cnt-1) & 0xFF` |
| `c2load`  | `c2 <= c2val` (config) |
| `c2dec`   | `c2 <= (c2-1) & 0xFF` |
| `trst`    | `tcount <= P-1` |
| `thalf`   | `tcount <= P/2-1` |
| `call`    | `link <= index of this row's *false* exit` (the link row) |

### The timer runs unconditionally

This is easy to miss. The last lines of `step` are outside the `if test` branch:

```python
if new_t is not None:  self.tcount = new_t            # trst / thalf
else:                  self.tcount = self.P-1 if tick else self.tcount-1
```

So the timer free-runs and auto-reloads on every tick whether or not the row's
test passed. `trst`/`thalf` only override the reload value, and only on a row
whose test passed.

## 7. Configuration registers (not in the row, not counted in program bits)

`isa_bench/README.md`: "Program bits only; configuration registers (baud
divider, shift direction) not counted." From the `SttCore.__init__` signature:

| Config | Used by | Benchmark values |
|---|---|---|
| `period` (P) | timer reload | 32 at nominal; swept |
| `shift` | `shift`, `srbit` | `"right"` (UART, USB), `"left"` (SPI, I2C) |
| `fill` | `shift` | `"0"`, `"1"`, or input pin 0 |
| `sr_width` | shift register | 8 everywhere |
| `cload` a/b/c | `cload*` | `(8,0,0)`; USB `(8,3,5)` |
| `c2load` | `c2load` | 0; USB 6 |
| `loadk` | `loadk` | 0; USB `0x80` |
| `init_pins` | pin reset value | per protocol |
| slot modes | pin drivers | `pp` or `od` per slot |

## 8. What this means structurally for the RTL

* 2 synchronized input pins, 3 output slots (slots 0/1 also drive as a pair).
* One 8-bit shift register with left/right and a selectable fill source.
* Two 8-bit down-counters (`cnt`, `c2`) with three and one reload constants.
* One free-running down-counter timer with reload `P` and an override input.
* A 5-bit CRC5 register with a reflected-0x14 step.
* A 5-bit row pointer plus a 5-bit link register.
* A 32 x 13 action palette: 24 constant entries (combinational ROM) + 8 x 13
  flops.
* A 32 x 21 row array with a shift-in load path.

---

# Ambiguities

These are **not** resolvable from `isa_bench/`. I have taken the default in the
right-hand column so the study could proceed; every one of them is an RTL
parameter or a localparam, so changing the answer changes a number, not the
structure. Please confirm or correct.

| # | Ambiguity | Why it is ambiguous | Default taken |
|---|---|---|---|
| A1 | **Timer width.** | `SttCore.period` is a Python int with no width. The benchmarks sweep P over small values (nominal 32), but a real baud divider at an ASIC clock needs far more. This is the single largest area knob outside the imem. | `TIMER_W = 16` |
| A2 | **Counter width.** | `cdec`/`c2dec` mask with `0xFF`, which implies 8 bits, but no benchmark loads more than 8. | `CNT_W = 8` (follows the mask) |
| A3 | **Which six multi-action sets are frozen in palette entries 18–23.** | `hybridsweep.py` derives them from the training set. In-sample (train on all five) gives one stable set of six; each leave-one-out run gives a different set. A tapeout must freeze exactly one. | the in-sample six, listed in §5 |
| A4 | **Row 31 is not addressable.** | `RET = 31` occupies the top target code, so with `MAX_ROWS = 32` a 32-row program cannot branch to row 31 — only fall into it. Is the usable row count 31, or should RET be encoded another way? | 32 rows implemented; row 31 reachable only by fall-through |
| A5 | **Undefined encodings.** | Test codes 10–15 and pin-op code 7 are unassigned; the Python decoder would raise. `d0`/`d1` (codes 5/6) are undefined for a single slot. | test 10–15 -> false; pin op 7 -> hold; `d0`/`d1` on a single slot -> hold |
| A6 | **Host FIFO depth and ownership.** | `World.tx_fifo`/`rx_fifo` are unbounded Python deques. The task's block list puts no FIFO in the datapath. | no FIFO in the measured blocks; `load`/`push` are strobes and data buses at the top-level boundary |
| A7 | **How the 8 loadable palette entries are loaded.** | Not modelled at all — `hybridsweep.py` only counts their 104 bits. | same serial shift-in chain as the row array, appended after the rows |
| A8 | **Shift-register width.** | 8 in all five benchmarks, but `sr_width` is a parameter and `loadcrc` only writes 5 bits. | `SR_W = 8` |
