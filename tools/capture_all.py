"""Capture EVERY frame on eno1 (no filtering) to find any card-originated traffic.
Prints each non-IP-noise frame with source MAC, and flags anything from a new MAC."""
import socket, time, sys
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 60
OURS = {bytes.fromhex("112233445566"), bytes.fromhex("222233445566")}
NOISE_ET = {0x0800, 0x86dd, 0x0806}   # IPv4, IPv6, ARP
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); s.bind(("eno1", 0)); s.settimeout(0.5)
seen_macs = {}
t_end = time.time() + dur; n = 0
print(f"capturing all frames for {dur:.0f}s ...", flush=True)
while time.time() < t_end:
    try: p = s.recv(65535)
    except socket.timeout: continue
    if len(p) < 14: continue
    src = p[6:12]; dst = p[0:6]; et = int.from_bytes(p[12:14], "big")
    n += 1
    key = src.hex(":")
    if key not in seen_macs:
        seen_macs[key] = 0
        print(f"[new MAC] src={src.hex(':')} dst={dst.hex(':')} ethertype/type=0x{et:04x} len={len(p)}  first={p[:32].hex(' ')}", flush=True)
    seen_macs[key] += 1
    # always print non-IP, non-ours frames (potential card traffic)
    if src not in OURS and et not in NOISE_ET and et != 0x893a:
        print(f"  frame src={src.hex(':')} type=0x{et:04x} len={len(p)} {p[12:40].hex(' ')}", flush=True)
print("--- summary: frames per source MAC ---", flush=True)
for m, c in sorted(seen_macs.items(), key=lambda x:-x[1]): print(f"  {c:6}  {m}", flush=True)
