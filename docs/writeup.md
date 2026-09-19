# A protocol emulator on 6×4 tiles: the argument

Draft. This is the case for the design, not a tour of it. `docs/SPEC.md` is the
specification, `docs/area-study.md` the measurements, `docs/row-format-decision.md`
the format decision.

---

## 1. One machine, twelve rows, watching a wire

A state machine on this chip watches a pin it never drives, and decides whether
what it sees is UART:

> a falling edge; the line still low half a bit later, so not a glitch; eight
> bit times; a stop bit high where one belongs — eight frames in a row.

That program is **12 rows**. It rejects constant levels, square waves and random
toggling, and it confirms a real transmitter at any phase, with jitter. Five
such machines run concurrently, each testing a different candidate baud.

The chip is a **protocol emulator**: five independent state machines on a Tiny
Tapeout 6×4 die in IHP 130 nm, each executing one 32-bit row per clock, driving
and reading pins directly. Programs load at run time over serial chains, so the
silicon is not committed to any protocol at tape-out. Six run cycle-exact
against device models today — UART TX and RX, SPI mode 0, I²C master, USB
low-speed token TX, JTAG — plus CAN, which §3 is about.

## 2. The ceiling is the design

A row costs exactly one clock. There is no fetch, no pipeline, and **no stall** —
a machine cannot wait, cannot be back-pressured, and cannot take two cycles for
one row. Everything interesting about this design follows from that.

It is what makes the machine cheap enough to replicate five times. It is why
bit-level timing is exact rather than approximate. And it imposes a hard limit
that is unusual in a programmable device: **a program is at most 32 rows**, and
a protocol either fits or it does not exist.

That limit is not a budget to be managed; it is a boundary with things on both
sides of it, and this submission reports measurements from both:

| | rows |
|---|---|
| UART detector — decides what a wire is carrying | **12** of 32 |
| CAN 2.0A transmitter, with the §9 wider units | **24** of 32 |
| JTAG — the longest reference program | 25 of 32 |
| CAN 2.0A, attempted without those units | **54** — does not exist |

The same no-stall rule has a second consequence, derived rather than assumed
(§8.1.1): **nothing a row can invoke may be shared between machines.** A shared
resource can be reached by N rows on the same cycle, serving them needs
arbitration, arbitration means a machine waits, and there is nowhere for that
wait to go. That is why the FIFOs, the CRC units and the bit stuffer all
replicate, and why the price in §3 is per machine rather than per chip.

This document argues three things, in descending order of confidence:

1. **A 32-bit row ISA emulates real protocols at line rate** — seven programs,
   cycle-exact against models and against RTL.
2. **The chip can decide what a wire is carrying, not only speak it** — the
   detector above, with a measured capture window of −5% to +10% of baud, so
   five machines cover a 1.77× range.
3. **Two of the shared units are preconditions, not optimisations** — §3, which
   is the load-bearing claim and the one most worth attacking.

## 3. CAN: an impossibility argument, and an attempt to break it

The decision to keep a wide programmable CRC and a bit stuffer was made on
capability grounds and was, until recently, the least-supported decision in the
project. Both units were specified, priced and unused.

**The claim.** CAN 2.0A cannot be implemented on this ISA without them.

Most hardware justifications are cost arguments, which invite "but how much?".
This one is an impossibility argument, which invites "prove it" — so the
falsification attempt is the evidence.

**The attempt.** Write CAN using only the codes that existed before the units.
`isa_bench/can_soft.py` does this and is measured, not estimated.

**Result 1 — bit stuffing in rows costs 54 rows against a 32-row ceiling.**

The reason is one missing test. CAN stuffs after five identical bits, so a
program must know whether the bit it is about to send *equals the one it just
sent*. `srbit` reports the value of the next bit. **Nothing reports the previous
one**, and no test compares them — the eleven live tests are listed above.

So the previous bit has to be remembered, and there is no register free to
remember it in: `sr` holds the data being shifted, `cnt` the bit position, `c2`
the byte count, and the CRC registers their own state. The only remaining place
to store it is **the program counter itself** — the program forks into two
parallel chains, one meaning "the last bit was 0" and one meaning "the last bit
was 1".

The run length has nowhere to live either, so each chain unrolls into five
states. That gives **10 states**, `(last bit, run length)` for bit ∈ {0,1} and
run ∈ 1..5:

```
          run=1     run=2     run=3     run=4     run=5
last=0    S0_1  →   S0_2  →   S0_3  →   S0_4  →   S0_5 → insert 1
            ↑ ↓       ↑ ↓       ↑ ↓       ↑ ↓
last=1    S1_1  →   S1_2  →   S1_3  →   S1_4  →   S1_5 → insert 0
```

Every state needs the same four rows: wait for the bit boundary (`tmr`), test
`srbit`, and *two* call sites — because the destination differs depending on
whether the next bit continues the run or breaks it, and a row has one pair of
exits. The emit-and-shift work itself is shared as a subroutine.

**The duplication is control flow, not storage, which is why more registers
would not fix it.** A spare counter could hold the run length, but the fork by
polarity would remain: the program still cannot ask whether this bit matches
the last one, so it still has to be in a different place depending on the
answer. What is missing is a *test*, not a register. This ISA could have spent
a test code on “same as the previous bit” and did not — the eleven codes went
elsewhere — so the cost below is the price of that choice, not an oversight.

| | rows |
|---|---|
| the 10 `(last bit, run)` states | **34** |
| run of 5 reached: insert the complement | 2 |
| shared emit subroutine | 3 |
| byte boundary and reload | 3 |
| arm: reset CRC, stuffer, counters | 4 |
| CRC sequence and trailer | 8 |
| **total** | **54** |

The toolchain rejects it: `SttProgram` raises at 33. The hardware stuffer
replaces all 36 control-flow rows with one test, `stall`, which asks the
stuffer what it is about to do — and the same program is **24 rows**.

**Result 2 — and unlimited rows would not save it.** CAN stuffs the CRC
sequence too. In the data phase a program can see the bit it is about to send,
with `srbit`. In the CRC sequence the bit comes out of the CRC register through
the `crcb` pin op, and **no test in the ISA reads that register** — the eleven
live tests are `always`, `c2z`, `cz`, `fifo`, `in0h`, `in0l`, `in1h`, `in1l`,
`srbit`, `stall`, `tmr`. So the program cannot know what it just transmitted
and cannot track a run across the CRC field, at any row count.

The second closes the loophole the first leaves open. A reader who doubts the
row count can check the second independently and reach the same conclusion.

Separately, CAN's CRC-15 with polynomial 0x4599 cannot be computed by the
legacy unit at all: it is 5 bits wide with a hard-wired 0x14.

**With the units: 24 of 32 rows.** `isa_bench/can_prog.py` transmits a base
frame, verified against a receiver that de-stuffs structurally and checks the
CRC-15, over five identifier/payload combinations, and in cycle-exact lockstep
with the RTL for 2,240 cycles. The receiver is shown able to fail: its CRC is
cross-checked against an independent polynomial reduction, the wire is asserted
to carry no run longer than five in the stuffed region, and corrupted frames
are rejected at seven of seven glitch positions.

**The price, stated with the claim.** +22 flops per machine in `stt_core`
(16 CRC, 6 stuffer) and +31 in `stt_config`, so **+53 flops per machine** and
**+6.58%** cell area on `stt_top`. The units are per machine, not shared, and
that is forced rather than chosen — see §4.1.

## 4. How this was verified, and what verification found

This is the part worth reading. The design is ordinary; the evidence is not.

### 4.1 Every load-bearing number is measured, and several arguments are executable

The encoding tables in the specification are generated from `spec/isa.json`,
which is checked against the Python models on all 60 entries; the RTL's decode
constants are generated from the same file. Drift between the specification,
the models and the RTL is therefore a build failure rather than a review
finding.

Where a rule could be derived instead of asserted, it is. §8.1.1 states that
**nothing a row can invoke may be shared between state machines** — a row costs
exactly one cycle, a shared resource can be reached by N rows on the same cycle,
arbitration means a machine waits, and §8.1 leaves nowhere for that wait to go.
That rule was written only after the same conclusion was reached twice
independently and by surprise: once for the host FIFOs, once for the §9 units.

### 4.2 The verification is adversarial, in four layers

- **Cycle-exact lockstep.** The Python models drive the world; the RTL shadows
  them and is compared every cycle on row, link, `sr`, `cnt`, `c2`, `crc`,
  `crc16`, stuffer state, `tcount` and pin values. Seven programs.
- **Mutation.** 350 mutants of the reference programs; the gate fails below
  85% kill. Currently 89.1%. A surviving mutant is treated as a gap in the
  tests, not a curiosity — one of them is why §4.3 exists.
- **Random programs.** 39 of 40 random 32-row programs run in lockstep, at
  100% coverage of the 54 field codes. This is what catches decode paths no
  reference program reaches.
- **Through the real pins.** Five machines configured over `ui_in`, run through
  the Tiny Tapeout boundary for 2,000 cycles with every assigned driver checked
  on its assigned pin, and host bytes moved over the serial port of §11.2.

Every gate is checked in both directions where that is possible. The
pin-assignment builder is verified to reject six classes of unusable assignment
*and* to accept valid ones; the phase machinery is verified to change the
waveform *and* to leave the default byte-identical.

### 4.3 What verification found, and the failure modes behind it

Ten wrong conclusions were caught by measurement. Each is recorded with the
mistake named, because the pattern matters more than the individual errors.

| # | The wrong conclusion | How it was caught | Failure mode |
|---|---|---|---|
| 1 | The encoding freeze held after adding a test code | Re-encoding every program and comparing packed words | **A check that measured the wrong property.** The first check compared row *counts*, which are unchanged when a code silently slides `tmr` from 9 to 10 and re-encodes every program |
| 2 | Nine state machines fit | Global routing at six | **Area is not routability.** The area projection was right and irrelevant; macros cost more routing resource than area |
| 3 | Format D's per-machine logic is smaller than C's | Synthesising both | **A component priced in a structure the architecture forbids.** §9's units were priced as shared; §8.1.1 does not permit sharing |
| 4 | `PSM-0069` is a missing database annotation | Adding the annotation | **A signal read without checking what the failing case does with it.** The annotation was added, the disconnected-pin count went to zero, and the unconnected-shape count did not move — which refuted the theory and was read as a puzzle |
| 5 | The unconnected stripes are every stripe in the core | Comparing their x positions against the macro columns | **Uniformity assumed from a pattern that tiles.** The 24 stripes sit 8 per macro column; the columns are spaced at exactly 8 × the stripe pitch, so the sets tile seamlessly |
| 6 | The aligned run fixed `PSM-0069` | Locating the message in the *failing* run's log | **A pass signal that also appears in the failing case.** `PSM-0040` is an early PDN check that passes in both; the verdict is the one after the IR-drop banner |
| 7 | Thread count caused the out-of-memory kills | Noticing the 16-thread run got further than the 4-thread one | **A plausible cause accepted without checking it explains the data** |
| 8 | The slew and capacitance violations concentrate on the macro read path | Re-measuring on the current design | **A finding carried across a design change without re-measuring.** True on the superseded floorplan, 1-of-13 on the current one |
| 9 | A CAN device model existed | Attempting to use it | **A file's existence taken for a working model.** `feed()` was never called and referenced an attribute that is never assigned |
| 10 | Post-GRT repair improves timing | Comparing at the same flow stage | **Mid-flow metrics compared against post-route ones.** The repaired run's mid-PnR numbers are *identical* to the baseline's — 1.4535804082934107, 0, 128 — and both lose ~3.65 ns to extraction |

Four of these ten are the same mistake: reading a signal without asking what
the failing case does with that same signal. It is recorded here because
naming it is what stopped the fifth.

The one diagnostic that was correct throughout was printed by the PDN plugin on
every affected run, in both row formats, and went unread:

```
pin column at x=56.870 um is 2.880 um off the nearest tile stripe
```

## 5. Physical result

Five machines and ten CFGMEM macros on the 6×4 die, format D:

| | |
|---|---|
| Magic DRC / KLayout DRC | **0 / 0** |
| LVS errors | **0**, every sub-count zero |
| Router DRC / antenna | 0 / 0 |
| IR drop, worst case | **0.02%** (1.92e-04 V) |
| Setup, slow corner | **−2.200 ns** → ~45 MHz |
| Hold, all corners | met, +0.108 ns worst |
| Instance utilization | 59.3% |

**The load-bearing physical constraint is grid alignment,** and it is the
hardest thing in the project to have found. A macro's *power pin columns* — not
its origin — must land on pdngen's stripe grid. Off by 2.88 µm, the stripes
drawn over them coincide with nothing, get no rail vias, and the entire power
network is sourceless: IR-drop analysis cannot run and LVS fails. On grid,
every signoff check reports zero. The constant that caused it was carried over
from a floorplan with a different core origin; it is now derived from the
stripe grid and the macro LEF, with an assertion that fails naming the offending
pin column.

**~45 MHz is the floor, not a missing optimisation.** Post-GRT design repair was
the obvious lever and made it worse: −2.200 → −2.798 ns, slew 48 → 97, fanout
unchanged. At 6.525 cycles per bit, 45 MHz is about 6.9 Mbps for SPI, well
inside anything in the conformance set.

**Six machines does not fit**, measured rather than projected: global routing
finishes with 2,846 GCells of overflow.

## 6. What is not established

- **Fmax is a violation, not a target.** −2.200 ns at the slow corner means the
  50 MHz template clock is missed, and closing it would need work not yet
  attempted at the synthesis level.
- **622 max-fanout violations**, of which **320 are the vendored macro's own
  internal structure** — 32 per instance, confirmed in a separate two-macro
  design. The remaining 302 are ours, 162 of them one load over the limit.
  Two levers were tried and neither works: post-GRT design repair made
  timing worse and left the count at 624, and a tighter synthesis fanout
  constraint never reaches yosys — it writes an SDC the router and STA read,
  and produced a byte-identical netlist. With zero router DRC and clean LVS,
  302 nets between 9 and 17 loads is a note rather than a defect.
- **Inter-pin skew is unmeasured, and it is the one item here where the answer
  could be bad rather than merely absent.** Every other limit on this list is
  something not yet known; this is something that could be wrong. The models
  have no pin path, so skew between a clock and its data — SCK/MOSI, SCL/SDA —
  is checked nowhere, and a protocol can meet every bit-period assertion while
  violating a setup time between two pins. The signoff run already emits
  post-route SDF for all three corners (`final/sdf/`), so resolving this is a
  matter of running the existing testbenches against the gate netlist with
  back-annotation, not of generating new data. Until that runs, every timing
  result here describes when a machine *decides* to change a pin, not when the
  pin changes.
- **Phase independence is established for the input side only.** UART traffic
  can now arrive at arbitrary phase with jitter; the SPI and I²C assertions
  measure the machine's own output, where there is no independent phase.
- **Shadowing was cut.** A second machine monitoring a bus another drives was
  considered and dropped: it has no specification entry, and adding a fourth
  capability late is how the first three end up underwritten.
