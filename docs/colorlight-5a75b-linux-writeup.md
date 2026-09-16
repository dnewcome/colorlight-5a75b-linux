# Driving a Colorlight 5A-75B HUB75 receiver card from Linux — the complete field notes

A full account of getting a **Colorlight 5A-75B V8.2** receiver card to drive a
**64×64 P3 HUB75 panel** (FM6124 column drivers + RUC7258E row decoder), done entirely
on Linux — raw layer-2 packets from Python, LEDVISION 8.8 running under Wine with a
custom WinPcap shim, and every dead end and root cause along the way. Written so the next
person with this board loses hours instead of days.

---

## 1. The cast

**Receiver card — Colorlight 5A-75B V8.2**
- Lattice ECP5 `LFE5U-25F-7BG256I` FPGA (reprogrammable with the open yosys /
  nextpnr-ecp5 / prjtrellis flow over JTAG).
- 2× Realtek `RTL8211FP` gigabit PHYs, Winbond `25Q32` SPI flash, ESMT SDRAM.
- 8 HUB75 output ports (J1–J8). Stock firmware speaks a **raw layer-2 Ethernet**
  protocol; the card is configured and fed pixels over that.
- Hardware teardown reference: **q3k/chubby75** `5a-75b/README.md`.

**Panel — 64×64 P3 (single HUB75 connector, on J1)**
- **Column/RGB driver: FM6124** — a plain constant-current shift register (clock in data,
  latch). *Not* a PWM driver.
- **Row/mux driver: RUC7258E** — a 1/32-capable row decoder (A–E address lines).
- 1/32 scan: two RGB data groups (R0/G0/B0 = top 32 rows, R1/G1/B1 = bottom 32 rows),
  A–E select the scan row.

**Host — Linux**, gigabit NIC `eno1`, plus the Colorlight vendor tool **LEDVISION 8.8**
(Windows-only) running under **Wine**.

---

## 2. The layer-2 protocol

All frames use fixed MACs and a fake "ethertype" that is really `[packet_type, data[0]]`:

```
dst 11:22:33:44:55:66   src 22:22:33:44:55:66
bytes 12..13 = [packet_type, first data byte]
```

Note **`11:22:33:44:55:66` is a multicast MAC** — the low bit of the first octet (`0x11`)
is the I/G group bit. That is deliberate: it is a well-known group address baked into the
firmware, so you can address a card whose real MAC you don't know.

| type | meaning | notes |
|------|---------|-------|
| `0x0A` | brightness | `data = [b,b,b,0xFF]`, 77-byte frame |
| `0x55` | pixel row  | `data = [row_hi,row_lo, off_hi,off_lo, n_hi,n_lo, 0x08,0x88] + RGB*n` |
| `0x01` | sync/latch | 112-byte frame, `data[0]=0x07`, brightness bytes at 22/25–27 |
| `0x07` | discover   | 284-byte probe; card replies `0x08` |
| `0x08` | discover reply | ~1070 bytes; carries card id / fw / geometry |

Everything except discovery is **fire-and-forget** — no ACK. Absence of a reply never
means the frame didn't land.

`cl5a75.py` in this repo implements all of this (send, discover, patterns, and replaying
a captured config blob). Raw `AF_PACKET` sockets need `CAP_NET_RAW`; we run them inside
`docker run --net=host` to avoid a sudo password prompt.

### The discovery handshake, and why it dies on a switch

The single most important protocol finding. The probe and the reply are addressed
**asymmetrically**:

| direction | dst MAC | src MAC | fate through a switch |
|-----------|---------|---------|-----------------------|
| probe (host→card) | `11:...:66` (multicast) | `22:...:66` (unicast, legal) | flooded everywhere → **reaches the card** |
| reply (card→host) | `ff:ff:ff:ff:ff:ff` (broadcast) | **`11:22:33:44:55:66`** (multicast!) | **dropped by the switch** |

The card sends its `0x08` reply as a **broadcast**, but with a **source MAC that has the
group bit set** — which is illegal per IEEE 802.3 (a source address must be unicast).
**Switch silicon routinely drops frames with a group-bit source MAC** as a sanity check.
So:

- The probe floods through any switch and reaches the card.
- The card's reply never survives the switch's source-address validation.
- On a **direct cable** there is no switch enforcing the rule, so the reply arrives every
  time.

We proved this with a clean A/B (both at 1000 Mb/s link, same probes):

| setup | link | probe out | reply back |
|-------|------|-----------|------------|
| direct cable | 1 Gb/s | yes | **50/50 replies** |
| through switch | 1 Gb/s | yes | **0 replies (×2 runs)** |

The captured reply header, for the record:
`dst=ff:ff:ff:ff:ff:ff  src=11:22:33:44:55:66  ethertype=0x0805` (`0x08`=reply, `0x05`=5A
card), firmware **v11.6**.

**Takeaway: use a direct NIC↔card cable.** Discovery *needs* the reply, and only a direct
link delivers it. (Display doesn't need the reply — but see the power section for why a
switch still isn't worth it.)

> Debugging note: to see the reply at all on the host you must put the NIC in
> **promiscuous mode** — the reply's destination is broadcast but you're also watching for
> a frame that isn't addressed to your real MAC.

---

## 3. Running LEDVISION 8.8 on Linux under Wine

You do not need Windows. What it took:

- **WinPcap**: LEDVISION talks to the NPF driver via `DeviceIoControl` (BIOCSENDPACKETS).
  We built a **custom `wpcap.dll` shim** (MinGW) that fakes `pcap_t`/adapter handles,
  implements the send path over a raw socket, and injects the discovery reply. Installed
  into the prefix with a `wpcap=native,builtin` DLL override.
- **VC++ 2013 runtime** (real `msvcr120`, extracted from vcredist cabs) — LEDVISION
  crashes at startup without it.
- **>20 network interfaces crashes LEDVISION** (it enumerates docker bridges/veths). Fix:
  run it inside a **network namespace containing a single `macvlan`** child of `eno1`, so
  it sees exactly one NIC.
- **Wayland focus theft** by the LED preview stole keyboard input → run Wine in
  **virtual-desktop mode** (`wine explorer /desktop=…`).
- **Wine wow64 pcap RECEIVE is broken** (returns a correct header but a dangling 32-bit
  data pointer), so the shim **injects the card's real captured discovery reply** for
  probe index 0 (only index 0 — otherwise LEDVISION invents 1024 phantom cards).
- Launcher: `sudo ledvision/run-ledvision.sh` (rsyncs the prefix to root, builds the
  namespace + macvlan, runs LEDVISION). Logs to `ledvision/run-root.log` and the shim to
  `ledvision/wpcap-shim.log`.

With this, LEDVISION detects the real card **on the direct link** and drives the panel
live.

---

## 4. The config protocol (what LEDVISION actually sends)

Configuring the card = a **burst of ~43 packets** sent once (captured and re-playable with
`cl5a75.py --config`). The packet types we identified:

- `0x05` — **cabinet geometry / timing** (width, height, gamma/scan params).
- `0x18` — **scan/timing table** (per-scan-line; regenerated when scan rate changes).
- `0x1b` / `0x2b` — **per-group scan config** (repeats once per scan group — 16× at 1/16).
- `0x17`, `0x37`, `0x40` — timing / group config.
- `0x76` / `0x7b` / `0x7f` / `0x83` — **driver-IC waveform/init tables** (these change when
  you pick a different Driver IC).
- `0x10` / `0x1f` — gamma/brightness LUT slots (default = zeros).

Full byte-level notes: `docs/config-protocol.md`. **Config is applied incrementally** —
LEDVISION pushes packets as you click through its dialogs, so partial state reaches the
card mid-wizard.

### The `.rcvbp` file

LEDVISION's saved receiver-parameter file. Two format variants seen in the wild:
- **Uncompressed** (~22 KB) with embedded scan/gamma/calibration tables (the kostaman
  64×64 files). Header is a **fixed signature, not a content checksum** (first 57 bytes
  identical across two different files).
- **zlib-compressed** (~4.6 KB, `78 9c` magic) — the SeenGreat file.

Because the scan table (`0x18`) is embedded and must be *regenerated* for a different scan
rate, **you cannot byte-patch a 1/16 file into a 1/32 file** — the header would claim 32
while the table still says 16. Only LEDVISION (or open gateware) regenerates it.

---

## 5. The debugging saga — every root cause

These are the traps, in the order they bit, with the actual cause (several masqueraded as
something else for hours).

### 5.1 No lights on the card → reversed 5V polarity
Self-inflicted; fixed by correcting polarity. (The card survived.)

### 5.2 "Card is dead / TX damaged" → WRONG; it was the switch
Early on, discovery got nothing and it looked like the card couldn't transmit. It was
**§2's illegal-source-MAC drop**, not damage. On a direct link the card replies perfectly
(fw v11.6). *Lesson: prove the link topology before condemning hardware.*

### 5.3 Won't link at 100 Mb → needs gigabit
The card/PHY wants a gigabit link partner. Use a GB port / direct GB cable.

### 5.4 The **PSU brownout** — the great masquerader
This one cost the most time because it disguised itself as *config* failures:
- LEDVISION's Intelligent-Setting **greyscale test dead-ended** ("check the cable") — we
  chased data polarity and cabling. **Real cause: the test drives full white, which browns
  out an undersized 5V supply and reboots the card.**
- Full-white Screen Test "strobed to one line," blank panels, etc. — all the same brownout.
- **Full white ≈ 3× a single-color's current.** A 64×64 P3 at full white pulls **~4–8 A at
  5 V**. Small supplies collapse only under white; single-color tests look fine.
- *Lesson: judge the card by single-color tests; get a 6–10 A 5 V supply before trusting
  any white/greyscale result.* A new PSU cleared a whole class of "failures" at once.

### 5.5 The **driver IC** — MBI5153 vs FM6124
The deepest config trap:
- A solid-green test that comes out as a **scattered rainbow / hue sweep** = the card is
  clocking data with the **wrong driver protocol**, so uniform input becomes position-
  dependent garbage.
- The downloaded SeenGreat "6124" file actually loaded **Driver IC = MBI5153** — a PWM/
  S-PWM driver with a grayscale clock (GCLK), Gray Level 8192, refresh 3540 Hz. Feeding an
  **FM6124** (dumb shift register) panel an MBI5153 waveform = exactly that rainbow.
- **The value that works in LEDVISION is `Normal Chip`.** Counter-intuitively, selecting
  the literal **`FM6124`** dropdown entry *blanks* the panel; `Normal Chip` drives it
  correctly.
- *Lesson: driver IC is manual and it is the #1 thing to get right; a "solid color →
  rainbow" symptom is a wrong-driver tell, not signal corruption.*

### 5.6 The **scan rate** — 1/16 vs 1/32 (the missing E line)
Once the driver was right, the panel showed **clean colors but only the first 16 rows of
each 32-row half**. Mechanism:
- A 64-tall panel = **1/32 scan**: A–E (5 address lines) = 32 addresses, each driving one
  row in the top half and one in the bottom.
- The kostaman/known-good config was **1/16** (module `64W×16H`, "16 scan"): only A–D are
  driven = 16 addresses = 16 rows per half. **The other 16 rows need the E line, which is
  only clocked at 1/32.** There is no separate "enable E" toggle — **1/32 *is* the toggle.**
- Detailed patterns *flickered* at 1/16-on-a-1/32-panel (wrong refresh timing); solids
  looked stable. Fixing scan settles it.
- *Lesson: "N rows lit per half, rest dark" = scan set to half what the panel needs.*

### 5.7 LEDVISION's scan config is wizard-gated and hostile
- **Module Size / Scan Mode are read-only** on the flat parameters page; changing scan
  *requires* the "Intelligent Setting" wizard.
- The wizard's **greyscale step** (§5.4) needs adequate power to pass.
- The wizard ends in a **manual pixel-map**: a 64×32 grid where it expects you to trace the
  data path pixel-by-pixel (2048 cells) — "fill down" just copies row 1 into every row
  (→ one bright line, because all scan lines then read the same data). The intended shortcut
  is **"Import alignment table"** with a CSV where `cell(r,c) = (r-1)*64 + c` (row 1 = 1–64,
  row 2 = 65–128, …). A generated raster CSV is in
  `ledvision/rcvbp/downloaded/align_full_raster.csv`.

### 5.8 Config files off the internet are password-walled
Hunting a ready `P3 64×64 1/32 FM6124/7258` `.rcvbp`:
- **colorlitled.com** P3 zip → inner zip is **AES-encrypted** (method 99); password behind
  a JS/email popup. Contains the ideal `P3-32S-64X64-FM6253+7258` but locked.
- **ledcontrollercard.com** → 12 `.rar` archives; filenames list but **extraction is
  password-protected** (common passwords fail).
- **seengreat.com** → the one *unencrypted* file… but it's the MBI5153 mismatch (§5.5).
- *Lesson: the vendor "free download" ecosystem is a lead-gen maze; budget for a password
  wall on anything actually useful.*

---

## 6. The clean way out — open gateware (no LEDVISION at all)

The ECP5 is reprogrammable, so you can replace the stock firmware and never touch
LEDVISION's config UI again. Saved for when the vendor path isn't worth it (see
`docs/reflash-v8.2.md` for the JTAG pinout and toolchain):

- **dgym/receiver75** — MIT replacement gateware for the 5A-75B **v8**, **hardcoded for
  64×64 panels, two per connector, 500 Hz**, scan/row-addressing done in the FPGA, driven
  by Python (`sender75.py`, `make_config.py`). Ships **prebuilt bitstreams**. This is
  essentially "the ESP32 HUB75 library, but in the card's FPGA."
- **q3k/chubby75** — the hardware reference (ECP5/flash/PHY part numbers, JTAG header,
  HUB75 pin map; V8.2 uses RTL8211FP PHYs, differs from older Broadcom-PHY revisions).

Deploy = JTAG flash (a ~$10 FT2232 adapter). **Back up the stock SPI flash first**
(`ecpprog`/`openocd` read-out) so the card is restorable to Colorlight firmware.

Recommended order: back up flash → flash a `receiver75` prebuilt bitstream → drive with
`sender75.py`. Fall back to chubby75's pinout for a LiteX/custom HUB75 target if needed.

---

## 7. Practical playbook (if you're doing this again)

1. **Power first.** 5 V supply rated **≥ 6–10 A** for a 64×64. Undersized power will
   masquerade as every kind of config failure. Check polarity.
2. **Direct cable, gigabit.** NIC ↔ card, no switch. Discovery's reply won't survive a
   switch (illegal source MAC).
3. **Confirm the card lives**: `cl5a75.py discover` (in `docker --net=host`), promiscuous
   mode. You want a `0x0805` reply and a firmware string.
4. **Driver IC = `Normal Chip`** for FM6124 panels (not the `FM6124` entry, which blanks).
   Decode = `7258`. These are manual — nothing auto-detects them.
5. **Scan = 1/32** for a 64×64. If you see 16 rows per half, you're at 1/16 and missing the
   E line. Scan is wizard-only in LEDVISION.
6. **Test with single colors, never white**, until power is confirmed. "Solid → rainbow" =
   wrong driver; "16 rows per half" = wrong scan; "flicker on patterns only" = scan/refresh.
7. **Capture once, replay forever.** Once a config works, capture the burst off the wire
   (`tools/cfgdump*.py`) and replay it from Linux with `cl5a75.py --config` — no LEDVISION
   after that.
8. **Or skip all of it** and flash `receiver75`.

---

## 8. Repo map

- `cl5a75.py` — layer-2 sender/discovery/pattern tool (wire-verified).
- `tools/` — `disc_sniff.py` (promiscuous discovery A/B), `cfgdump*.py` (capture config
  bursts), `pixcheck.py` (verify streamed pixel payloads), `extract_config.py`
  (pcap → replayable blob), `align_full_raster.csv` generator.
- `ledvision/` — Wine launcher, the `wpcap` shim source, captured `.rcvbp` files.
- `docs/config-protocol.md` — byte-level config packet notes + the driver-IC gotcha.
- `docs/reflash-v8.2.md` — open-gateware path (receiver75 + chubby75), JTAG pinout, HUB75
  pin map.
- `config/` — captured config blobs, the card's real discovery reply, LEDVISION's probe.

---

## 9. Status / open items (as of this writing)

- **Proven:** card healthy (fw v11.6); direct-link discovery; LEDVISION-under-Wine detects
  and drives live; switch-drop root cause; PSU brownout root cause; driver = Normal Chip;
  scan needs 1/32; a **stable, correct half-panel (1/16) config** exists.
- **Not yet closed:** a clean **full 64×64 (1/32)** config on the stock firmware — blocked
  only by LEDVISION's wizard (pixel-map/CSV import) and password-walled ready-made configs.
- **Cleanest path to done:** finish one wizard pass with the raster CSV *or* flash
  `receiver75`.

The hardware was never the problem. Power and a hostile vendor tool were.
