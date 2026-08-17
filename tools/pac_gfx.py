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
    pac_gfx.py tiles   STAGE00.PAC OUTDIR            # tile definitions, each with its own CLUT
    pac_gfx.py map     STAGE00.PAC OUTDIR            # the stage's layer maps as full PNGs

`extract` writes, per pixel section: `sec<T>_idx.png` (indexed-colour PNG,
one CLUT applied — default row 4 index 2; pass --clut to pick),
`sec<T>_gray.png` (palette index as grey, CLUT-independent), plus
`palettes.png` (all 128 CLUT16 swatches) and `palettes.txt`.

`tiles` renders section 4 — the tile definitions the background renderer
uses (`docs/GRAPHICS.md`, A3): 4 bytes per tile `{v<<4|u, page slot, clut
byte, flags}`; each 16×16 tile is cut from page column *slot* of section 259
and coloured with CLUT `0x7900 + (clut & 15) + ((clut & 0x30) << 2)` (palette
rows 4–7 of section 9) → `tiles.png` (32 per row) + `tiles.txt`.

`map` renders sections 0/1/2 (three layers of 32×32 block ids) through section
3 (512-byte blocks = 16×16 u16 entries: def id | 0x1000 OT group | 0x2000
semi-transparent) → `map_layer<N>.png` (RGBA, transparent where empty),
cropped to the used blocks; `map.txt` lists the block grid.
`pack` (PNG → PAC) is the next step and is not here yet.
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


# ── A3: tile definitions + layer maps ──────────────────────────────────────

def decode_pages(sec: bytes, bpp: int = 4):
    """Page columns of a pixel section as lists of index rows (256 rows each)."""
    chunks = len(sec) // 0x800
    ncols = math.ceil(chunks / 16)
    ppw = 4 if bpp == 4 else 2
    pages = [[[0] * (64 * ppw) for _ in range(256)] for _ in range(ncols)]
    for k in range(chunks):
        col, row0 = k // 16, (k % 16) * 16
        chunk = sec[k * 0x800:(k + 1) * 0x800]
        pg = pages[col]
        for r in range(16):
            row = pg[row0 + r]
            for hw in range(64):
                v = chunk[(r * 64 + hw) * 2] | (chunk[(r * 64 + hw) * 2 + 1] << 8)
                x = hw * ppw
                if bpp == 4:
                    row[x] = v & 15; row[x + 1] = (v >> 4) & 15; row[x + 2] = (v >> 8) & 15; row[x + 3] = (v >> 12) & 15
                else:
                    row[x] = v & 255; row[x + 1] = v >> 8
    return pages


def clut_from_byte(pal: bytes, cb: int, base_row: int = 4):
    """CLUT word = 0x7900 + (cb & 15) + ((cb & 0x30) << 2): row base_row + (cb>>4 & 3), index cb & 15."""
    row = base_row + ((cb & 0x30) >> 4)
    idx = cb & 0xF
    return [bgr555_rgb(struct.unpack_from("<H", pal, (row * 256 + idx * 16 + i) * 2)[0]) +
            ((0,) if struct.unpack_from("<H", pal, (row * 256 + idx * 16 + i) * 2)[0] == 0 else (255,))
            for i in range(16)]


class TileSet:
    def __init__(self, secs: dict[int, bytes]):
        self.defs = secs.get(4, b"")
        self.pal = secs.get(9)
        self.pages = decode_pages(secs[259]) if 259 in secs else []
        self.cache: dict[int, Image.Image] = {}
        self.ndef = len(self.defs) // 4

    def tile(self, defid: int) -> Image.Image:
        if defid in self.cache:
            return self.cache[defid]
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        if defid < self.ndef and self.pal is not None:
            uvb, slot, cb, _fl = struct.unpack_from("<BBBB", self.defs, defid * 4)
            u, v, slot = (uvb & 0xF) << 4, uvb & 0xF0, slot & 7
            if slot < len(self.pages):
                cl = clut_from_byte(self.pal, cb)
                pg = self.pages[slot]
                px = img.load()
                for yy in range(16):
                    row = pg[v + yy]
                    for xx in range(16):
                        px[xx, yy] = cl[row[u + xx]]
        self.cache[defid] = img
        return img


def cmd_tiles(a) -> int:
    secs = sections(Path(a.pac).read_bytes())
    ts = TileSet(secs)
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    per_row = 32
    rows = math.ceil(ts.ndef / per_row)
    sheet = Image.new("RGBA", (per_row * 16, max(1, rows) * 16), (0, 0, 0, 0))
    lines = []
    for i in range(ts.ndef):
        sheet.alpha_composite(ts.tile(i), ((i % per_row) * 16, (i // per_row) * 16))
        uvb, slot, cb, fl = struct.unpack_from("<BBBB", ts.defs, i * 4)
        lines.append(f"def {i:4d}: page slot {slot & 7} u {(uvb & 15) << 4:3d} v {uvb & 0xF0:3d} clut row {4 + ((cb & 0x30) >> 4)} idx {cb & 15:2d} flags {fl:#04x} slotbyte {slot:#04x}")
    sheet.save(out / "tiles.png")
    (out / "tiles.txt").write_text("\n".join(lines) + "\n")
    print(f"tiles: {ts.ndef} definitions -> {out / 'tiles.png'} ({sheet.size[0]}x{sheet.size[1]})")
    return 0


def cmd_map(a) -> int:
    secs = sections(Path(a.pac).read_bytes())
    ts = TileSet(secs)
    blocks = secs.get(3, b"")
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    lines = []
    for layer in (0, 1, 2):
        m = secs.get(layer)
        if m is None or len(m) < 1024:
            continue
        used = [(i % 32, i // 32) for i in range(1024) if m[i]]
        if not used:
            lines.append(f"layer {layer}: empty"); continue
        bx0, bx1 = min(c for c, _ in used), max(c for c, _ in used)
        by0, by1 = min(r for _, r in used), max(r for _, r in used)
        img = Image.new("RGBA", ((bx1 - bx0 + 1) * 256, (by1 - by0 + 1) * 256), (0, 0, 0, 0))
        for c, r in used:
            b = m[r * 32 + c]
            if (b + 1) * 512 > len(blocks):
                continue
            for ti in range(256):
                e = struct.unpack_from("<H", blocks, b * 512 + ti * 2)[0]
                if e == 0:
                    continue
                img.alpha_composite(ts.tile(e & 0xFFF), ((c - bx0) * 256 + (ti & 15) * 16, (r - by0) * 256 + (ti >> 4) * 16))
        img.save(out / f"map_layer{layer}.png")
        lines.append(f"layer {layer}: blocks x{bx0}..{bx1} y{by0}..{by1} ({len(used)} used) -> map_layer{layer}.png {img.size[0]}x{img.size[1]}")
        for r in range(by0, by1 + 1):
            lines.append("  " + " ".join(f"{m[r * 32 + c]:3d}" for c in range(bx0, bx1 + 1)))
        print(lines[-(by1 - by0 + 2)])
    (out / "map.txt").write_text("\n".join(lines) + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("pac"); e.add_argument("outdir")
    e.add_argument("--clut", default="4:2", help="palette ROW:INDEX (row 0-7, index 0-15)")
    e.add_argument("--bpp", type=int, default=4, choices=(4, 8))
    e.set_defaults(fn=cmd_extract)
    t = sub.add_parser("tiles"); t.add_argument("pac"); t.add_argument("outdir"); t.set_defaults(fn=cmd_tiles)
    m = sub.add_parser("map"); m.add_argument("pac"); m.add_argument("outdir"); m.set_defaults(fn=cmd_map)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
