import socket, collections, sys, struct
IFACE = sys.argv[1] if len(sys.argv) > 1 else "eno1"
rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); rx.bind((IFACE, 0)); rx.settimeout(0.3)
import struct as _st
ifi = socket.if_nametoindex(IFACE)
rx.setsockopt(263, 1, _st.pack("IHH8s", ifi, 1, 0, b""))  # promisc
import time
t0 = time.time(); n55 = 0; nonzero = 0; maxv = 0; rows = set(); offs = set(); sample = None
hist = collections.Counter()
while time.time() - t0 < 4:
    try: p = rx.recv(2048)
    except socket.timeout: continue
    if len(p) < 22 or p[12] != 0x55: continue
    n55 += 1
    row = (p[13] << 8) | p[14]; off = (p[15] << 8) | p[16]; cnt = (p[17] << 8) | p[18]
    rows.add(row); offs.add(off)
    rgb = p[21:21 + cnt * 3]  # data hdr is 8 bytes: 13..20, rgb from 21
    m = max(rgb) if rgb else 0
    if m > 0: nonzero += 1
    if m > maxv: maxv = m; sample = (row, off, cnt, p[21:21+24].hex(" "))
    hist[m] += 1
print(f"0x55 frames: {n55}  nonzero-payload: {nonzero}  max byte value seen: {maxv}")
print(f"distinct rows: {sorted(rows)[:40]} (n={len(rows)})")
print(f"distinct offsets: {sorted(offs)}")
print(f"payload-max histogram (value:count): {dict(sorted(hist.items())[:10])}")
if sample: print("brightest sample row=%d off=%d cnt=%d rgb[0:24]=%s" % sample)
