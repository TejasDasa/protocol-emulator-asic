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
test passes. Whole set: about 2 seconds, so it is inside `make check`.

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
