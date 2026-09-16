#!/usr/bin/env python3
"""
Single-process panel probe: send + capture in ONE process (no docker-background
+ separate-camera coordination). Sends a config + test pattern continuously on a
thread while capturing the C920, then reports the panel's dominant colour so you
instantly know whether the content actually landed.

Run (opencv image from Dockerfile.probe):
  docker run --rm --net=host --privileged --device=/dev/video0 \
    -v "$PWD":/app -w /app panelprobe \
    python tools/panelprobe.py --config library/configs/cfg_04_*.bin \
      --pattern fill:255,255,255 --cw 256 --ch 512 --secs 6 --out /app/probe.png

--pattern: fill:R,G,B | bars | grid | replay:<pcap-frame.bin>
"""
import argparse, threading, time, glob, sys, struct
import numpy as np
import cv2
import cl5a75


def build_fb(pattern, w, h):
    if pattern.startswith("fill:"):
        r, g, b = (int(x) for x in pattern[5:].split(","))
        return cl5a75.fb_solid(w, h, r, g, b)
    if pattern == "bars":
        return cl5a75.fb_bars(w, h)
    if pattern == "grid":
        return cl5a75.fb_grid(w, h)
    raise SystemExit("unknown pattern " + pattern)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--iface", default="eno1")
    ap.add_argument("--config", help="config blob glob to apply first")
    ap.add_argument("--pattern", default="fill:255,255,255")
    ap.add_argument("-W", "--width", type=int, default=256)
    ap.add_argument("-H", "--height", type=int, default=512)
    ap.add_argument("--cw", type=int, default=256)
    ap.add_argument("--ch", type=int, default=512)
    ap.add_argument("--px", type=int, default=0)
    ap.add_argument("--py", type=int, default=0)
    ap.add_argument("-b", "--brightness", type=int, default=200)
    ap.add_argument("--fps", type=float, default=60)
    ap.add_argument("--secs", type=float, default=6)
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--expo", type=int, default=320)
    ap.add_argument("--out", default="/app/probe.png")
    ap.add_argument("--replay", help="raw length-prefixed frame blob to replay verbatim instead of pattern")
    a = ap.parse_args()

    snd = cl5a75.Sender(a.iface, a.width, a.height, a.brightness, False,
                        canvas_w=a.cw, canvas_h=a.ch, px=a.px, py=a.py)
    if a.config:
        blob = sorted(glob.glob(a.config))[0]
        frames = cl5a75.load_config_blob(blob)
        print(f"applying {len(frames)} config frames from {blob}", flush=True)
        snd.send_raw_frames(frames)

    replay_frames = cl5a75.load_config_blob(a.replay) if a.replay else None
    fb = None if replay_frames else build_fb(a.pattern, a.width, a.height)

    stop = threading.Event()
    def sender():
        while not stop.is_set():
            if replay_frames:
                for fr in replay_frames:
                    snd.sock.send(fr)
            else:
                snd.show(fb)
            time.sleep(1.0 / a.fps)
    t = threading.Thread(target=sender, daemon=True); t.start()
    print(f"streaming {'replay' if replay_frames else a.pattern} at ~{a.fps}fps", flush=True)

    # camera
    cam = cv2.VideoCapture(a.cam, cv2.CAP_V4L2)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1920); cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    cam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1); cam.set(cv2.CAP_PROP_AUTO_WB, 0)
    cam.set(cv2.CAP_PROP_GAIN, 0); cam.set(cv2.CAP_PROP_WB_TEMPERATURE, 4500)
    cam.set(cv2.CAP_PROP_EXPOSURE, a.expo)
    time.sleep(a.secs)                       # let the stream settle
    for _ in range(8): cam.read()
    ok, frame = cam.read()
    stop.set()
    if not ok:
        raise SystemExit("camera grab failed")
    cv2.imwrite(a.out, frame)

    # crude panel-colour readout: brightest 5% of pixels' mean BGR
    flat = frame.reshape(-1, 3).astype(np.float32)
    lum = flat.sum(axis=1)
    bright = flat[lum > np.percentile(lum, 95)]
    b, g, r = bright.mean(axis=0)
    print(f"wrote {a.out}  panel dominant BGR=({b:.0f},{g:.0f},{r:.0f})  "
          f"-> {'RED' if r>g and r>b else 'GREEN' if g>r and g>b else 'BLUE' if b>r and b>g else 'WHITE/GREY'}",
          flush=True)


if __name__ == "__main__":
    main()
