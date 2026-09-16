"""Capture Colorlight traffic (to/from 11:22:33:44:55:66 or 22:22:33:44:55:66, plus any
non-IP ethertype) into a pcap file for later analysis/replay. Usage: capture_pcap.py out.pcap [seconds]"""
import socket, struct, sys, time
out, dur = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 3600
CL = {bytes.fromhex("112233445566"), bytes.fromhex("222233445566")}
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); s.bind(("eno1", 0)); s.settimeout(0.5)
f = open(out, "wb"); f.write(struct.pack("<IHHiIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)); f.flush()
t_end = time.time() + dur; n = 0; types = {}
while time.time() < t_end:
    try: p = s.recv(65535)
    except socket.timeout: continue
    et = int.from_bytes(p[12:14], "big")
    if not (p[0:6] in CL or p[6:12] in CL or et < 0x0600 or et in (0x0805,)):
        if et in (0x0800, 0x86dd, 0x0806, 0x893a, 0x88cc): continue
    ts = time.time(); f.write(struct.pack("<IIII", int(ts), int((ts % 1) * 1e6), len(p), len(p)) + p); n += 1
    types[p[12]] = types.get(p[12], 0) + 1
    f.flush()
    if n % 100 == 1: print(n, {hex(k): v for k, v in sorted(types.items())}, flush=True)
f.close(); print("done", n, {hex(k): v for k, v in sorted(types.items())}, flush=True)
