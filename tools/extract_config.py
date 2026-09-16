#!/usr/bin/env python3
"""Extract the Colorlight receiver-card config burst from a pcap and (a) save it as a
length-prefixed replay blob, (b) print a per-packet-type analysis. See docs/config-protocol.md."""
import struct, sys, glob
from collections import Counter, OrderedDict

STREAM = {0x01, 0x0a, 0x55}          # display sync / brightness / pixel-row
DISC   = {0x07, 0x08}                 # discovery probe / reply
SRC_SENDER = bytes.fromhex("222233445566")

def read_pcap(path):
    d = open(path, "rb").read(); off = 24
    while off + 16 <= len(d):
        ts, us, cl, ol = struct.unpack("<IIII", d[off:off+16]); p = d[off+16:off+16+cl]; off += 16+cl
        yield p

def config_burst(path):
    pkts = [p for p in read_pcap(path) if len(p) >= 14 and p[6:12] == SRC_SENDER]
    runs, cur = [], []
    for p in pkts:
        t = p[12]
        if t in STREAM:
            if any(q[12] not in DISC for q in cur): runs.append(cur)
            cur = []
        else:
            cur.append(p)
    if any(q[12] not in DISC for q in cur): runs.append(cur)
    def score(r): return len(set(q[12] for q in r if q[12] not in DISC))
    best = max(runs, key=lambda r: (score(r), len(r)))
    return [p for p in best if p[12] not in DISC]

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--") and sys.argv[sys.argv.index(a)-1] != "--save"]
    path = args[0] if args else sorted(glob.glob("captures/*.pcap"))[-1]
    burst = config_burst(path)
    print(f"# source: {path}\n# {len(burst)} config packets in the winning burst\n")
    # replay blob
    if "--save" in sys.argv:
        out = sys.argv[sys.argv.index("--save")+1]
        with open(out, "wb") as o:
            for p in burst: o.write(struct.pack(">H", len(p)) + p)
        print(f"# wrote replay blob {out}")
    # per-type analysis
    bytype = OrderedDict()
    for p in burst: bytype.setdefault(p[12], []).append(p)
    for t, ps in bytype.items():
        lens = sorted(set(len(p) for p in ps))
        p = ps[0]; data = p[13:]
        print(f"## type 0x{t:02x}  x{len(ps)}  frame_len={lens}  data_len={[l-13 for l in lens]}")
        print(f"   first 48 data bytes: {data[:48].hex(' ')}")
        if len(ps) > 1 and t in (0x1b, 0x03, 0x83, 0x37, 0x32, 0x26):
            # show how successive packets of same type differ in their first 8 data bytes (index fields)
            for q in ps[:6]:
                print(f"     idx bytes: {q[13:13+8].hex(' ')}  (len {len(q)})")
        print()

if __name__ == "__main__":
    main()
