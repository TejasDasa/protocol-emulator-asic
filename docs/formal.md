# Formal properties of the decode and control logic

The random-program suite reaches 100% code coverage, but coverage is sampling.
These properties are quantified over the whole input space instead, chosen so
that a rare combination being wrong is exactly the case random testing would
probably miss. The precedent is concrete: random testing found `RET` on a false
exit under `SKIP`, and a `next`-from-row-31 path that had never executed once
in this repo. Both are inside the space P1 quantifies over.

Run everything:

    make formal

That runs every property **and** every negative test, and fails if a negative
test passes. Thirty-two tasks, about a minute, so it is inside `make check`.

## Summary

| # | property | result | negative tests |
|---|---|---|---|
| P1 | the branch resolver agrees with §5 for every mode, target, row and outcome | **PROVED** | 2, both fail |
| P2 | action groups are mutually exclusive for every 32-bit row word | **PROVED** | 1, fails |
| P3 | every row word decodes to defined behaviour | **PROVED** (5 tasks) | 4, all fail |
| P4 | a FIFO's flags always match what it holds | **PROVED** (4 tasks) | 3, all fail |
| P5 | the timer is true on exactly one cycle in `P` | **PROVED** at `TIMER_W = 8`; **BOUNDED to depth 80** at the real 16 | 3, all fail |

Thirty-two tasks. Nothing failed that was supposed to pass, and nothing passed
that was supposed to fail.

### Spec gaps the exercise exposed

Three, all of the same kind, and all found by the act of stating a property
precisely enough to assert it rather than by any proof failing:

| gap | what was missing | now in |
|---|---|---|
| **target values 32–254** | §5 said the target field addresses rows, but only rows 0–31 exist, so 32–254 named nothing and the spec did not say what they meant | §16.1 |
| **`sr_width` outside 1–8** | §2 names the field and gives it no range; out of range it reads a bit of the shift register that does not exist, and the undefined value reaches a pin | §16.1 |
| **`P` below 2** | §8.4 gives the period no range; at `P = 1` a `thalf` reload underflows to 65535 and strands the timer | §16.1 |

Two of these are the same shape: **every configuration field this exercise
looked at had a range the spec never stated and the hardware never enforces.**
Two of the two examined. A small sample, but not a coincidence — §9's
`crc16_width` and `stuff_n` are the obvious next ones to check, and they have
not been.

None of the three is a bug in the sense of a program behaving wrongly. All
three are regions no encoder emits and no test in the repo reaches, which is
exactly why quantifying over the input space found them and sampling did not.

## How to read a result

| word | means |
|---|---|
| **PROVED** | Unbounded. `abc pdr` (IC3/PDR) established the property holds in every reachable state, not to some depth. |
| **BOUNDED to depth N** | Holds for all executions of N cycles from reset. Says nothing about cycle N+1. |
| **FAILED** | A counterexample exists. Reported as a design finding, not worked around. |

Everything below is PROVED unless it says otherwise. No result in this
document was taken from anything but tool output.

### Two things about this toolchain that affect what the results mean

**No SMT solver is installed** — only `yosys-abc`. So the engine is `abc pdr`,
which is complete for safety properties, and results are genuinely unbounded.
The cost is that `sby` cannot convert a counterexample into a VCD (that path
wants `yices`), so `aigsmt` is off and a failing task reports FAIL with an
AIGER witness at `<task>/engine_0/trace.aiw` rather than a waveform. For the
negative tests, which only need to establish that the assertion *can* fail,
that is sufficient.

**Undefined bits are adversarial, not zero.** The design has seven `$shiftx`
cells — variable bit-selects that can be out of range. The usual recipe is
`setundef -zero`, which decides those bits in the proof's favour. This uses
`setundef -anyseq`, which makes each one a free signal that may take a
different value every cycle. A property that passes therefore holds for *every*
value the undefined bit could take. This matters: see the §2 gap under P3.

---

## P1 — branch resolver totality

**Stated in `docs/SPEC.md` §5, before the assertion was written:**

> For every branch mode, every 8-bit target field, every current row and either
> outcome of the test, the resolver selects exactly one next row, and it is the
> one this section names: `target` is the target field taken as a row index,
> `self` is the row currently executing, `next` is `(row + 1) mod 32`, and a
> target of 255 on whichever exit the target field feeds selects the row held
> in the link register after this row's own `call`. While a machine is not
> enabled the row pointer does not move.

**Result: PROVED.**

The assertion is not a copy of the implementation. §5's table is transcribed as
*which of the three sources each exit takes* (`f_src_t`, `f_src_f`), and `next`
is written as the arithmetic the spec states rather than as the
implementation's compare-against-all-ones. The two agree only if both read the
table the same way, so a priority slip or a swapped mode column in either one
shows up. The proof quantifies over all 2^8 target values, all four modes, both
test outcomes and all 32 current rows, which is what covers target 255 in every
mode and `next` wrapping from row 31.

`row_next < 32` is also asserted, and is reported here as **structural, not a
result**: `ADDR_W` is 5, so it cannot fail. It is kept so that widening the row
pointer without widening the target handling fails loudly.

**Negative tests — both FAIL as required:**

| task | the break | why this one |
|---|---|---|
| `p1_break_ret` | `RET` resolved on the true exit whatever fed it | This is the real bug, not a synthetic one: it is what `SttCore` did until 2026-09-16, and a `SKIP` row with target 255 then returns when its test passes instead of when it fails |
| `p1_break_skip` | `SKIP`'s two exits swapped, so it behaves like `BRANCH` | Catches a transcription error in the mode table itself, which the `RET` break would not |

**Reproduce:**

    cd rtl2/formal
    sby -f stt_core.sby p1              # PASS
    sby -f stt_core.sby p1_break_ret    # FAIL, as required
    sby -f stt_core.sby p1_break_skip   # FAIL, as required

### Spec gap this exposed: target values 32–254

Stating §5 precisely enough to assert it is what surfaced this. §5 said the
target field addresses rows with 255 reserved for return — but only rows 0–31
exist (§12), so **targets 32–254 name no row and §5 did not say what they
mean.** The implementation takes the low five bits, so target 40 addresses row
8.

Nothing was wrong, and nothing was tested either: `rowenc` never emits such a
target, so only a host writing raw row words can reach one, and no test in the
repo covered the region until P1 quantified over it. It is now recorded in
§16.1 as an implementation choice rather than left as a silent one.

## P2 — action group mutual exclusion

**Stated in `docs/SPEC.md` §6.1, which already carried the rule; the sentence
added is the hardware reading of it:**

> For **every** 32-bit row word, including words no encoder would ever emit,
> the action flags a row decodes to satisfy every rule in the §6.1 table — at
> most one per group, with exactly the two exceptions named, `{clr, shift}` and
> `{crcrst, call}`.

**Result: PROVED**, over all 2^32 row values.

Worth being precise about what this does and does not establish. Mutual
exclusion *between* groups is structural: the groups are separate bit fields,
so nothing could make `sr` and `c1` collide. What the proof actually checks is
*within* a group, and there the content is real — each flag is a comparison
against a constant from the generated `stt_isa.vh`, so the property holds only
if those constants are distinct and each flag names the right ones. A
duplicated code out of `gen_isa_vh.py`, or a stray extra term in a comparison,
makes two flags in one group fire together, and the `if / else if` chains
downstream then silently drop one of the two actions rather than failing.

One assertion is stated separately because the datapath depends on it
specifically rather than on the group rule in general: `rx_data` is `sr_mid`,
the shift register before any shift, which is only the right value to `push`
because a row cannot both push and shift. That is an assumption written in a
comment in `stt_core.v`; it is now proved.

**Negative test — FAILS as required:**

| task | the break |
|---|---|
| `p2_break` | `act_push` also decoded from the combined `clr+shift` code. This is the shape a copy-paste of the adjacent `act_clr` / `act_shift` lines would produce — both of those legitimately match two codes — so one row then asserts `push`, `clr` and `shift` together |

**Reproduce:**

    cd rtl2/formal
    sby -f stt_core.sby p2          # PASS
    sby -f stt_core.sby p2_break    # FAIL, as required

## P3 — decoder totality

**Stated in `docs/SPEC.md` §4, before the assertions were written:**

> A row is 32 bits and a host loads them raw, so every one of the 2^32 words is
> reachable and the ISA has no trap. An unassigned test code does not pass: the
> row takes its false exit and performs no action and no pin write. An
> unassigned combination of pin slot and pin op writes nothing. No row word
> leaves any architectural register undefined.

**Result: PROVED**, in five parts, each a separate task so a failure names
itself. All are over all 2^32 row words.

| task | claim | result |
|---|---|---|
| `p3_a` | every variable bit-select the shift register is read through is in range | PROVED, under the precondition below |
| `p3_b` | test codes 11–15 do not pass, and such a row pushes and pops nothing | PROVED |
| `p3_c` | a single-slot pin op never disturbs a slot it does not address | PROVED |
| `p3_d` | the documented no-ops — `hold`, and `d0`/`d1` sent to a single slot rather than the pair — write nothing at all | PROVED |
| `p3_e` | a row that does not fire changes no architectural state but the row pointer and the timer | PROVED |

**Negative tests — all FAIL as required:**

| task | the break |
|---|---|
| `p3_b_break` | unassigned codes 11–15 pass instead of failing |
| `p3_c_break` | the pin write also lands on slot 0, so a row disturbs a slot it never addressed |
| `p3_d_break` | `d0` on a single slot writes rather than being the §7 no-op |
| `p3_e_break` | the shift register updates whether or not the test passed |

`p3_a`'s ability to fail is not a synthetic break — it is `p3_srwidth`, below.

**Reproduce:**

    cd rtl2/formal
    for t in p3_a p3_b p3_c p3_d p3_e; do sby -f stt_core.sby $t; done
    for t in p3_b_break p3_c_break p3_d_break p3_e_break; do sby -f stt_core.sby $t; done

### An assertion of mine that was wrong, and how it showed

`p3_e` failed when first written. The design was right and the assertion was
not: it guarded on the *current* cycle's `en` and `test_pass`, but `$stable`
compares this cycle's value against the last, and that change was decided by
the row executing one cycle earlier. Guarding on the current condition asks
whether state is stable across an edge that condition did not control — a
different claim, and a false one. The guard is now on `$past(en)` and
`!$past(test_pass)`.

Recording it because the failure was indistinguishable at first sight from a
design finding, and the rule for this work is to report a failure rather than
weaken the assertion. The way to tell them apart was to split P3 into five
tasks so the failure named which claim it was, rather than reading a
counterexample — which this toolchain cannot produce as a waveform anyway.

### Spec gap this exposed: `sr_width` has no range

**P3 cannot be proved without a precondition on the configuration**, and that
is the finding. §2 names `sr_width` but gives it no range, and nothing clamps
the 4-bit field a host loads. The shift register is 8 bits, so a width of 0 or
9–15 makes `srbit_of` select bit 15, or bits 8–14, of an 8-bit register.

`p3_srwidth` is `p3_a` with the precondition removed. It **FAILS**, which is
the formal half of the evidence. The other half is what it costs, which the
bound check alone does not show:

    cd rtl2 && iverilog -g2012 -I . -o /tmp/srw.out formal/srwidth_demo.v stt_core.v && /tmp/srw.out

    Row 0x00030030 = always / step / slot0 <- sr, MSB-first.
      sr_width=8 (in range): pin_out = 000
      sr_width=1 (in range): pin_out = 000
      sr_width=0 (NO RANGE): pin_out = 00x
      sr_width=9 (NO RANGE): pin_out = 00x
      sr_width=15 (NO RANGE): pin_out = 00x

The undefined bit reaches the pin. Nothing traps, and nothing in the repo
covered the region: every program the encoder emits sets a width in range, so
the whole lockstep and random-program apparatus only ever exercises legal
widths. Recorded in §16.1. An implementation must either bound the field or
define what out-of-range means; this one does neither yet, and that is a
decision for the design rather than something this document should invent.

## P4 — FIFO state consistency

**Stated in `docs/SPEC.md` §9, before the assertions were written:**

> At every cycle the number of bytes a FIFO holds is between zero and its
> depth. It reports `empty` exactly when it holds none and `full` exactly when
> it holds `depth`, so it never reports both, and never reports room it does
> not have or fullness it has not reached. A push onto a full FIFO and a pop
> from an empty one leave the contents and the pointers alone and set only the
> corresponding sticky flag, and neither flag clears except by reset.

**Result: PROVED**, over every sequence of pushes and pops.

| task | claim | result |
|---|---|---|
| `p4_a` | occupancy never exceeds the depth | PROVED |
| `p4_b` | `empty` and `full` match occupancy exactly, in both directions | PROVED |
| `p4_c` | overflow and underflow move no pointer and change no occupancy, and set their flag | PROVED |
| `p4_d` | the sticky flags never clear | PROVED |

The occupancy is not a signal in the design — the pointers are, and the extra
pointer bit exists precisely so their difference is the occupancy. Computing it
in the formal block is what lets the flags be checked against something other
than themselves. `p4_b` is stated as equality rather than implication on
purpose: a flag that is merely *conservative* — `full` asserted early, say —
would satisfy "never reports not-full when full" and still be wrong, and
equality catches it.

**Negative tests — all FAIL as required:**

| task | the break |
|---|---|
| `p4_break_full` | `full` computed without the wrap-bit check, the classic single-pointer-bit mistake, so an empty FIFO also reports full |
| `p4_break_ovwr` | a push accepted when full, so the FIFO holds more than its depth and overwrites an unread entry |
| `p4_break_sticky` | the overflow flag tracks the current cycle instead of latching, so a host polling a cycle late never learns a byte was lost |

**Reproduce:**

    cd rtl2/formal
    for t in p4_a p4_b p4_c p4_d; do sby -f stt_fifo.sby $t; done
    for t in p4_break_full p4_break_ovwr p4_break_sticky; do sby -f stt_fifo.sby $t; done

### Why the state invariants are checked from the first clock edge

`p4_a` and `p4_b` failed as first written, and again the design was right. They
were combinational assertions, so they were also evaluated at time zero — before
any clock edge, when `wptr` and `rptr` hold whatever the flops powered up with
and no reset has run. An occupancy of 7 in a 4-deep FIFO is not a reachable
state during operation; it is the absence of a state.

They are now clocked and guarded on `f_past_valid`, so the first checked cycle
is the one in which reset applied. This is not weakening: the evidence is that
`p4_break_full` and `p4_break_ovwr` both still **fail**, and both are built on
exactly these two assertions. A guard that had neutered them would have made
those breaks pass, which is the case `run_formal.sh` exists to catch.

## P5 — the timer free-runs on exactly one cycle in P

**Stated in `docs/SPEC.md` §8.4, before the assertions were written:**

> The counter never exceeds `P−1`. Between two consecutive ticks with no `trst`
> or `thalf` in between, exactly `P` cycles elapse, so `tmr` is true on exactly
> one cycle in `P` — for every `P`, and whether the intervening rows passed
> their tests or failed them. A `trst` or `thalf` on a row whose test failed
> changes nothing.

**Result: mixed, and the mixture is the honest part.**

| task | claim | result |
|---|---|---|
| `p5_lemma` | for `P ≥ 2`, a `thalf` reload never exceeds a `trst` reload | **PROVED**, at the real width |
| `p5_c` | a timer action on a failing row changes nothing — the counter free-runs as if it were absent | **PROVED**, at the real width |
| `p5_a_w8` | the counter never exceeds `P−1` | **PROVED for every `P`, at `TIMER_W = 8`** |
| `p5_b_w8` | exactly `P` cycles between undisturbed ticks | **PROVED for every `P`, at `TIMER_W = 8`** |
| `p5_a_bmc` | the same, at the design's real `TIMER_W = 16` | **BOUNDED to depth 80** |
| `p5_b_bmc` | the same, at the design's real `TIMER_W = 16` | **BOUNDED to depth 80** |

**Why two widths.** Bit-level PDR does not converge on a 16-bit down-counter
compared against a *symbolic* 16-bit period: it has to discover the relation
between the counter and the period one bit at a time. Measured, not assumed —
`p5_a` proves in **1 second** at `TIMER_W = 8` and does not finish in **609
seconds** at 16. Two things were tried before settling for this and neither
closed the gap: the arithmetic lemma about `thalf` was hoisted into its own
task and assumed (`p5_lemma`), and the two-point claim was restated as a
one-step inductive invariant (below). Both helped at 8 bits. Neither made 16
converge.

So what is claimed is what was obtained: the property holds **for every
period** at a reduced counter width, and for **every execution of 80 cycles**
at the real one. The reduction is in the counter's width, not in the range of
periods or of action sequences. `TIMER_W` is a parameter of `stt_core`, and the
logic is width-generic, so nothing about the property is specific to 16 — but
that is an argument, not a proof, and it is labelled as such here.

**The invariant that made it inductive.** "Exactly `P` cycles between ticks" is
a claim about two points in time. The formal block counts cycles since the last
tick (`f_since`) and remembers whether a timer action landed since then
(`f_disturbed`), so the assertion compares an independently accumulated count
against `P−1` rather than re-deriving it from the counter. Stated that way it
still is not inductive; stated as

> while nothing has reloaded the counter, `f_since + tcount == P−1`

it is, because the two move in opposite directions by one each cycle. The
property then follows in one step: at a tick the counter is zero, so `f_since`
is `P−1`. Both are asserted.

**Negative tests — all FAIL as required:**

| task | the break |
|---|---|
| `p5_break_fire` | `trst` and `thalf` apply whether or not the test passed, against §8.4's "only on a row whose test passed" |
| `p5_break_wrap` | no reload at zero, so the counter wraps to 65535 |
| `p5_break_period` | reload one short, so the period is `P−1` rather than `P` |

**Reproduce:**

    cd rtl2/formal
    for t in p5_lemma p5_c p5_a_w8 p5_b_w8; do sby -f stt_core.sby $t; done
    for t in p5_a_bmc p5_b_bmc; do sby -f stt_core_bmc.sby $t; done
    for t in p5_break_fire p5_break_wrap p5_break_period; do sby -f stt_core.sby $t; done

### An assumption that is not proved here

`always @* if (!rst_n) assume (!en);` — a core is never enabled while held in
reset. This is discharged by the enclosing design, not by this proof:
`stt_chip` drives the port from `machines_en = ena & run_dly[1]`, and `run_dly`
is cleared by `!rst_n`, so `en` is low throughout reset and for two cycles
after.

It is load-bearing, which is why it is called out. The asynchronous reset
leaves `tcount` at 0 rather than at `P−1` — the `P−1` arrives through the `!en`
branch, once the configuration has been shifted in — so a core enabled *during*
reset would hold a timer value one reload short for one cycle, and `p5_b`
fails without the assumption. The state is unreachable as `stt_core` is
instantiated, and P5 is stated for how it is instantiated. Anyone reusing
`stt_core` in another context has to honour this.

### Spec gap this exposed: `P` has no range

**P5 cannot be proved without assuming `P ≥ 2`.** Neither §2 nor §8.4 gives the
timer period a range, and nothing constrains the 16-bit field a host loads.

- `P = 0` makes "reload to `P−1`" meaningless: the counter reloads to 65535 and
  `tmr` is true once in 65536 cycles, not once in `P`.
- `P = 1` free-runs coherently — `tmr` every cycle — but `thalf` reloads to
  `P/2−1`, which underflows to 65535 and strands the timer for 65536 cycles.

`p5_period` is `p5_a` with the precondition removed. It **FAILS**. Recorded in
§16.1, alongside the `sr_width` gap P3 found — the same shape twice, and the
pattern is worth naming: **every configuration field this exercise looked at
turned out to have a range the spec never stated and the hardware never
enforces.** Two of the two examined. That is a small sample, but it is not a
coincidence, and §9's `crc16_width` and `stuff_n` are the obvious next ones to
check.

## Synthesis is unaffected

All formal code is inside `` `ifdef FORMAL ``, which production synthesis never
defines. Two checks, run by `make formal`:

1. **Permanent gate.** The synthesized netlist contains no `$assert`,
   `$assume`, `$anyseq`, `$anyconst`, `$live` or `$cover` cells.
2. **One-time, when the formal code was added.** The synthesized netlist is
   **byte-identical** to that of the file as it stood at commit `b8372af`,
   with `src` attributes stripped and both copies synthesized from the same
   path — yosys derives netlist names from the source location, so comparing
   two different paths reports naming differences rather than logic ones.

       rtl2/formal/check_synth_clean.sh --ref <b8372af copy of stt_core.v>
       OK: no assert/assume/anyseq cells in production synthesis
       OK: synthesized netlist byte-identical to ...
