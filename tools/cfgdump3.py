import socket, struct, time
IFACE = "eno1"
WANT = {0x05, 0x18, 0x17, 0x2b, 0x1b, 0x37, 0x40, 0x76, 0x7b, 0x7f, 0x83, 0x10, 0x1f}
rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); rx.bind((IFACE, 0)); rx.settimeout(0.3)
ifi = socket.if_nametoindex(IFACE)
rx.setsockopt(263, 1, struct.pack("IHH8s", ifi, 1, 0, b""))
t0 = time.time()
out = open("/app/tools/cfgcapture.txt", "w")
while time.time() - t0 < 150:
    try: p = rx.recv(2048)
    except socket.timeout: continue
    if len(p) < 14: continue
    t = p[12]
    if t in WANT:
        line = "%.1f 0x%02x len=%d: %s" % (time.time()-t0, t, len(p), p[12:12+56].hex(" "))
        print(line, flush=True); out.write(line+"\n"); out.flush()
out.close()
