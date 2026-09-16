import socket, time, sys, collections
dur = float(sys.argv[1])
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); s.bind(("eno1", 0)); s.settimeout(0.2)
t_end = time.time() + dur; seen = collections.Counter(); sample = {}
while time.time() < t_end:
    try: p = s.recv(4096)
    except socket.timeout: continue
    if p[0:6] == bytes.fromhex("112233445566"): continue
    k = (p[6:12].hex(":"), p[0:6].hex(":"), hex(int.from_bytes(p[12:14], "big")))
    seen[k] += 1; sample.setdefault(k, p[:48].hex(" "))
for k, n in sorted(seen.items()):
    print(n, k, sample[k][:80])
