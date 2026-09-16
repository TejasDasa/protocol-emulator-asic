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
benchmarks (a deliberately corrupted decode is caught).

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
