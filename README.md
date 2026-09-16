# hub75-board — Colorlight 5A-75B sender

`cl5a75.py` drives a Colorlight 5A-75B/5A-75E HUB75 receiver card over raw
layer-2 Ethernet (no IP). Protocol per Falcon Player's ColorLight-5a-75.cpp.

Raw sockets need CAP_NET_RAW. Either run with sudo, or use docker on the host
network (no password needed):

    D='docker run --rm --net=host -v "$PWD":/w -w /w python:3.12-slim python3'
    $D cl5a75.py -i eno1 discover              # prints fw version + stored panel size
    $D cl5a75.py -i eno1 --hold 5 fill 255 0 0 # solid red for 5 s
    $D cl5a75.py -i eno1 bars                  # colour bars
    $D cl5a75.py -i eno1 grid                  # geometry/scan-mapping test pattern
    $D cl5a75.py -i eno1 anim                  # moving gradient, ctrl-c to stop
    $D cl5a75.py -i eno1 image pic.png         # needs Pillow in the image

`-W/-H` set the framebuffer size (default 64x32), `-b` brightness, `--dup`
sends each packet twice (LEDVision does this for fw >= 13).

`tools/` has wire sniffers (`sniff_all.py`, `sniff_replies.py`) and `cycle.py`
(red/green/blue/white cycle with periodic discovery).

## Status 2026-09-14
Sender verified on the wire with a sniffer. The first card was powered with
reversed polarity; the FPGA survived (red power LED, amber status LED after
boot) but both Ethernet PHYs are dead: no link on either jack at an unmanaged
switch with a known-good cable. Waiting on a replacement card.

Notes: the destination MAC 11:22:33:44:55:66 is a multicast address, so keep
the card on an unmanaged switch or a direct cable; routers/mesh nodes with
multicast filtering may drop it. Once discovery answers, the card's stored
panel config (scan rate, size per HUB75 port) must match the panel or the
image will be scrambled; that config is normally written with LEDVision.
