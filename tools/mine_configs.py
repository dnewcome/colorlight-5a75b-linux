#!/usr/bin/env python3
"""
Stream a (possibly huge) pcap of LEDVISION traffic and mine the receiver-card
CONFIG bursts out of it, deduped, into a config-template library.

This is phase 1 of the baked-in knowledge library (GH #12): distill what the
Windows tool emitted so nobody has to run it. Streams packet-by-packet, so it
handles multi-GB captures that won't fit in RAM.

Usage:
  mine_configs.py <pcap>                      # inventory (type/MAC histogram)
  mine_configs.py <pcap> --save library/configs   # extract+dedupe bursts -> dir + index.json
"""
import struct, sys, json, os, hashlib
from collections import Counter

STREAM = {0x01, 0x0a, 0x55}     # display sync / brightness / pixel-row
DISC   = {0x07, 0x08}           # discovery probe / reply
SRC_SENDER = bytes.fromhex("222233445566")
DST_CARD   = bytes.fromhex("112233445566")


def stream_pcap(path):
    """Yield raw ethernet frames from a pcap, without loading the file."""
    with open(path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return
        magic = struct.unpack("<I", gh[:4])[0]
        le = magic in (0xa1b2c3d4, 0xa1b23c4d)
        end = "<" if le else ">"
        while True:
            rh = f.read(16)
            if len(rh) < 16:
                return
            _ts, _us, caplen, _ol = struct.unpack(end + "IIII", rh)
            data = f.read(caplen)
            if len(data) < caplen:
                return
            yield data


def geometry(burst):
    """Pull width/height/scan hints from the 0x05 packet if present."""
    for p in burst:
        if p[12] == 0x05 and len(p) > 30:
            d = p[13:]
            # per docs/config-protocol.md the 0x05 payload carries width/height ~bytes 15-18
            w = (d[16] << 8) | d[17] if len(d) > 17 else 0
            h = (d[18] << 8) | d[19] if len(d) > 19 else 0
            return {"w_guess": w, "h_guess": h, "raw05": d[:24].hex(" ")}
    return {}


def signature(burst):
    types = Counter(p[12] for p in burst)
    total = sum(len(p) for p in burst)
    h = hashlib.sha1(b"".join(bytes([p[12]]) + p[:0] for p in burst)).hexdigest()[:8]
    # content hash of the whole burst (dedupe identical configs)
    ch = hashlib.sha1(b"".join(burst)).hexdigest()[:12]
    return {"types": {f"0x{t:02x}": n for t, n in sorted(types.items())},
            "n_packets": len(burst), "total_bytes": total, "content": ch}


def mine(path, save_dir=None):
    type_hist, dst_hist, src_hist = Counter(), Counter(), Counter()
    cur, bursts = [], []
    seen = set()
    n = 0
    for p in stream_pcap(path):
        n += 1
        if len(p) < 14:
            continue
        dst_hist[p[:6].hex(":")] += 1
        src_hist[p[6:12].hex(":")] += 1
        t = p[12]
        type_hist[t] += 1
        if p[6:12] != SRC_SENDER:
            continue
        if t in STREAM:
            if any(q[12] not in DISC for q in cur):
                bursts.append(cur)
            cur = []
        elif t in DISC:
            continue
        else:
            cur.append(p)
    if any(q[12] not in DISC for q in cur):
        bursts.append(cur)

    print(f"# {path}\n# {n} frames")
    print("## ethertype/type byte histogram (byte 12):")
    for t, c in type_hist.most_common(20):
        print(f"   0x{t:02x}: {c}")
    print("## top src MACs:", dict(src_hist.most_common(4)))
    print("## top dst MACs:", dict(dst_hist.most_common(4)))
    print(f"## {len(bursts)} candidate config bursts")

    uniq = []
    for b in bursts:
        sig = signature(b)
        if sig["content"] in seen:
            continue
        seen.add(sig["content"])
        uniq.append((b, sig))
    print(f"## {len(uniq)} UNIQUE config bursts (by content)\n")

    index = []
    for i, (b, sig) in enumerate(sorted(uniq, key=lambda x: -x[1]["n_packets"])):
        geo = geometry(b)
        rec = {"i": i, **sig, **geo}
        index.append(rec)
        print(f"[{i}] {sig['n_packets']} pkts, {sig['total_bytes']} B, "
              f"types={list(sig['types'])}, {geo.get('raw05','')[:30]}")
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            name = f"burst_{i:02d}_{sig['content']}.bin"
            with open(os.path.join(save_dir, name), "wb") as o:
                for p in b:
                    o.write(struct.pack(">H", len(p)) + p)
            rec["file"] = name
    if save_dir:
        with open(os.path.join(save_dir, "index.json"), "w") as o:
            json.dump(index, o, indent=2)
        print(f"\n# wrote {len(uniq)} bursts + index.json to {save_dir}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    save = sys.argv[sys.argv.index("--save") + 1] if "--save" in sys.argv else None
    mine(args[0], save)
