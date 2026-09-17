# UART detector feasibility — EXPERIMENT

**Not part of the conformance set.** This exists to answer one question: does a
protocol detector plus enough decoding to be useful fit in 32 rows? The row count
is the deliverable; the working detector is how it was obtained.

## Result

**12 rows.** 20 of 32 remain.

| | rows |
|---|---|
| detector (`isa_bench/detector.py`) | **12**, no trampolines |
| UART RX receiver (existing benchmark, measured) | 8 |
| naive sum | 20 |
| realistic combined detect-then-decode | **~19** (see below) |
| remaining of 32 | **~13** |

Measured by encoding at the frozen row format, not estimated:
`Format("single5", "grouped", tgt_bits=8)` → 12 rows, 384 bits, 0 trampolines.

**Detect-plus-decode fits in one machine.** So protocol inference is a
five-protocol demo — one detector+decoder per machine — not a two-machine-pair
demo. The detector and the receiver share seven rows of structure
(`IDLE, MID, CHKST, BITS, CNT, STOP, STOPCK`); they differ only in the frame
counter and what they push. A combined program needs a *second* copy of the
receive loop for the post-confirmation mode, because the ISA has no mode flag
(see below), which is where the ~19 comes from rather than 12 + 8 = 20.

## What it checks, and what it does not

Checks, per frame: a falling edge; the line **still low half a bit later**, so a
glitch is not a start bit; 8 bit times; a stop bit high where one belongs. Then
**8 consecutive well-formed frames** before it calls the signature.

Does **not** check: the data. Detection is framing only. It happens to push the
shift register on confirmation, which hands the host the byte that confirmed the
signature, but it is not a receiver.

**Baud is assumed, not measured.** The timer period P is preconfigured to a
candidate and the detector confirms or rejects that hypothesis. Several machines
each testing a different candidate is what makes that reasonable.

## Cases

| case | expect | result |
|---|---|---|
| real UART traffic | HIT | ✓ |
| real UART, baud ~3% off the hypothesis | HIT | ✓ |
| UART-shaped, every stop bit wrong | REJECT | ✓ |
| line held high (idle) | REJECT | ✓ |
| line held low | REJECT | ✓ |
| pseudo-random toggling on the bit grid | REJECT | ✓ |
| square wave at ⅔ the baud (SPI-clock-like) | REJECT | ✓ |
| square wave **at** the baud | HIT | ✓ — see below |

The confirm count matters and is **configuration, not rows**: each frame passes
random traffic with p ≈ 0.25, so 3 consecutive is ~1.6% per attempt and produced
a measured false positive within 200 frames. At 8 it is ≈ 1.5 × 10⁻⁵.

**A square wave at exactly the candidate baud is detected, and that is correct.**
Low for bit 0 is a valid start; the data bits alternate 1,0,1,0,1,0,1,0; bit 9 is
high, a valid stop. It is a well-formed frame carrying 0x55, repeating forever. A
real UART receiver would decode it as 0x55 and be right. The ambiguity is in the
signal, not the detector, and no amount of framing analysis resolves it.

## Verification

Run through the same machinery as the reference programs:

- **Lockstep against the RTL**: `uart_detect: 4904 cycles in lockstep, 12 rows,
  no divergence` — cycle-exact on `rtl2`, same harness as the six references.
- **Mutation**: 66 mutants, 47 killed, **71.2%**, against the reference suite's
  89.1%.

The gap is informative rather than alarming, and two survivors are worth naming:

- `drop action shift` survives. Expected: detection is framing only, so the
  shift register's contents never affect the verdict. It does mean the byte
  pushed on confirmation is only meaningful if `shift` works, which nothing here
  tests.
- `drop action thalf` survives, and **this one is a weakness of the cases, not a
  don't-care**. `thalf` is the mid-bit alignment — the whole of the detector's
  tolerance to baud error. Without it the timer free-runs at a phase that, on
  these deterministic waveforms, happens to land usably. A 3%-skew case was added
  specifically to kill it and did not, because the phase is still deterministic.
  Killing it needs waveforms with arbitrary edge phase or jitter, which the
  device models do not currently produce -- a gap that applies to every timing
  result in the repository, not just this one, and is now recorded in SPEC §16.2.

Row-order `swap` mutants also survive, which `mutate.py` already documents as
equivalent mutants.

## What auto-baud would cost, and where it stops

Measuring is cheap; applying is impossible.

**Measuring** the start-bit width needs a loop counting cycles while the line is
low — roughly 3–4 rows using a counter and `tmr`, plus a couple to bracket the
edges. Call it 4–6 rows on top of the 12.

**The architectural answer is several machines each testing a candidate baud**,
which is what this detector assumes, rather than one machine retuning itself.

**Applying it cannot be done from a program.** The timer period P is
configuration (§2). The only actions that touch the timer are `trst` and `thalf`,
and both reload from the *configured* P — **no action writes P**. So a program
can measure a baud and push the measurement to the host, but it cannot retune
itself. Autonomous auto-baud is outside the ISA; host-assisted auto-baud is a
round trip through the RX FIFO and a reconfiguration.

This is stated as a finding, not a request: the ISA is frozen.

## Does the structure generalize?

**Partly, and the limit is not rows.** UART is unusually easy in one respect —
it is self-clocked with an idle level, a known frame length and a stop bit, so
the whole signature is available on **one pin**. The binding constraint for the
others is that a machine has only **two inputs** (§2):

- **SPI**: the information is in the relationship between CS, SCK and MOSI. CS
  framing a burst of SCK edges is detectable with the two inputs available, and
  counters make the burst length checkable. But detecting *and decoding* wants
  CS + SCK + MOSI = three inputs, which a single machine does not have. That, not
  row count, is what would force a two-machine split for SPI.
- **I²C**: START is SDA falling while SCL is high, STOP is SDA rising while SCL
  is high. Both pins fit in the two inputs, but the ISA tests **one input per
  row**, so each condition costs two rows and is exposed to skew between the two
  synchronizers. Workable, more rows than UART, no fundamental obstacle.

## What the ISA cannot express

Stated plainly, as findings about a frozen ISA:

1. **No edge test.** Tests are levels (`in0h`/`in0l`). An edge costs two rows and
   a cycle of latency. Every detector in this family pays it.
2. **No action writes the timer period.** See auto-baud above.
3. **Two inputs per machine.** Caps single-machine SPI detect+decode.
4. **No mode flag.** State lives in the row pointer, so "same loop, different
   behaviour" means a duplicated loop. This is what makes combined
   detect-then-decode ~19 rows rather than ~14.
5. **No "same as the previous bit" test.** Already recorded in
   `row-format-decision.md` §6 for bit stuffing; it bites here too, since a
   run-length check would be a cheap extra signature.

## Reproducing

```bash
cd isa_bench
python3 detector.py          # row count
python3 detrun.py            # all eight cases
python3 detector_mutate.py   # mutation
cd ../rtl2 && python3 tb/run_tests.py uart_detect   # lockstep against the RTL
```


## Update: phase is now swept, and the `thalf` survivor is dead

The finding below has been acted on. `devices.UartDriver` builds its waveform
from bit-boundary times rather than fixed-length runs, so it takes a fractional
period, an arbitrary phase and per-boundary jitter; `check_all` sweeps the phase
over a whole bit period for every UART case.

| | mutants | killed | survived | kill rate | `thalf` mutant |
|---|---|---|---|---|---|
| fixed phase, as before | 66 | 47 | 19 | 71.2% | **survives** |
| phase swept over a bit period | 66 | 49 | 17 | 74.2% | **killed** |
| phase swept + 1.5 cycles jitter | 66 | 49 | 17 | 74.2% | killed |

The two survivors sweeping phase removes are exactly the two about the row that
does the mid-bit alignment: `drop action thalf` and `swap true/false exits` on
`IDLE`. Jitter on top of phase adds nothing further, which is itself worth
knowing — for this program phase was the whole gap.

`isa_bench/phase_check.py` gates that the default waveform did not move: it
rebuilds the old fixed-run construction and compares the line value at every
cycle, at four periods. Every existing result was measured against that
waveform, so it has to stay identical, and it does.


## The baud capture window, measured

`DETECTOR_NOTES` says auto-baud is not applicable and that several machines each
testing a candidate baud is the architectural answer. `isa_bench/baud_window.py`
puts a number on it, and the number is smaller than the naive measurement.

Running a detector configured for period P against real UART at P*r, at four
phases:

| | r range |
|---|---|
| fires at every phase | 0.81 - 1.05 |
| fires **and samples correctly** | **0.91 - 1.05** |

The gap is the detector firing on traffic it cannot sample. Shown UART ~15%
faster than assumed, it over-runs the frame, and the stop-bit check then passes
trivially against the idle line -- so it confirms "UART at P" while pushing a
byte that was never sent. "Did it detect" is the wrong question; the window has
to be measured on whether the byte it pushes is one that was actually
transmitted.

So the capture window is **-5% to +10% of baud**, adjacent candidates may be
spaced by a factor of **1.154**, and therefore:

* **five machines cover a 1.77x baud range**, not an open-ended sweep;
* covering a 10x range would need 17.

That does not overturn the multi-candidate answer, but it bounds it: it is a
way to cover a handful of nearby candidate rates, not a way to find an arbitrary
unknown baud. Anyone quoting the approach should quote the 1.77x with it.
