# Running Colorlight LEDVISION 8.8 on Linux (Wine) to configure a 5A-75B

The 5A-75B receiver card stores its panel configuration (size, scan rate,
driver chip, port mapping) in flash, and the only tool that writes it is
Colorlight's Windows program LEDVISION.  This directory makes LEDVISION 8.8
work under Wine on Linux, including receiver-card detection and configuration
over the raw layer-2 protocol, so no Windows machine is needed.

Tested 2026-09-14 on Ubuntu, Wine 10.0, GNOME/Wayland, LEDVISION 8.8.41357.

## What breaks out of the box, and the fix for each

| Symptom | Cause | Fix |
|---|---|---|
| "WinPcap not installed" at startup | LEDVISION checks the registry key `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinPcapInst` | add the key (`setup-prefix.sh`) |
| Dialogs and password box ignore input | Wine popups on a Wayland desktop lose focus to LEDVISION's LED preview window | run inside a Wine virtual desktop (`explorer /desktop=...`) |
| Crash on ticking "Net Card" | LEDVISION crashes when it sees more than ~20 network adapters (docker bridges, veths) | run it in a network namespace holding a single macvlan child of the real NIC |
| Crash at startup inside the namespace (`LedMonitor.dll failed to initialize`) | the root user's Wine "My Documents" folder did not exist, so the DLL built a garbage path | launcher pre-creates `drive_c/users/root/Documents` |
| `unimplemented function wpcap.dll.pcap_sendqueue_alloc, aborting` | Wine's wpcap only stubs the WinPcap send-queue API that LEDVISION uses to transmit | `shim/wpcap.dll`: implements the 4 send-queue functions on top of Wine's `pcap_sendpacket`, forwards everything else to Wine's builtin |
| Raw sockets need root | layer-2 frames need CAP_NET_RAW | launcher runs Wine as root in a root-owned copy of the prefix (Wine refuses a prefix it doesn't own) |

Also useful to know: the card only links at gigabit, and its destination MAC
11:22:33:44:55:66 is a multicast address, so keep it on an unmanaged gigabit
switch (or a direct cable), not behind a router.

## Layout

- `setup-prefix.sh`  — one-time: create `~/.wine-ledvision`, install LEDVISION,
  add the WinPcap registry key, install the genuine VC2013 runtime, install the shim.
- `run-ledvision.sh` — run with `sudo`: syncs the prefix to `/root/.wine-ledvision`,
  builds the `clnet` namespace with macvlan `cl0` on `eno1`, launches LEDVISION
  in a Wine virtual desktop.  `--trace` adds a full Wine relay trace to the log.
- `shim/wpcap_shim.c`, `shim/build.sh` — the WinPcap send-queue shim (MinGW, built in docker).
  `shim/shimtest.c` is a tiny self-test.  Shim writes `C:\wpcap-shim.log` in the prefix.
- `ledvision-8.8.zip` — the installer as downloaded (sha256
  66d73833cb5a7fe05322089345c694b997e69a085958feb7518ec93d4f99d89a), from a
  reseller mirror listed on colorlight.net.

## Using it

    ./setup-prefix.sh                 # once
    sudo ./run-ledvision.sh           # each time

In LEDVISION: Control -> LED Screen Settings (password 168) -> Sending Device:
Net Card, choose cl0 -> Detect Receiver Cards.  Then Receiver Card Parameters
(Smart Settings wizard, or width/height/scan by hand) -> Send to Receiver ->
Save to Receiver.  Close LEDVISION before streaming pixels with `../cl5a75.py`,
since both use the same source MAC.
