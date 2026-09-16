#!/usr/bin/env python3
"""
Camera-in-the-loop autotuner / auto-mapper for a HUB75 panel driven by cl5a75.

The idea (see GH issue #11): send a test pattern -> photograph the panel ->
dewarp the photo to the panel's WxH grid -> read back what each LED did ->
score it. This turns the human "does it look right?" round trip into an
automated fitness function, and the single-pixel walk auto-builds the pixel
alignment map that LEDVISION makes you click 2048 times.

STATUS: scaffold. Vision (calibrate/readout), the walk patterns, the scorers,
and pixel-map CSV export work today (they only need pixel send, which cl5a75
already does, on top of *any* base config). The parameter SEARCH is stubbed
until we can emit config programmatically (issue #6 make_config()).

------------------------------------------------------------------------------
THE ONE CAMERA SETTING THAT MATTERS: EXPOSURE vs SCAN  (issue #11 discussion)

The panel is multiplexed: only the currently-addressed rows are lit at any
instant. A short exposure freezes a slice mid-scan -> you photograph "one part
of the scan" (a bright band, rest dark). To read the WHOLE panel the exposure
must cover at least one full-frame refresh, ideally 2-4x:

    exposure_seconds >= FRAMES_TO_INTEGRATE / panel_refresh_hz

For a 240 Hz refresh that's >= ~4 ms; use 1/30 s (33 ms) for margin and to
average out PWM. Long exposure too bright? lower ISO/gain or panel brightness,
don't shorten the shutter.

Two capture modes:
  MODE_CONFIG  -> long exposure, single frame  (coverage / color / geometry)
  MODE_FLICKER -> short exposure, high-fps burst (temporal variance = flicker)
------------------------------------------------------------------------------

Deps: opencv-python, numpy, and cl5a75 (same repo). Needs CAP_NET_RAW for the
raw socket (run via sudo, or docker --net=host --device=/dev/video0).
"""
import argparse, time, sys, csv
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # vision commands will error clearly; send-only paths still work

import cl5a75


# ---------------------------------------------------------------- panel driver
class Panel:
    """Thin wrapper over cl5a75.Sender for emitting test patterns."""
    def __init__(self, iface, w, h, brightness=255, dup=False, hold=0.25):
        self.w, self.h, self.hold = w, h, hold
        self.snd = cl5a75.Sender(iface, w, h, brightness, dup)

    def _show(self, fb):
        # re-send for `hold` seconds so the camera always catches a fresh frame
        t_end = time.time() + self.hold
        while True:
            self.snd.show(fb)
            if time.time() >= t_end:
                break
            time.sleep(0.02)

    def solid(self, r, g, b):
        self._show(cl5a75.fb_solid(self.w, self.h, r, g, b))

    def clear(self):
        self.solid(0, 0, 0)

    def pixel(self, x, y, c=(255, 255, 255)):
        fb = bytearray(self.w * self.h * 3)
        i = (y * self.w + x) * 3
        fb[i:i + 3] = bytes(c)
        self._show(bytes(fb))

    def row(self, y, c=(255, 255, 255)):
        fb = bytearray(self.w * self.h * 3)
        for x in range(self.w):
            i = (y * self.w + x) * 3
            fb[i:i + 3] = bytes(c)
        self._show(bytes(fb))

    def col(self, x, c=(255, 255, 255)):
        fb = bytearray(self.w * self.h * 3)
        for y in range(self.h):
            i = (y * self.w + x) * 3
            fb[i:i + 3] = bytes(c)
        self._show(bytes(fb))

    def corner_markers(self):
        """White border + distinct corners for homography calibration."""
        fb = bytearray(self.w * self.h * 3)
        def px(x, y, c):
            if 0 <= x < self.w and 0 <= y < self.h:
                i = (y * self.w + x) * 3
                fb[i:i + 3] = bytes(c)
        for x in range(self.w):
            px(x, 0, (255, 255, 255)); px(x, self.h - 1, (255, 255, 255))
        for y in range(self.h):
            px(0, y, (255, 255, 255)); px(self.w - 1, y, (255, 255, 255))
        # unique corner blobs to disambiguate orientation
        for (cx, cy, col) in [(1, 1, (255, 0, 0)), (self.w - 2, 1, (0, 255, 0)),
                              (1, self.h - 2, (0, 0, 255)), (self.w - 2, self.h - 2, (255, 255, 0))]:
            px(cx, cy, col)
        self._show(bytes(fb))


# --------------------------------------------------------------------- camera
MODE_CONFIG, MODE_FLICKER = "config", "flicker"

class Camera:
    def __init__(self, index=0, refresh_hz=240.0, frames_to_integrate=3.0):
        if cv2 is None:
            raise RuntimeError("opencv-python not installed")
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera {index}")
        self.refresh_hz = refresh_hz
        self.frames_to_integrate = frames_to_integrate
        # lock auto-exposure / auto-white-balance so readings are comparable
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)   # 0.25 = manual on many UVC cams
        self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)

    def min_config_exposure_s(self):
        return self.frames_to_integrate / self.refresh_hz

    def set_exposure(self, seconds):
        # UVC exposure units vary by driver; many use log2(seconds). Try both and
        # let the caller verify against a test shot. This is the #1 thing to tune.
        self.cap.set(cv2.CAP_PROP_EXPOSURE, seconds)          # some drivers: raw seconds/ms
        # fallback attempt for log2-microsecond drivers is left to a calibration step

    def grab(self, n=1, drop=3):
        for _ in range(drop):            # flush stale buffered frames
            self.cap.read()
        frames = []
        for _ in range(n):
            ok, f = self.cap.read()
            if not ok:
                raise RuntimeError("frame grab failed")
            frames.append(f)
        return frames

    def capture(self, mode=MODE_CONFIG):
        if mode == MODE_CONFIG:
            self.set_exposure(max(self.min_config_exposure_s(), 1/30))  # >=1 full frame, >=33ms
            return self.grab(1)[0]
        else:  # MODE_FLICKER: short exposure burst to expose temporal variation
            self.set_exposure(1/2000)
            return self.grab(20, drop=2)

    def release(self):
        self.cap.release()


# ---------------------------------------------------------------- homography
class Grid:
    """Maps a camera image to a WxH panel grid via a 4-corner homography."""
    def __init__(self, w, h):
        self.w, self.h, self.H = w, h, None

    def calibrate_from_corners(self, src_pts):
        """src_pts: 4 (x,y) image coords of panel corners TL,TR,BR,BL."""
        dst = np.float32([[0, 0], [self.w, 0], [self.w, self.h], [0, self.h]])
        self.H = cv2.getPerspectiveTransform(np.float32(src_pts), dst)

    def calibrate_interactive(self, img):
        pts = []
        disp = img.copy()
        def on_click(ev, x, y, flags, param):
            if ev == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
                pts.append((x, y)); cv2.circle(disp, (x, y), 5, (0, 255, 255), -1)
        cv2.namedWindow("click TL,TR,BR,BL"); cv2.setMouseCallback("click TL,TR,BR,BL", on_click)
        while len(pts) < 4:
            cv2.imshow("click TL,TR,BR,BL", disp)
            if cv2.waitKey(20) == 27:
                break
        cv2.destroyAllWindows()
        if len(pts) == 4:
            self.calibrate_from_corners(pts)
        return pts

    def readout(self, img):
        """Warp to panel space and return an (H, W, 3) BGR array of per-cell means."""
        if self.H is None:
            raise RuntimeError("grid not calibrated")
        warp = cv2.warpPerspective(img, self.H, (self.w, self.h), flags=cv2.INTER_AREA)
        return warp.astype(np.float32)  # already 1 px per LED cell


# ---------------------------------------------------------------- scorers
def coverage(cells, thresh=40):
    """Fraction of cells lit (any channel above thresh)."""
    lit = (cells.max(axis=2) > thresh)
    return float(lit.mean()), lit

def lit_rows(cells, thresh=40):
    lit = (cells.max(axis=2) > thresh)
    return [y for y in range(cells.shape[0]) if lit[y].mean() > 0.5]

def color_order(cells_r, cells_g, cells_b, thresh=40):
    """Given readouts of solid-R/G/B tests, report observed channel order.
    cells_* are (H,W,3) BGR. Returns dict of which BGR channel dominated each test."""
    def dom(cells):
        m = cells.reshape(-1, 3).mean(axis=0)  # BGR means
        return ["B", "G", "R"][int(np.argmax(m))]
    return {"sent_R->saw": dom(cells_r), "sent_G->saw": dom(cells_g), "sent_B->saw": dom(cells_b)}

def flicker(frames, grid):
    """Per-cell temporal std over a short-exposure burst; higher = more flicker."""
    stack = np.stack([grid.readout(f).max(axis=2) for f in frames], axis=0)
    return float(stack.std(axis=0).mean())


# ---------------------------------------------- single-pixel walk -> pixel map
def build_pixel_map(panel, cam, grid, thresh=60):
    """Light each logical pixel, find where it appears, build logical->physical map.
    Returns physical[(px,py)] = logical index, and can export the LEDVISION CSV."""
    W, H = panel.w, panel.h
    phys_of_logical = {}
    panel.clear(); time.sleep(0.1)
    for ly in range(H):
        for lx in range(W):
            panel.pixel(lx, ly)
            cells = grid.readout(cam.capture(MODE_CONFIG)).max(axis=2)
            py, px = np.unravel_index(int(np.argmax(cells)), cells.shape)
            if cells[py, px] > thresh:
                phys_of_logical[(lx, ly)] = (int(px), int(py))
        print(f"  mapped row {ly+1}/{H}", file=sys.stderr)
    return phys_of_logical

def export_alignment_csv(phys_of_logical, W, H, path):
    """Write a LEDVISION-style alignment table: cell(phys_r,phys_c)=serial order.
    serial order of logical (lx,ly) = ly*W + lx + 1 (raster). Inverted onto physical."""
    grid = [[0] * W for _ in range(H)]
    for (lx, ly), (px, py) in phys_of_logical.items():
        if 0 <= py < H and 0 <= px < W:
            grid[py][px] = ly * W + lx + 1
    with open(path, "w", newline="") as f:
        cv = csv.writer(f)
        for r in grid:
            cv.writerow(r)
    print(f"wrote {path}")


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--iface", default="eno1")
    ap.add_argument("-W", "--width", type=int, default=64)
    ap.add_argument("-H", "--height", type=int, default=64)
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--refresh", type=float, default=240.0, help="panel full-frame refresh Hz (for exposure calc)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("expo", help="print the minimum config exposure for --refresh")
    sub.add_parser("calibrate", help="show corner markers, click 4 corners, save homography")
    sub.add_parser("coverage", help="solid white -> report lit fraction and lit rows")
    sub.add_parser("color", help="solid R/G/B -> report observed channel order")
    sub.add_parser("flicker", help="short-exposure burst -> flicker score")
    mp = sub.add_parser("map", help="single-pixel walk -> alignment CSV")
    mp.add_argument("--out", default="align_from_camera.csv")
    a = ap.parse_args()

    if a.cmd == "expo":
        cam = Camera(a.cam, a.refresh)
        print(f"min config exposure ~ {cam.min_config_exposure_s()*1000:.1f} ms "
              f"(use >= 33 ms / 1/30s for margin); refresh={a.refresh} Hz")
        return

    panel = Panel(a.iface, a.width, a.height)
    cam = Camera(a.cam, a.refresh)
    grid = Grid(a.width, a.height)

    # every vision command needs a homography first
    panel.corner_markers(); time.sleep(0.3)
    grid.calibrate_interactive(cam.capture(MODE_CONFIG))

    if a.cmd == "calibrate":
        print("homography set (H matrix):\n", grid.H)
    elif a.cmd == "coverage":
        panel.solid(255, 255, 255); time.sleep(0.2)
        cov, lit = coverage(grid.readout(cam.capture(MODE_CONFIG)))
        print(f"coverage={cov:.1%}  lit_rows={len(lit_rows(grid.readout(cam.capture(MODE_CONFIG))))}/{a.height}")
    elif a.cmd == "color":
        panel.solid(255, 0, 0); time.sleep(0.2); cr = grid.readout(cam.capture(MODE_CONFIG))
        panel.solid(0, 255, 0); time.sleep(0.2); cg = grid.readout(cam.capture(MODE_CONFIG))
        panel.solid(0, 0, 255); time.sleep(0.2); cb = grid.readout(cam.capture(MODE_CONFIG))
        print(color_order(cr, cg, cb))
    elif a.cmd == "flicker":
        panel.solid(255, 255, 255); time.sleep(0.2)
        print(f"flicker score (lower=better): {flicker(cam.capture(MODE_FLICKER), grid):.2f}")
    elif a.cmd == "map":
        m = build_pixel_map(panel, cam, grid)
        export_alignment_csv(m, a.width, a.height, a.out)

    panel.clear(); cam.release()


# TODO(issue #6/#7): wire a parameter SEARCH once make_config() exists:
#   for cfg in enumerate_configs(scan=[16,32], driver=[...], decode=[...], rgb=[...]):
#       panel.snd.send_raw_frames(make_config(cfg)); pattern; score = coverage+color+flicker
#   pick argmax; then hill-climb DCLK/blanking on the flicker score.

if __name__ == "__main__":
    main()
