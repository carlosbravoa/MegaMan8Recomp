#!/usr/bin/env python3
"""video_filter_check.py — in-game parity check of the OpenGL video-filter
shaders against the CPU reference (psxrecomp/runtime/src/video_filter.c).

Needs a debug-tools build running on the OpenGL renderer (port 4545 for MM8:
`bash tools/run_mm8.sh --debug --no-launcher`). For every upscaler it:

  1. selects the filter over the debug server ("video_filter"),
  2. resizes the window to exactly N x the native display (so the final
     sharp-bilinear fit is a 1:1 identity — "window_size"),
  3. queues "present_capture" — the runtime writes the presented drawable
     (post-filter, pre-OSD) plus the exact source rect the shader consumed
     (`.src.png`) and the CPU reference of that same input (`.ref.png`),
  4. diffs drawable vs reference: sizes must match, and every pixel must be
     within --tolerance (default 1 LSB, the unorm-rounding slack) — anything
     else is a shader/CPU divergence and fails the run.

The final-pass filters (sharp / scanlines / crt) have no integer-exact CPU
twin (their software fallback is an approximation), so they are only
captured for eyeballing. Everything lands in --out (default
$CLAUDE_JOB_DIR/tmp or ./vf_check). Exit status 1 on any parity failure.

    python3 tools/video_filter_check.py                # all filters
    python3 tools/video_filter_check.py xbr2x 2xsai    # subset
"""
import argparse
import json
import os
import socket
import sys
import time

try:
    from PIL import Image, ImageChops
except ImportError:  # pragma: no cover
    sys.exit("needs Pillow (pip install pillow)")

UPSCALERS = ["scale2x", "scale3x", "2xsai", "super2xsai", "supereagle",
             "xbr2x", "xbr3x", "xbr4x"]
FINAL = ["sharp", "scanlines", "crt"]


class Dbg:
    def __init__(self, port, host="127.0.0.1"):
        self.addr = (host, port)

    def cmd(self, cmd, **kw):
        req = {"id": 1, "cmd": cmd}
        req.update(kw)
        try:
            s = socket.create_connection(self.addr, timeout=30)
        except OSError as e:
            sys.exit(f"cannot reach the debug server on {self.addr} ({e})")
        with s:
            s.sendall((json.dumps(req) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode(errors="replace").splitlines()[0])


def wait_capture(d, path, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = d.cmd("present_capture")
        if r.get("state") == "written" and os.path.exists(path):
            return True
        if r.get("state") == "failed":
            return False
        time.sleep(0.05)
    return False


def native_size(d):
    """Native display size via a source capture at the current filter."""
    r = d.cmd("screenshot_file", path=os.devnull)
    if r.get("ok") and r.get("width") and r.get("height"):
        return int(r["width"]), int(r["height"])
    return 320, 240


def compare(a_path, b_path, tolerance):
    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    if a.size != b.size:
        return False, f"size mismatch drawable {a.size} vs reference {b.size}"
    diff = ImageChops.difference(a, b)
    bbox = diff.getbbox()
    if not bbox:
        return True, "identical"
    # Histogram of the max channel difference per pixel.
    px = diff.load()
    w, h = diff.size
    over = 0
    worst = 0
    for y in range(h):
        for x in range(w):
            m = max(px[x, y])
            if m > worst:
                worst = m
            if m > tolerance:
                over += 1
    total = w * h
    msg = f"max diff {worst}, {over}/{total} px over tolerance {tolerance}"
    return over == 0, msg


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("filters", nargs="*", help="subset of filters (default: all)")
    ap.add_argument("--port", type=int, default=4545)
    ap.add_argument("--out", default=None)
    ap.add_argument("--tolerance", type=int, default=1)
    ap.add_argument("--settle", type=float, default=0.6,
                    help="seconds to let the window resize/present settle")
    args = ap.parse_args()

    out = args.out or os.path.join(os.environ.get("CLAUDE_JOB_DIR", "."), "tmp", "vf_check") \
        if os.environ.get("CLAUDE_JOB_DIR") else (args.out or "vf_check")
    os.makedirs(out, exist_ok=True)
    d = Dbg(args.port)
    r = d.cmd("video_filter")
    if not r.get("ok"):
        sys.exit(f"video_filter query failed: {r}")
    names = r["names"]
    original = r["filter"]
    wanted = args.filters or (UPSCALERS + FINAL)
    for f in wanted:
        if f not in names:
            sys.exit(f"unknown filter {f!r}; runtime knows {names}")

    win = d.cmd("window_size")
    orig_win = tuple(win.get("window", (1280, 960)))
    nw, nh = native_size(d)
    print(f"native display {nw}x{nh}; window {orig_win}; drawable {win.get('drawable')}")

    failures = []
    for f in wanted:
        r = d.cmd("video_filter", name=f)
        if not r.get("ok"):
            failures.append((f, f"select failed: {r}"))
            continue
        n = int(r["scale"])
        if f in UPSCALERS:
            want = (nw * n, nh * n)
        else:
            want = (nw * 3, nh * 3)   # any size; 3x keeps captures comparable
        d.cmd("window_size", w=want[0], h=want[1])
        time.sleep(args.settle)
        ws = d.cmd("window_size")
        drawable = tuple(ws.get("drawable", (0, 0)))
        path = os.path.abspath(os.path.join(out, f"{f}.png"))
        for stale in (path, path + ".src.png", path + ".ref.png"):
            if os.path.exists(stale):
                os.remove(stale)
        d.cmd("present_capture", path=path)
        if not wait_capture(d, path):
            failures.append((f, "capture did not complete (is a frame being presented?)"))
            continue
        gl = d.cmd("video_filter")["gl"]
        if gl["broken_mask"] & (1 << int(r["kind"])):
            failures.append((f, "GL shader failed to build (broken_mask)"))
            continue
        if f in UPSCALERS:
            ref = path + ".ref.png"
            if drawable != want:
                failures.append((f, f"drawable {drawable} != wanted {want}; cannot check 1:1 parity"))
                continue
            if not os.path.exists(ref):
                failures.append((f, "runtime wrote no .ref.png (was the filter path taken?)"))
                continue
            ok, msg = compare(path, ref, args.tolerance)
            print(f"{f:12s} N={n} drawable {drawable}: {'OK  ' if ok else 'FAIL'} {msg}")
            if not ok:
                failures.append((f, msg))
        else:
            print(f"{f:12s} captured {path} (visual only)")

    # Restore.
    d.cmd("video_filter", name=original)
    d.cmd("window_size", w=orig_win[0], h=orig_win[1])
    if failures:
        print("\nFAILURES:")
        for f, m in failures:
            print(f"  {f}: {m}")
        sys.exit(1)
    print("\nall checked filters within tolerance")


if __name__ == "__main__":
    main()
