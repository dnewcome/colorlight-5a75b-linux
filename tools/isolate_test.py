"""Runs offline on eno1: logs link speed/carrier AND every non-LAN frame to a file.
Reads link state from /sys/class/net/eno1 so it needs no host tools or internet."""
import socket, time, sys

def link():
    try: sp = open("/sys/class/net/eno1/speed").read().strip()
    except Exception: sp = "?"
    try: car = open("/sys/class/net/eno1/carrier").read().strip()
    except Exception: car = "?"
    return f"carrier={car} speed={sp}Mb"

OURS = {bytes.fromhex("112233445566"), bytes.fromhex("222233445566")}
NOISE = {0x0800, 0x86dd, 0x0806, 0x893a}
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 240
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); s.bind(("eno1", 0)); s.settimeout(0.5)
t0 = time.time(); t_end = t0 + dur; last_link = None; next_link = 0
seen = {}
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)
log("START  " + link())
while time.time() < t_end:
    now = time.time()
    if now >= next_link:
        l = link()
        if l != last_link: log("LINK-> " + l); last_link = l
        next_link = now + 2
    try: p = s.recv(65535)
    except socket.timeout: continue
    if len(p) < 14: continue
    src = p[6:12]; et = int.from_bytes(p[12:14], "big")
    k = src.hex(":")
    if k not in seen:
        seen[k] = 0; log(f"NEW-MAC src={k} dst={p[0:6].hex(':')} type=0x{et:04x} len={len(p)} {p[:32].hex(' ')}")
    seen[k] += 1
    if src not in OURS and et not in NOISE:
        log(f"  FRAME src={k} type=0x{et:04x} len={len(p)} {p[12:44].hex(' ')}")
log("END  " + link())
log("--- per-MAC frame counts ---")
for m, c in sorted(seen.items(), key=lambda x: -x[1]): log(f"  {c:6}  {m}")
