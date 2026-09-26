# FPGA bring-up wiring

FPGA bring-up only. None of this is part of the ASIC submission; it exists so
the design can be exercised on real pads before tape-out.

Board: Cora Z7-07S. `tt_um_stt` runs from a PL-side loader (`rtl2/stt_loader.v`)
with no host involvement — reset to running program. The system clock is the
Clocking Wizard `clk_out1` at **15.625 MHz**.

Regenerate the ROM for a stage with `scripts/gen_fpga_rom.py --program <name>`;
the generator prints the pin plan it encoded, and that printout is the
authority, not this table. Regenerating never requires editing RTL.

## SPI flash: JEDEC ID

Two machines. Machine 0 drives the SPI bus (the reference program from
`isa_bench/`, unmodified — only the pin plan differs). Machine 1 prints what
came back over UART at 9600 baud. `stt_hostread.v` relays bytes from machine
0's RX FIFO into machine 1's TX FIFO.

Generate with:

```
python3 scripts/gen_fpga_rom.py --program spi_flash --nsm 2 --div 8 -o rtl2/stt_rom.vh
```

`--sck-div` sets the SCK divisor (default 64). Set `LOOPBACK_INTERNAL = 0`;
the ROM also gates it, so a non-loopback ROM cannot close the internal path.

### Wiring

Device under test: W25Q128JV serial flash, 8-pin SOIC-208. Pin numbers below
are from the datasheet §3.3 *Pin Description SOIC 208-mil*, not from memory.

| Cora Z7 | signal | direction | flash pin | flash name |
|---|---|---|---|---|
| JA1 | MOSI | FPGA → flash | 5 | DI (IO0) |
| JA2 | SCK | FPGA → flash | 6 | CLK |
| JA3 | /CS | FPGA → flash | 1 | /CS |
| JB1 | MISO | flash → FPGA | 2 | DO (IO1) |
| JA5 | GND | — | 4 | GND |
| JA6 | 3V3 | — | 8 | VCC |

JA4 is UART TX and does **not** go to the flash — it goes to the RX pin of a
USB-serial adapter, with that adapter's ground tied to board ground. 9600 8N1.

Two flash pins must be tied high and are not in the table because they are not
FPGA signals: **pin 3 (/WP)** and **pin 7 (/HOLD or /RESET)**, both to 3V3.
Most breakout boards already pull these up — check the board before adding
jumpers, and check that the breakout is a 3.3 V part.

Pmod pin numbering is the Digilent 12-pin standard: top row 1–4 signal,
5 GND, 6 VCC; bottom row 7–10 signal, 11 GND, 12 VCC.

MISO arrives on a `uio` pin whose output enable the program releases, so the
flash can drive it. `rtl2/tb/tb_fpga_spi.v` asserts that release before the
first transaction — if the chip drove that pin it would fight the flash.

### What to expect

The 9Fh Read JEDEC ID instruction returns, MSB first, the Winbond
manufacturer ID then two device ID bytes (memory type, then capacity).
From the datasheet §8.1.1 *Manufacturer and Device Identification*:
manufacturer **EFh**, and for instruction 9Fh the W25Q128JV device ID is
**7018h**. So the three bytes are **EF 70 18**.

The UART prints **four** bytes, not three: `FF EF 70 18`. The bus is full
duplex, so the first byte captured is whatever MISO held while `9F` was
going out — with the line released and pulled up, that is `FF`. It is not
part of the JEDEC ID.

SCK is **244.1 kHz** at the default divisor of 64 (15.625 MHz / 64), far
below anything the part cares about. The transaction is **SPI mode 0**:
CPOL = 0 because SCK idles low, CPHA = 0 because the program shifts in the
rise row. The datasheet states *"SPI bus operation Mode 0 (0,0) and 3 (1,1)
are supported"*, so the program and the part agree and nothing needed changing.

### What a passing run does and does not show

`rtl2/tb/tb_fpga_spi.v` runs this against `rtl2/tb/spi_flash_model.v`, which
**we wrote**. Passing in simulation validates the plumbing — pin plan, CS
idling high, MISO released, bit order, the relay, the UART sequence — and
says nothing about a real W25Q128JV. The expected bytes come from the
datasheet and are programmed into our own model, so the simulation cannot
disconfirm them. Only a run against the real part can.
