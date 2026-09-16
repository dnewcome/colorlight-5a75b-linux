import socket, time, sys
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 30
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
s.bind(("eno1", 0)); s.settimeout(0.2)
t_end = time.time() + dur; n = 0
while time.time() < t_end:
    try: p = s.recv(4096)
    except socket.timeout: continue
    if p[0:6] == bytes.fromhex("112233445566"): continue   # our own outgoing frames
    if p[6:12] == bytes.fromhex("222233445566") or p[12] in (0x08,) and p[13] == 0x05:
        n += 1; print(len(p), p[:96].hex(" "), flush=True)
print("replies seen:", n)
