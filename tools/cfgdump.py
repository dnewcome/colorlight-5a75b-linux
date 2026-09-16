import socket, sys, struct, time
IFACE = sys.argv[1] if len(sys.argv) > 1 else "eno1"
WANT = {0x05, 0x18, 0x17, 0x2b, 0x1b, 0x0a, 0x01}
rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); rx.bind((IFACE, 0)); rx.settimeout(0.3)
ifi = socket.if_nametoindex(IFACE)
rx.setsockopt(263, 1, struct.pack("IHH8s", ifi, 1, 0, b""))
seen = {}
t0 = time.time()
while time.time() - t0 < 6 and len(seen) < len(WANT):
    try: p = rx.recv(2048)
    except socket.timeout: continue
    if len(p) < 14: continue
    t = p[12]
    if t in WANT and t not in seen:
        seen[t] = p[12:12 + 48]  # type byte + 47 data bytes
for t in sorted(seen):
    print("0x%02x len-shown=%d: %s" % (t, len(seen[t]), seen[t].hex(" ")))
