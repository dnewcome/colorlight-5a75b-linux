# Config template library — distilled from LEDVISION captures

These are **receiver-card config bursts** mined out of a 27.8 GB pcap of LEDVISION
driving a Colorlight 5A-75B (see `tools/mine_configs.py`, GH #12). Each `.bin` is a
length-prefixed replay blob (`[u16 BE len][frame]…`) that `cl5a75.py --config <file>`
can send straight to the card — **no LEDVISION, no Windows.**

`index.json` catalogs each: packet count, byte size, the `0x05` geometry fields, which
driver-IC tables it carries (`0x76/0x7b/0x7f/0x83`), and whether it has a scan table
(`0x18`).

## What the fields mean (decoding in progress — GH #6/#7)
- **`0x05` byte 7 (`geometry.b7`)** — the scan/module setting. `32` = the 1/32 (module
  64×32) configs; `1` = static/1-scan. `width` (byte 17) = 64 on all of these (our panel).
- **driver_tables** — the set of `0x76/0x7b/0x7f/0x83` waveform/init tables present. This
  distinguishes driver ICs (Normal Chip / FM6124 vs MBI5153 etc.). Diffing configs that
  differ *only* in driver extracts the per-chip tables.
- **`0x18`** — the scan timing table (regenerated per scan rate; the thing a byte-patch
  can't fake).

## How this gets used
1. `cl5a75.py --config cfg_XX.bin` replays a whole config to the card.
2. Diff a `b7=32` config's scan/geometry against the known-good 1/16 config
   (`../../config/config_64x64.bin`) to decode the scan table.
3. **Splice**: known-good driver tables (Normal Chip) + a 1/32 scan table → a generated
   correct 1/32 config (GH #7). We now have both halves of that splice here.

## Caveat
Not every captured config *displayed correctly* — tonight's 1/32 attempts flickered
because they used the wrong driver (MBI5153). But their **scan tables are valid 1/32
tables**; correctness comes from pairing a 1/32 scan table with the right driver tables.
Provenance for each is its content hash in the filename.
