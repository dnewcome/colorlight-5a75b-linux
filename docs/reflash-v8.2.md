# Driving the Colorlight 5A-75B V8.2 with open FPGA gateware

The board is a Lattice ECP5 you can reprogram, which sidesteps the stock Colorlight
firmware entirely: no LEDVISION, no config protocol, no discovery, no dependence on the
card's Ethernet transmit (which the initial reverse-polarity event may have damaged),
and no mystery scan/mux config. You write the HUB75 driver, so the FM6124 + RUC7258
panel is driven by code you control.

## This board (V8.2), from q3k/chubby75 hardware_V8.2.md

- **FPGA:** Lattice ECP5 `LFE5U-25F-7BG256I` (CABGA256). Open flow: Yosys + nextpnr-ecp5 + prjtrellis.
- **SPI flash:** Winbond `25Q32JVSIQ`, 32 Mbit. Pins: CS# N8, SO T7, SI T8.
- **SDRAM:** ESMT `M12L64322A`, 2M x 32, 200 MHz.
- **Ethernet:** two Realtek `RTL8211FP` gigabit PHYs (U11, U13). Shared: PHYRstB R6, MDC R5, MDIO T4.
  (Note: older boards used Broadcom B50612D; V8.2 differs — matters for liteeth PHY config.)

### JTAG header (connect an FT2232H / ECP5-capable programmer)
| Signal | Pin |
|--------|-----|
| TCK | J27 |
| TMS | J31 |
| TDI | J32 |
| TDO | J30 |
| 3V3 | J33 |
| GND | J34 |

### HUB75 pin mapping (FPGA pins)
Shared control across all 8 ports:
```
A=N4  B=N3  C=P3  D=P4  E=N5     (RUC7258 row address, 1/32 -> A..E)
CLK=M3   STB/LAT=N1   OE=M4
```
Per-port RGB (upper half R0/G0/B0, lower half R1/G1/B1):
```
J1: R0 C4  G0 D4  B0 E4   R1 D3  G1 F5  B1 E3
J2: R0 F1  G0 F2  B0 G2   R1 G1  G1 H2  B1 H3
J3: R0 B1  G0 C2  B0 C1   R1 D1  G1 E2  B1 E1
J4: R0 P5  G0 R3  B0 P2   R1 R2  G1 T2  B1 N6
J5: R0 T13 G0 R12 B0 R13  R1 R14 G1 T14 B1 P12
J6: R0 R15 G0 T15 B0 P13  R1 P14 G1 N14 B1 H15
J7: R0 G16 G0 H14 B0 G15  R1 F15 G1 F16 B1 E16
J8: R0 D16 G0 E15 B0 C16  R1 B16 G1 C15 B1 B15
```
Your panel is on J1. A 64x64 1/32-scan panel uses the two RGB triplets (R0/G0/B0 top 32
rows, R1/G1/B1 bottom 32 rows) with A..E selecting the scan row. FM6124 = plain shift
register (clock on CLK, latch on STB). RUC7258 = row mux driven by A..E. Standard HUB75
gateware drives both.

## Toolchain / starting points
- Toolchain: `yosys`, `nextpnr-ecp5`, `prjtrellis` (`ecppack`), flash with `ecpprog` or `openocd`.
- Board target: LiteX has `litex-boards` colorlight_5a_75b targets (revisions 7.0/8.0); a V8.2
  platform file may need small pin/PHY tweaks per the table above.
- HUB75 core: reuse an existing ECP5 HUB75 driver, or write a small one: shift 64 px/row on
  CLK for both halves, pulse STB, set A..E, pulse OE for the BCM/PWM sub-period, advance row.
- Simplest first bring-up: an internal test-pattern gateware (no Ethernet) that drives J1 with
  a moving color/gradient. Once the panel lights correctly, add a pixel source (SDRAM framebuffer,
  or Ethernet via liteeth/etherbone — more work, and needs the RTL8211FP config).

## Why this solves what the stock path could not
- The scan/mux for RUC7258 is explicit in your gateware, not a config we have to guess.
- No reliance on the card answering discovery or transmitting at all.
- RGB order, brightness/PWM depth, refresh are all yours to set.

## Ready-made open gateware & prior art (explore before rolling your own)

We are NOT reflashing right now (the stock firmware + LEDVISION config path works, just
painfully). These are saved as the escape hatch to explore later — the day LEDVISION's
wizard becomes intolerable, this is the way out. Two complementary projects:

### dgym/receiver75 — drop-in replacement gateware (start here)
<https://github.com/dgym/receiver75> — MIT-licensed replacement FPGA gateware **specifically
for the Colorlight 5A-75B v8** (our board is V8.2, same family), and it is **hardcoded for
64x64 panels, two panels per connector, 500 Hz refresh** — i.e. exactly our panel geometry.
The scan/row-addressing/refresh sequencing lives in the gateware, so there is **no LEDVISION,
no scan wizard, no discovery, no config protocol.**
- `prebuilt/` ships ready-to-flash bitstreams — **try these before building from source.**
- `gateware/` = FPGA logic (UDP receive + panel control). `tools/make_config.py` sets MAC/IP
  (supports multiple cards on one net, which stock fw can't). `tools/sender75.py` enables the
  display and sends test images — a clean Linux/Python control path (pairs with our `cl5a75.py`).
- Double-buffered, configurable memory base for multi-card sync.
- Limitation per its docs: 64x64 / two-panels / 500 Hz are FIXED, not runtime-configurable.
- Deploy = JTAG flash via the header above. **Back up the stock SPI flash first** (read out
  25Q32 with `ecpprog`/`openocd`) so the card can be restored to Colorlight firmware.

### q3k/chubby75 — hardware reverse-engineering reference
<https://github.com/q3k/chubby75/blob/master/5a-75b/README.md> — the definitive teardown of
the 5A-75B (all revisions incl. V8.2). Source of the FPGA/flash/PHY part numbers, the JTAG
header, and the HUB75 pin mapping in this doc. Use it to adapt any gateware (receiver75, a
LiteX target, or your own) to the exact V8.2 pinout, and for the LiteX `colorlight_5a_75b`
platform tweaks (V8.2 uses RTL8211FP PHYs, differs from older Broadcom-PHY revisions).

### Suggested exploration order
1. Read out & back up the stock flash (restore path).
2. Flash a `receiver75` `prebuilt/` bitstream, drive with `sender75.py` — fastest win, made for 64x64.
3. If that doesn't fit, use chubby75's pinout to bring up a LiteX/HUB75 target or the
   internal test-pattern gateware described above, then add Ethernet.
