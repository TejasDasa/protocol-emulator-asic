# ISA exploration for the protocol emulator ASIC

Cycle-accurate Python models of three candidate instruction sets, five protocol
benchmarks written in each, and independent device models that check the waveforms.

| File | Contents |
|---|---|
| `world.py` | Nets with open-drain resolution, 2-cycle input synchronizer, host FIFOs |
| `devices.py` | UART monitor/driver, SPI mode-0 target, I2C target with clock stretching, USB LS decoder |
| `pio.py` | RP2040-style PIO assembler and state machine (16-bit instructions) |
| `stt.py` | State-table ISA (v1 = 28-bit rows, v2 = 39-bit rows) |
| `rm.py` | Register machine (32 opcodes, 16-bit instructions, timer, one-level call) |
| `programs.py` | All 15 programs |
| `bench.py` | Stimulus and checks; `python3 bench.py [bench...]` runs at nominal timing |
| `sweep.py` | Timing sweep; writes `results.json` |

Run: `python3 bench.py` then `python3 sweep.py`.

## Rules used

- Same host interface for all: bytes in a TX FIFO, bytes out of an RX FIFO.
- Program bits only; configuration registers (baud divider, shift direction) not counted.
- Inputs pass through a 2-cycle synchronizer for every ISA.
- Exception: PIO cannot compute CRC5, so for USB its host supplies a prebuilt 32-bit word.

## Results

| Benchmark | PIO bits | STT bits | RM bits | PIO cyc/bit | STT cyc/bit | RM cyc/bit |
|---|---|---|---|---|---|---|
| UART TX | 64 | 140 | 224 | 2 | 2 | 5 |
| UART RX | 144 | 224 | 256 | 2 | 3 | 5 |
| SPI master | 192 | 168 | 336 | 6.9 | 6.2 | 10.7 |
| I2C master | 464 | 616 | 656 | 6.1 | 5.9 | 11.9 |
| USB LS token TX | 400* | 624 (v2) | 832 | 6 | 5 | 18 |

\* host computes CRC5 and packs SYNC/PID/field.

STT row counts: 5, 8, 6, 22, 16. At v2 width (39 bits) the first four become 195, 312, 234, 858.

## Known limitations

- Device models have zero propagation delay; real setup/hold margins are not modeled.
- Fixed test vectors, not constrained-random.
- Program quality depends on the author; STT and RM programs are probably less optimized than PIO's.
- STT row field widths are first guesses; bit totals are very sensitive to them.
- No logic-area numbers yet: bits of program memory are only half the cost.

## Row-encoding study (`rowenc.py`, `rowformat.py`, `formatsweep.py`, `gensweep.py`, `hybridsweep.py`)

Every format is packed to real integers, unpacked, and the decoded program is rerun on the
benchmarks.

The parenthetical that used to sit here -- "a deliberately corrupted decode is caught" -- was
never implemented: nothing in this repository corrupted anything, so the claim was plausible
but untested. `mutate.py` now tests it. It applies single-point corruptions (wrong test code,
wrong branch mode, shifted target, dropped/added action, wrong pin op or slot) and asserts the
benchmark fails.

Measured, `python3 mutate.py`:

| benchmark | semantic mutants killed |
|---|---|
| uart_tx | 30/31 (96.8%) |
| uart_rx | 32/37 (86.5%) |
| spi | 47/54 (87.0%) |
| i2c | 108/127 (85.0%) |
| usb | 95/101 (94.1%) |
| **total** | **312/350 (89.1%)** |

Row-order swaps are reported separately (4/54 killed) and **excluded from that rate**, which is
a deliberate choice worth stating: branch targets resolve by NAME, so exchanging two adjacent
rows changes behaviour only for rows that fall through to `next`. Most rows carry explicit
targets, so most swap mutants are semantically identical programs -- textbook equivalent
mutants. Counting them would understate detection; the four that do die identify the rows that
genuinely depend on physical order.

`python3 mutate.py --gate` is a validity gate wired into `make check`. It fails if the kill rate
drops below a floor OR if the mutant count drops, the latter catching a benchmark being removed
(which would raise the percentage while testing less).

**Timing is now checked.** SPI and I2C device models take `sck_nominal` / `scl_high_nominal` /
`scl_low_nominal` and a tolerance, and assert each clock phase lasts at least
`nominal * (1 - tol)`. These are MINIMUMS, matching how both protocols specify clock timing
(`t_HIGH` and `t_LOW` are minimums), which also makes them correct under I2C clock stretching --
a target can only lengthen the low phase. `tol` (default 0.25) is deliberate slack for
propagation delay and jitter, not measurement noise: tighten it to test timing margin. Adding
these checks took the timer-mutant survivors from 14 to 6 and the overall score from 86.6% to
89.1%. **All five benchmarks still pass**, so the SPI and I2C programs were timing-correct all
along -- they simply had never been verified.

**Remaining gap, named.** The 6 surviving timer mutants (spi `END`; i2c `S1`, `A3`, `A5`, `N1`,
`P3`) do change pin timing -- long phases shorten from 18/20 cycles to 12/13 -- but never below
the bit-period minimum. Those rows govern I2C's START/STOP setup and hold intervals, which the
spec times as separate parameters (`t_SU;STA`, `t_HD;STA`, `t_SU;STO`) from `t_HIGH`/`t_LOW`.
Closing it needs distinct nominals for those rows; it is not closed today.
and I2C: deleting the timer wait does not fail those benchmarks. uart_tx, uart_rx and usb kill
100% of test mutants (5/5, 8/8, 16/16) because they check jitter; SPI and I2C check data only.
So "SPI passes" is a weaker statement than "UART TX passes", and bit timing is unverified for
the two largest programs.

21-bit row: test 4 | branch mode 2 | target 5 | pin slot 2 | pin op 3 | action-set index 5

- Branch mode replaces the second target: WAIT (else stay), BRANCH (else next),
  SKIP (if true next), STEP (true next, else stay). Row reordering needed zero trampolines.
- One pin op per row; slot 3 is the D+/D- pair (ops SE0, J, K, toggle), so SPI needs 2 extra rows.
- Action sets come from a 32-entry palette: empty + all 17 single actions + common sets.

| Palette | First four | All five | Held-out USB |
|---|---|---|---|
| 32 fixed, built from all five (in-sample) | 903 | 1239 | n/a |
| 32 fixed, leave-one-out, split fallback | 924 | 1575 | 31 rows, 10 cyc/bit |
| 24 fixed + 8 loadable, leave-one-out | 916 | 1343 | 16 rows, 5 cyc/bit |
| PIO | 864 | 1264* | |

### Where the timing margin actually sits — and why the first answer was wrong

The `tol` default of 0.25 is generous, and tightening it changes nothing: the
check is a *minimum*, and the nominals are anchored at or below the measured
baseline, so the baseline still passes at `tol = 0`.

An earlier version of this section then "measured the margin" by raising the
required minimum until the baseline failed, and reported 0% for SPI SCK and I2C
SCL low. **That number was an artifact and the alarm attached to it was wrong.**

**Why it was an artifact.** The nominal was anchored at exactly what the program
produces. Sweeping P shows every phase is an exact, deterministic function of P:

| P | SPI SCK phase | I2C SCL low | I2C SCL high |
|---|---|---|---|
| 16 | 8 | 8 | 6 |
| 24 | 12 | 12 | 8 |
| 32 | 16 | 16 | 10 |
| 48 | 24 | 24 | 14 |
| 64 | 32 | 32 | 18 |

SCK and SCL-low are exactly `P/2`; SCL-high is exactly `P/4 + 2`. Anchoring at
`P/2` and then asking "how much longer than `P/2` is it" can only ever answer
zero. The 25% reported for SCL high was the constant `+2`, which is why it moved
with P (50% at P=16, 12.5% at P=64) instead of staying fixed.

**Why the alarm was wrong.** The claim was that "any delay in the pin-drive path
comes straight out of the phase". It does not. Phase length here is a count of
core clock cycles between two toggles, and it is integral and exact. A
register-to-pad delay `d` shifts *every* edge by `d`, so a phase measures
`(t2 + d) - (t1 + d)` and is unchanged. Pad delay moves the waveform; it does
not compress it.

**What the real silicon risks are**, none of which a cycle-accurate model can
see:

* **Inter-pin skew.** If SCK and MOSI, or SCL and SDA, have different pad and
  routing delays, the data-to-clock relationship shifts and setup/hold at the
  far end degrades. This is the actual failure mode, and it needs STA with SDF
  back-annotation, not this model.
* **Absolute time against spec minimums.** I2C standard mode wants
  `t_HIGH >= 4.0 us` and `t_LOW >= 4.7 us` in real time. Whether `P/4 + 2`
  cycles clears that depends on the core clock, which is a system choice. Note
  the duty cycle is low-heavy (about 33%), which is the spec-friendly direction.
* **PVT and clock jitter.** These scale the whole waveform together, so ratios
  are preserved; only absolute-time requirements are affected.

So the tolerance remains the right knob for asking "would this still work if the
pin path cost us N cycles" — but the honest answer is that the model cannot
answer it, because the model has no pin path. That question belongs to STA.

## Shared-unit reachability and the freeze (`sharedunits.py`, `nextrow.py`)

`crc_lfsr16` and `bit_stuffer` were priced into the fixed budget and argued for
on capability grounds, but no row field reached them: in `rtl/stt_chip.v` their
control inputs are tied to raw `ui_in`/`uio_in` bits to satisfy the area
harness's "every input driven" rule. (`stt_hostbuf` and `stt_iomux` were never
affected — they hang off `tx_pop`/`rx_push`/`tx_ne` and `sm_out`/`sm_oe`/`sm_in`,
which are existing actions, tests and pin ops.)

`python3 sharedunits.py` takes every control input from the two module port
lists, splits them into per-program constants and things a row must say, places
the latter in codes that are already free, and then **proves the freeze survives**
by re-encoding every reference program with and without the amendment and
comparing the packed words. Five codes, zero new row bits, every benchmark
bit-identical. Writes `sharedunits.json`.

`python3 nextrow.py` checks the one place the model and the RTL could disagree
about `next`: `rowenc.rebuild` wraps at the end of the *program*,
`stt_decode.v:73` wraps at row 31. It fails if any program starts taking `next`
from its own last row. All six currently end on a `WAIT` row, so the two rules
cannot be told apart.

Both are wired into `make check-freeze`, which `make check` runs.
