# Colorlight 5A-75B receiver-card configuration protocol (reverse-engineered)

All frames are raw layer-2 Ethernet, no IP. Same framing as the display protocol:

```
dst MAC = 11:22:33:44:55:66      src MAC = 22:22:33:44:55:66
byte 12 = packet type            byte 13.. = payload ("data[0]" = byte 13)
```

The receiver card **never sends anything back** (no discovery reply, no ACK). Every
config packet is fire-and-forget broadcast onto the wire. A full "Send parameters to
receiver" from LEDVISION 8.8 for a single 64x64 cabinet (1/32 scan) is the 43-packet
burst below, captured on the wire and replayable verbatim from Linux
(`cl5a75.py --config config/config_64x64.bin`).

Send order of the burst (each type may repeat; repeats carry an incrementing index in
data bytes 2..3):

```
0x26  0x05  0x10  0x03  0x1f  0x32  0x76  0x18  0x41  0x83  0x17  0x37  0x1b  0x2b
```

`0x1b` repeats 16x (once per something-per-cabinet, likely per scan-line group of a
1/32 panel), `0x03 0x32 0x83` repeat 4x, `0x37 0x26` 3x, `0x1f` 2x.

## Common header

For the parameter packets that carry a receiver index, the first data bytes are:

```
data[0..1]  target selector    00 00 = this cabinet
data[2..3]  index / sequence   increments across repeats of the same type
data[4..5]  often ff ff         = "broadcast to all receivers" marker
```

## Per-type notes (64x64 / 1/32 capture)

| Type | Count | data len | Role (inferred) | First data bytes |
|------|-------|----------|-----------------|------------------|
| 0x26 | 3  | 127/265 | pre-amble / handshake, also `ff ff` broadcast form | `00 00 ff ff 85 00 93 39` |
| 0x05 | 1  | 259  | **cabinet geometry + timing**: `20 20`=32x?, `20`, width `00 40`=64, height `00 40`? gamma/scan params follow | `00 00 00 a8 ff ff ff 20 20 02 20 0c 00 08 00 20 00 40 00 c6` |
| 0x10 | 1  | 1027 | large table (all zeros here) — brightness/gamma LUT slot | zeros |
| 0x03 | 4  | 771  | **row/address map**, index in data[2]; entries `xx 00 00` stepping 0x08 | `.. 01 00 00 02 00 00 03` |
| 0x1f | 2  | 1035 | large table (zeros) — second LUT slot | zeros |
| 0x32 | 4  | 1035 | **pixel/column map**, index in data[2]; 2-byte entries `20 00 20 01 20 02..` | `00 20 00 20 01 20 02` |
| 0x76 | 1  | 1158 | **3-byte-per-entry table** (gamma or coordinate map): `00 00 00 00 10 01 00 20 02..` | see hex |
| 0x18 | 1  | 1027 | scan/timing table: repeating `0b 00 02 80 0a 00 01 40 09 00 01 40 07 00 00 50` blocks | see hex |
| 0x41 | 1  | 1053 | cabinet layout: `40 00 40 00 40 00 40` = 64s, then `01 00 02 00 03..` index list | see hex |
| 0x83 | 4  | 775  | **another row map**, index in data[2]; entries step 0x08, stride marker `04` in data[5] | `.. 00 04 00 00` |
| 0x17 | 1  | 772  | region/window descriptor: `00 10` (16) blocks, `03`, `10 00 10 00 02` | see hex |
| 0x37 | 3  | 788  | **map table**, index data[2], marker `01` in data[5]; entries step 0x08 | `.. 00 01 00 00` |
| 0x1b | 16 | 269  | **per-group scan config** (16 groups for 1/32); `ff ff` bcast, `41 00 00 00 05 01 00 ff ff ff` = flags + RGB | `00 00 ff ff 00 00 00 00 41 00 00 00 05 01 00 ff ff ff` |
| 0x2b | 1  | 269  | commit / apply: `00 01`, `18 80 00 80 00 80 00 80` (drive strength / latch?) | `00 00 ff ff 00 00 00 01 00 00 00 00 18 80 00 80 00 80` |

### Index convention (verified across repeats)

For `0x03`, `0x32`, `0x83`, `0x37` the third data byte (`data[2]`) is a 0-based chunk
index, and `data[3..]` a running offset. E.g. `0x03`:

```
idx 0:  00 00 00 00 00 00 00 00
idx 1:  00 00 01 08 00 00 08 00      <- data[2]=1, offset 0x0800
idx 2:  00 00 02 10 00 00 10 00      <- data[2]=2, offset 0x1000
idx 3:  00 00 03 18 00 00 18 00
```

So these are one logical table split into fixed-size chunks; concatenating the chunk
payloads in index order reconstructs the whole map.

## Reproducing / replaying

The exact 43-frame burst is saved as a length-prefixed blob
(`[u16 be length][frame bytes]...`) in `config/config_64x64.bin`. To push it to a card:

```
cl5a75.py --config config/config_64x64.bin config <same-blob>     # or
cl5a75.py --iface eno1 --config config/config_64x64.bin --hold 10 fill 255 0 0
```

Regenerate the blob and this analysis from any capture with:

```
tools/extract_config.py captures/<file>.pcap --save config/config_64x64.bin
```

## You must set the driver/decoder ICs by hand — they are NOT auto-detected

The single most important thing to get right, and the one LEDVISION will **not** figure
out for you: the **driver IC** and **decode/mux IC** must be selected manually and must
match the chips actually on your panel. There is no probe-back from the panel that tells
the controller what shift-register or row-decoder it's driving — the card blindly clocks
out whatever waveform the selected driver profile defines, so a wrong driver produces
garbage (wrong colors, half the panel dark, columns collapsed into one, or nothing).

- **Driver IC** = the RGB shift-register/constant-current LED driver on the panel
  (e.g. FM6124/FM6126A, ICN2038, MBI5124, DP5125, SM16xx, …). Setting this wrong is the
  usual cause of "half the panel is white and frozen" or badly shifted color.
- **Decode/mux IC** = the row-address decoder (e.g. RUC7258 / a 138-style 3-to-8 decoder,
  or "direct" no-decoder). Wrong choice collapses rows or lights the wrong scan line.
- LEDVISION's "Intelligent Settings" wizard maps **scan/geometry**, but it does **not**
  reliably detect the driver — you pick it from the dropdown, click **Send**, and watch
  the panel. Iterate driver first, then decoder, then scan/geometry.
- When capturing a config blob to replay with `cl5a75.py --config`, the driver/decoder
  choice is baked into the burst. If you replay a blob captured for a different driver,
  the panel will be wrong even though the geometry is right — recapture per panel.

In this project's saga, setting the correct driver + decoder was exactly what turned an
unreadable, collapsed display into a legible one; leaving them on auto/default never
worked.

## Caveats / still unknown

- Field meanings above are inferred from a single 64x64 1/32 capture; byte-level
  semantics (which bits are gamma vs. scan vs. drive-strength) are not fully decoded.
- A different panel geometry or scan rate will produce a different burst; capture your
  own with the LEDVISION-under-Wine setup in `ledvision/` and re-extract.
- The `0x10`/`0x1f` all-zero tables are likely gamma/brightness LUT slots that were left
  default; a calibrated setup would populate them.
