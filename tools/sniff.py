import socket, time, collections
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
s.bind(("eno1", 0)); s.settimeout(0.2)
t_end = time.time() + 6
seen = collections.Counter(); samples = {}
while time.time() < t_end:
    try: p = s.recv(4096)
    except socket.timeout: continue
    et = int.from_bytes(p[12:14], "big")
    if et in (0x0800, 0x86dd, 0x0806): continue   # skip IP/ARP
    key = (p[6:12].hex(":"), p[0:6].hex(":"), hex(et))
    seen[key] += 1; samples.setdefault(key, p[:80].hex(" "))
for k, n in seen.most_common(20):
    print(n, k, "\n   ", samples[k])
print("done")
