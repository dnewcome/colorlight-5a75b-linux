import socket, sys, struct, time
IFACE = "eno1"
WANT = {0x05, 0x18, 0x17, 0x2b, 0x1b, 0x37, 0x40, 0x76, 0x83}
rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); rx.bind((IFACE, 0)); rx.settimeout(0.3)
ifi = socket.if_nametoindex(IFACE)
rx.setsockopt(263, 1, struct.pack("IHH8s", ifi, 1, 0, b""))
seen = {}
t0 = time.time()
print("capturing 45s — click Send to Receiver in LEDVISION now...", flush=True)
while time.time() - t0 < 45:
    try: p = rx.recv(2048)
    except socket.timeout: continue
    if len(p) < 14: continue
    t = p[12]
    if t in WANT and t not in seen:
        seen[t] = p[12:12 + 40]
        print("got 0x%02x" % t, flush=True)
for t in sorted(seen):
    print("0x%02x: %s" % (t, seen[t].hex(" ")))
if 0x05 in seen:
    d = seen[0x05]
    print("  -- 0x05 geometry bytes[7:20]:", d[7:20].hex(" "))
