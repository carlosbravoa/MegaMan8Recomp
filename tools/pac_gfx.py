#!/usr/bin/env python3
"""pac_gfx.py — render Mega Man 8 STDATA .PAC pixel sections to PNG (ROADMAP A4, extract side).

Layout (measured, docs/GRAPHICS.md): a pixel section (types 256–260) is a run of
2 KB chunks; chunk k is a 64-halfword × 16-row block placed at VRAM column
k // 16 (×64 halfwords) and row 16·(k mod 16) of the section's base rectangle
(258 → VRAM (512,0), 259 → (512,256), COMNCHAR 256 → (320,0), 257 → (320,256),
260 → (384,256)). Section 9 = the stage palette block, 8 rows × 256 BGR555
entries uploaded to VRAM (0,480): 4bpp sprites/tiles address a 16-entry CLUT
at (16·i, 480+row) → 128 CLUT16s. Everything the intro stage draws is 4bpp.

    pac_gfx.py extract STAGE00.PAC OUTDIR [--clut ROW:INDEX] [--bpp 4|8]

writes, per pixel section: `sec<T>_idx.png` (indexed-colour PNG, one CLUT
applied — default row 4 index 2 = the CLUT most used by the intro stage; pass
--clut to pick), `sec<T>_gray.png` (palette index as grey, CLUT-independent),
plus `palettes.png` (all 128 CLUT16 swatches, 16 px per entry) and
`palettes.txt`. `pack` (PNG → PAC) is the next step and is not here yet.
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("pac_gfx.py needs Pillow (pip install pillow)")

PIXEL_TYPES = (256, 257, 258, 259, 260)


def sections(data: bytes) -> dict[int, bytes]:
    n = struct.unpack_from("<I", data, 0)[0]
    out, off = {}, 0x800
    for i in range(n):
        t, sz = struct.unpack_from("<II", data, 8 + i * 8)
        out.setdefault(t, data[off:off + sz])
        off = (off + sz + 0x7FF) & ~0x7FF
    return out


def bgr555_rgb(v: int):
    return ((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31)


def clut16(pal: bytes, row: int, index: int):
    base = (row * 256 + index * 16) * 2
    return [bgr555_rgb(struct.unpack_from("<H", pal, base + i * 2)[0]) for i in range(16)]


def render_section(sec: bytes, bpp: int):
    """Indexed image: 2 KB chunks -> 64-halfword x 16-row blocks, 16 rows per column."""
    chunks = len(sec) // 0x800
    ncols = math.ceil(chunks / 16)
    ppw = 4 if bpp == 4 else 2                       # pixels per halfword
    img = Image.new("P", (ncols * 64 * ppw, 256))
    px = img.load()
    for k in range(chunks):
        col, row0 = k // 16, (k % 16) * 16
        chunk = sec[k * 0x800:(k + 1) * 0x800]
        for r in range(16):
            for hw in range(64):
                v = chunk[(r * 64 + hw) * 2] | (chunk[(r * 64 + hw) * 2 + 1] << 8)
                x0, y = col * 64 * ppw + hw * ppw, row0 + r
                if bpp == 4:
                    px[x0, y] = v & 15; px[x0 + 1, y] = (v >> 4) & 15
                    px[x0 + 2, y] = (v >> 8) & 15; px[x0 + 3, y] = (v >> 12) & 15
                else:
                    px[x0, y] = v & 255; px[x0 + 1, y] = v >> 8
    return img


def cmd_extract(a) -> int:
    data = Path(a.pac).read_bytes()
    secs = sections(data)
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    row, idx = (int(v) for v in a.clut.split(":"))
    pal = secs.get(9)
    if pal is None:
        print("no palette section (type 9) — indexed PNGs get a grey ramp", file=sys.stderr)
        colors = [(i * 17, i * 17, i * 17) for i in range(16)]
    else:
        colors = clut16(pal, row, idx)
        # swatch sheet: 8 rows x 16 CLUTs x 16 entries
        sw = Image.new("RGB", (256 * 8, 8 * 16))
        lines = []
        for r in range(8):
            for c in range(16):
                cl = clut16(pal, r, c)
                for i, rgb in enumerate(cl):
                    for yy in range(16):
                        for xx in range(8):
                            sw.putpixel((c * 128 + i * 8 + xx, r * 16 + yy), rgb)
                lines.append(f"row {r} clut {c:2d} (VRAM x={c*16:3d} y={480+r}): " + " ".join(f"{v:02x}{g:02x}{b:02x}" for v, g, b in cl))
        sw.save(out / "palettes.png")
        (out / "palettes.txt").write_text("\n".join(lines) + "\n")
    flat = [v for rgb in colors for v in rgb]
    for t in PIXEL_TYPES:
        if t not in secs:
            continue
        img = render_section(secs[t], a.bpp)
        n_idx = 16 if a.bpp == 4 else 256
        img.putpalette(flat + [0] * (768 - len(flat)))
        img.save(out / f"sec{t}_idx.png")
        gray = img.copy()
        gray.putpalette([c for i in range(n_idx) for c in (i * (255 // (n_idx - 1)),) * 3] + [0] * (768 - n_idx * 3))
        gray.save(out / f"sec{t}_gray.png")
        print(f"sec{t}: {len(secs[t])} bytes -> {img.size[0]}x{img.size[1]} px @{a.bpp}bpp")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("pac"); e.add_argument("outdir")
    e.add_argument("--clut", default="4:2", help="palette ROW:INDEX (row 0-7, index 0-15)")
    e.add_argument("--bpp", type=int, default=4, choices=(4, 8))
    e.set_defaults(fn=cmd_extract)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
