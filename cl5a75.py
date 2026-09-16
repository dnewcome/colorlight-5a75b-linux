#!/usr/bin/env python3
"""
Minimal Colorlight 5A-75B/5A-75E receiver-card sender (layer-2 Ethernet).

Protocol (reverse engineered; see Falcon Player ColorLight-5a-75.cpp,
hkubota.wordpress.com, mylifesucks.de/oss/mplayer-colorlight):

  Ethernet frame:  dst 11:22:33:44:55:66  src 22:22:33:44:55:66
  bytes 12..13 (the "ethertype") = [packet_type, data[0]]

  0x0A  brightness   data = [b, b, b, 0xff] + zero padding   (77-byte frame)
  0x55  pixel row    data = [row>>8, row, off>>8, off, n>>8, n, 0x08, 0x88] + RGB*n
  0x01  sync/display data[0]=0x07, data[22]=b, data[23]=0x05, data[25..27]=b (112-byte frame)
  0x07  discover     284-byte frame, receiver replies with type 0x08 (1070 bytes)

Needs CAP_NET_RAW: run with sudo (or inside `docker run --net=host`).
"""
import argparse, socket, struct, sys, time, math

DST = bytes.fromhex("112233445566")
SRC = bytes.fromhex("222233445566")
MAX_PIX_PER_PKT = 497


def frame(ptype, data, min_len=0):
    p = DST + SRC + bytes([ptype]) + data
    if len(p) < min_len:
        p += bytes(min_len - len(p))
    return p


def pkt_brightness(b):
    return frame(0x0A, bytes([b, b, b, 0xFF]), 77)


def pkt_sync(b):
    d = bytearray(99)
    d[0] = 0x07
    d[22] = b
    d[23] = 0x05
    d[25] = d[26] = d[27] = b
    return frame(0x01, bytes(d), 112)


def pkt_row(row, offset, rgb):
    n = len(rgb) // 3
    hdr = struct.pack(">HHHBB", row, offset, n, 0x08, 0x88)
    return frame(0x55, hdr + rgb)


def pkt_discover(idx=0):
    d = bytearray(271)
    d[3] = idx
    return frame(0x07, bytes(d), 284)


class Sender:
    def __init__(self, iface, width, height, brightness=255, dup=False,
                 canvas_w=0, canvas_h=0, px=0, py=0):
        self.iface, self.w, self.h, self.b, self.dup = iface, width, height, brightness, dup
        # The card has a FIXED internal framebuffer (e.g. 256x512); a small panel
        # maps to a sub-rectangle of it, and the card wants FULL-width rows.
        # LEDVISION always sends canvas_w=256, offset 0. Set canvas_w>0 to match.
        self.cw = canvas_w or width
        self.ch = canvas_h or height
        self.px, self.py = px, py
        self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
        self.sock.bind((iface, 0))

    def send(self, p):
        self.sock.send(p)
        if self.dup:
            self.sock.send(p)

    def send_raw_frames(self, frames, gap=0.002):
        """Send pre-captured raw Ethernet frames (e.g. a receiver-card config burst)."""
        for fr in frames:
            self.sock.send(fr)
            if gap:
                time.sleep(gap)

    def show(self, fb):
        """fb: bytes of w*h*3 RGB, row-major. Composited into the card's cw x ch
        internal canvas at (px, py); full canvas-width rows are sent (what the card
        actually wants). For cw==w and px==py==0 this is the original behaviour."""
        assert len(fb) == self.w * self.h * 3, (len(fb), self.w, self.h)
        self.send(pkt_brightness(self.b))
        cstride = self.cw * 3
        pstride = self.w * 3
        for cy in range(self.ch):
            # build one full canvas row (default black), overlay the panel if in range
            crow = bytearray(cstride)
            fy = cy - self.py
            if 0 <= fy < self.h:
                src = fb[fy * pstride:(fy + 1) * pstride]
                crow[self.px * 3:self.px * 3 + pstride] = src
            off = 0
            while off < self.cw:
                n = min(MAX_PIX_PER_PKT, self.cw - off)
                self.send(pkt_row(cy, off, bytes(crow[off * 3:(off + n) * 3])))
                off += n
        self.send(pkt_sync(self.b))

    def discover(self, timeout=0.5):
        rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0805))
        rx.bind((self.iface, 0))
        rx.settimeout(timeout)
        found = []
        for idx in range(8):
            self.sock.send(pkt_discover(idx))
            try:
                while True:
                    p = rx.recv(2048)
                    if len(p) < 100 or p[12] != 0x08:
                        continue
                    d = p[13:]
                    info = dict(
                        card=d[0], fw=f"{d[2]}.{d[3]}",
                        width=(d[21] << 8) | d[22], height=(d[23] << 8) | d[24],
                        packets=int.from_bytes(d[38:42], "big"),
                        uptime_ms=int.from_bytes(d[46:50], "big"),
                        receiver_id=d[85], raw_len=len(p))
                    found.append(info)
                    print("reply:", info)
                    print("  data[0:64]:", d[:64].hex(" "))
            except socket.timeout:
                pass
            if not found:
                break  # no receiver at this index
        return found


def load_config_blob(path):
    """Read a length-prefixed config blob ([u16 be len][frame]...) into a list of raw frames."""
    out = []
    with open(path, "rb") as f:
        data = f.read()
    off = 0
    while off + 2 <= len(data):
        n = (data[off] << 8) | data[off + 1]
        off += 2
        out.append(data[off:off + n])
        off += n
    return out


# ---------- patterns ----------
def fb_solid(w, h, r, g, b):
    return bytes([r, g, b]) * (w * h)


def fb_bars(w, h):
    cols = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255), (255, 255, 255), (64, 64, 64)]
    out = bytearray()
    for y in range(h):
        for x in range(w):
            out += bytes(cols[(x * len(cols)) // w])
    return bytes(out)


def fb_gradient(w, h, t=0.0):
    out = bytearray()
    for y in range(h):
        for x in range(w):
            r = int(127 + 127 * math.sin(x / w * 6.28 + t))
            g = int(127 + 127 * math.sin(y / h * 6.28 + t * 1.3))
            b = int(127 + 127 * math.sin((x + y) / (w + h) * 6.28 - t))
            out += bytes((r, g, b))
    return bytes(out)


def fb_grid(w, h):
    """Corner markers + 8px grid: use this to figure out panel geometry / scan mapping."""
    out = bytearray(w * h * 3)
    def px(x, y, c):
        if 0 <= x < w and 0 <= y < h:
            i = (y * w + x) * 3
            out[i:i + 3] = bytes(c)
    for y in range(h):
        for x in range(w):
            if x % 8 == 0 or y % 8 == 0:
                px(x, y, (40, 40, 40))
    for x in range(w):
        px(x, 0, (255, 0, 0))          # top edge red
    for y in range(h):
        px(0, y, (0, 255, 0))          # left edge green
    px(0, 0, (255, 255, 255))
    px(w - 1, h - 1, (0, 0, 255))     # bottom-right blue
    return bytes(out)


def fb_image(w, h, path):
    from PIL import Image
    im = Image.open(path).convert("RGB").resize((w, h))
    return im.tobytes()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--iface", default="eno1")
    ap.add_argument("-W", "--width", type=int, default=64, help="total framebuffer width sent to the card")
    ap.add_argument("-H", "--height", type=int, default=32)
    ap.add_argument("-b", "--brightness", type=int, default=255)
    ap.add_argument("--dup", action="store_true", help="send every packet twice (LEDVision does this for fw>=13)")
    ap.add_argument("--cw", type=int, default=0, help="card internal canvas width (LEDVISION uses 256); 0 = same as -W")
    ap.add_argument("--ch", type=int, default=0, help="card internal canvas height (rows to send); 0 = same as -H")
    ap.add_argument("--px", type=int, default=0, help="panel X offset within the card canvas")
    ap.add_argument("--py", type=int, default=0, help="panel Y offset within the card canvas")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--hold", type=float, default=0, help="seconds to keep re-sending a static frame (0 = send once)")
    ap.add_argument("--config", help="apply a captured receiver-card config blob before doing anything else")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    sc = sub.add_parser("config", help="replay a captured receiver-card config blob and exit")
    sc.add_argument("blob")
    s = sub.add_parser("fill"); s.add_argument("r", type=int); s.add_argument("g", type=int); s.add_argument("b", type=int)
    sub.add_parser("off")
    sub.add_parser("bars")
    sub.add_parser("grid")
    sub.add_parser("anim")
    s = sub.add_parser("image"); s.add_argument("path")
    s = sub.add_parser("pixel", help="light a single pixel"); s.add_argument("x", type=int); s.add_argument("y", type=int)
    a = ap.parse_args()

    snd = Sender(a.iface, a.width, a.height, a.brightness, a.dup,
                 canvas_w=a.cw, canvas_h=a.ch, px=a.px, py=a.py)
    if a.config:
        frames = load_config_blob(a.config)
        print(f"applying {len(frames)} config frames from {a.config}")
        snd.send_raw_frames(frames)
    if a.cmd == "config":
        frames = load_config_blob(a.blob)
        print(f"applying {len(frames)} config frames from {a.blob}")
        snd.send_raw_frames(frames)
        print("config sent")
        return
    if a.cmd == "discover":
        r = snd.discover()
        print(f"{len(r)} receiver(s) found")
        return

    if a.cmd == "anim":
        t0 = time.time()
        while True:
            snd.show(fb_gradient(a.width, a.height, time.time() - t0))
            time.sleep(1 / a.fps)

    if a.cmd == "fill":
        fb = fb_solid(a.width, a.height, a.r, a.g, a.b)
    elif a.cmd == "off":
        fb = fb_solid(a.width, a.height, 0, 0, 0)
    elif a.cmd == "bars":
        fb = fb_bars(a.width, a.height)
    elif a.cmd == "grid":
        fb = fb_grid(a.width, a.height)
    elif a.cmd == "image":
        fb = fb_image(a.width, a.height, a.path)
    elif a.cmd == "pixel":
        fb = bytearray(a.width * a.height * 3)
        i = (a.y * a.width + a.x) * 3
        fb[i:i + 3] = b"\xff\xff\xff"
        fb = bytes(fb)

    t_end = time.time() + a.hold
    while True:
        snd.show(fb)
        if time.time() >= t_end:
            break
        time.sleep(1 / a.fps)
    print("sent")


if __name__ == "__main__":
    main()
