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
    pac_gfx.py pack    OUTDIR NEW.PAC [--pac ORIGINAL.PAC] [--from-tiles]
    pac_gfx.py sprites PLAYER.PAC OUTDIR [--exe disc/SLUS_004.53] [--stage STAGE00.PAC] [--clut N]

`sprites` renders a streamed character sheet (Mega Man): `frames.png` = the
131 per-frame strips (16 px tall, from the EXE frame table at *(0x8013A3F4+4t))
in the chosen CLUT of the sheet's palette section, and — given a stage PAC —
`poses.png` = every animation cell assembled from its metasprite part list
(section 5: {u16 cell, s8 dx, s8 dy}), i.e. the sprites as drawn.

`pack` rebuilds the PAC from an extract directory: pixel sections from
`sec<T>_idx.png` (the palette *indices* of the PNG are the pixels — edit them
in an indexed-colour editor, or use `--from-tiles` to take each tile
definition's 16×16 pixels from an edited `tiles.png` and quantise them against
that tile's own CLUT), the palette block from `palette_block.png` (one pixel
per BGR555 entry; the STP bit of every entry is kept from the original),
every other section verbatim from the original PAC (path recorded in
`gfx.toml`, or --pac). Untouched art round-trips byte-identical.
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
    ptype = a.palette_type if a.palette_type is not None else 9
    pal = secs.get(ptype)
    if pal is not None and len(pal) % 512:
        sys.exit(f"section {ptype} is {len(pal)} bytes — not a palette block (multiple of 512)")
    if pal is None:
        print("no palette section (type 9) — indexed PNGs get a grey ramp", file=sys.stderr)
        colors = [(i * 17, i * 17, i * 17) for i in range(16)]
    else:
        prow = len(pal) // 512
        if row >= prow:
            print(f"palette has {prow} row(s); using row 0 for the preview CLUT", file=sys.stderr)
            row = 0
        colors = clut16(pal, row, idx)
        # swatch sheet: rows x 16 CLUTs x 16 entries
        sw = Image.new("RGB", (256 * 8, prow * 16))
        lines = []
        for r in range(prow):
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
    manifest = [f"# written by tools/pac_gfx.py extract — input for `pac_gfx.py pack`",
                f'source = "{Path(a.pac).resolve()}"', f'source_name = "{Path(a.pac).name}"',
                f"bpp = {a.bpp}", ""]
    if pal is not None:
        # editable palette block: one pixel per entry (256 wide, one row per 256-entry row)
        rows = len(pal) // 512
        pb = Image.new("RGB", (256, rows))
        for r in range(rows):
            for i in range(256):
                pb.putpixel((i, r), bgr555_rgb(struct.unpack_from("<H", pal, (r * 256 + i) * 2)[0]))
        pb.save(out / "palette_block.png")
        manifest += ["[palette]", f"type = {ptype}", 'file = "palette_block.png"', f"rows = {rows}", ""]
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
        manifest += ["[[pixels]]", f"type = {t}", f'file = "sec{t}_idx.png"', f"size = {len(secs[t])}", ""]
        print(f"sec{t}: {len(secs[t])} bytes -> {img.size[0]}x{img.size[1]} px @{a.bpp}bpp")
    (out / "gfx.toml").write_text("\n".join(manifest) + "\n")
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


# ── A3b: streamed character sprites (player) ───────────────────────────────

EXE_LOAD = 0x800C0000
FRAME_TABLE_PTRS = 0x8013A3F4   # u32 per character type: -> u32[] {width_units << 24 | strip offset}
CELL_TABLE_PTRS = 0x8013A428    # u32 per character type: -> u8[] animation cell -> frame id


def exe_read(exe: bytes, addr: int, n: int) -> bytes:
    off = 0x800 + (addr - EXE_LOAD)
    return exe[off:off + n]


def cmd_sprites(a) -> int:
    """Per-frame strips + assembled poses of a streamed character (default: Mega Man)."""
    exe = Path(a.exe).read_bytes()
    if exe[:8] != b"PS-X EXE":
        sys.exit(f"{a.exe}: not a PS-X EXE")
    sheet_secs = sections(Path(a.pac).read_bytes())
    strips_data = sheet_secs.get(a.sheet_section)
    if strips_data is None:
        sys.exit(f"{a.pac}: no section {a.sheet_section}")
    pal_secs = sections(Path(a.palette_pac).read_bytes()) if a.palette_pac else sheet_secs
    palsec = pal_secs.get(a.palette_type)
    if palsec is None:
        print(f"no palette section {a.palette_type} — using a grey ramp (pass --palette-pac/--palette-type/--clut)", file=sys.stderr)
        cl = [(i * 17, i * 17, i * 17) for i in range(16)]
    else:
        cl = clut16(palsec, a.clut // 16, a.clut % 16)
    rgba = [c + ((0,) if i == 0 else (255,)) for i, c in enumerate(cl)]
    t = a.type
    t2 = struct.unpack_from("<I", exe_read(exe, FRAME_TABLE_PTRS + 4 * t, 4))[0]
    t1 = struct.unpack_from("<I", exe_read(exe, CELL_TABLE_PTRS + 4 * t, 4))[0]
    # frame table: contiguous strips until the sheet is exhausted
    frames = []
    pos = 0
    while True:
        e = struct.unpack_from("<I", exe_read(exe, t2 + 4 * len(frames), 4))[0]
        w, off = e >> 24, e & 0xFFFFFF
        if w == 0 or w > 64 or off != pos or off + w * 128 > len(strips_data):
            break
        frames.append((w, off))
        pos = off + w * 128
    if not frames:
        sys.exit("no frames decoded — wrong --type / --exe?")
    # cell table: bytes until they stop being valid frame ids or the next table begins
    tables = sorted({struct.unpack_from("<I", exe_read(exe, base + 4 * k, 4))[0]
                     for base in (FRAME_TABLE_PTRS, CELL_TABLE_PTRS) for k in range(8)})
    limit = min([x for x in tables if x > t1] + [t1 + 1024]) - t1
    cells = []
    for i in range(limit):
        b = exe_read(exe, t1 + i, 1)
        if not b or b[0] >= len(frames):
            break
        cells.append(b[0])
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)

    def strip_img(k):
        # a frame = w*4 halfwords x 16 rows, stored as consecutive pieces of at most 64
        # halfwords (the LoadImage queue splits wide frames: 2 KB per full piece)
        w, off = frames[k]
        total = w * 4
        img = Image.new("RGBA", (w * 16, 16), (0, 0, 0, 0)); px = img.load()
        x0 = 0
        while x0 < total:
            pw = min(64, total - x0)
            for y in range(16):
                for hw in range(pw):
                    o = off + (y * pw + hw) * 2
                    v = strips_data[o] | (strips_data[o + 1] << 8)
                    for q in range(4):
                        px[(x0 + hw) * 4 + q, y] = rgba[(v >> (4 * q)) & 15]
            off += pw * 16 * 2
            x0 += pw
        return img

    maxw = max(w for w, _ in frames) * 16
    sheet = Image.new("RGBA", (maxw, len(frames) * 16), (0, 0, 0, 0))
    lines = []
    for k in range(len(frames)):
        sheet.alpha_composite(strip_img(k), (0, k * 16))
        lines.append(f"frame {k:3d}: offset {frames[k][1]:#7x} width {frames[k][0] * 16:3d} px ({frames[k][0] * 4} halfwords)")
    sheet.save(out / "frames.png")
    (out / "frames.txt").write_text("\n".join(lines) + "\n")
    print(f"frames: {len(frames)} strips -> {out / 'frames.png'} ({sheet.size[0]}x{sheet.size[1]}); {len(cells)} animation cells")

    # assembled poses need the metasprite part lists (STAGE section 5)
    if a.stage:
        st = sections(Path(a.stage).read_bytes())
        s5 = st.get(5)
        if s5 is None:
            sys.exit(f"{a.stage}: no section 5")
        # section 5 = consecutive metasprite groups: {u16 count, u16 offset}[N] header
        # (offsets group-relative, N = first offset / 4) then the part lists; group 0 =
        # Mega Man, the others = the stage's objects/enemies/boss (--group)
        gbase, gi = 0, 0
        while gi < a.group:
            n = struct.unpack_from("<H", s5, gbase + 2)[0] // 4
            hdr = [struct.unpack_from("<HH", s5, gbase + 4 * i) for i in range(n)]
            gbase = (gbase + max(o + c * 4 for c, o in hdr) + 3) & ~3
            gi += 1
        nentries = struct.unpack_from("<H", s5, gbase + 2)[0] // 4
        canvas_w, canvas_h, ox, oy = 128, 96, 64, 56
        per_row = 12
        nposes = min(len(cells), nentries)
        poses = Image.new("RGBA", (per_row * canvas_w, math.ceil(nposes / per_row) * canvas_h), (0, 0, 0, 0))
        plines = []
        for c in range(nposes):
            count, off = struct.unpack_from("<HH", s5, gbase + 4 * c)
            parts = [struct.unpack_from("<Hbb", s5, gbase + off + 4 * k) for k in range(count)]
            fr = strip_img(cells[c])
            pose = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            for raw, dx, dy in parts:
                idx = raw & 0x3FF
                if idx * 16 + 16 > fr.size[0]:
                    continue
                cell = fr.crop((idx * 16, 0, idx * 16 + 16, 16))
                if raw & 0x8000: cell = cell.transpose(Image.FLIP_LEFT_RIGHT)
                if raw & 0x4000: cell = cell.transpose(Image.FLIP_TOP_BOTTOM)
                pose.alpha_composite(cell, (ox + dx, oy + dy))
            poses.alpha_composite(pose, ((c % per_row) * canvas_w, (c // per_row) * canvas_h))
            plines.append(f"cell {c:3d}: frame {cells[c]:3d} parts {[(hex(r), dx, dy) for r, dx, dy in parts]}")
        poses.save(out / "poses.png")
        (out / "poses.txt").write_text("\n".join(plines) + "\n")
        print(f"poses: {nposes} animation cells -> {out / 'poses.png'} (origin at +{ox},+{oy} in each {canvas_w}x{canvas_h} cell)")
    return 0


# ── A5: pack ───────────────────────────────────────────────────────────────

def encode_section(indices, nbytes: int, bpp: int = 4) -> bytes:
    """Inverse of render_section: indices[y][x] over (ncols*64*ppw) x 256 -> chunk stream of nbytes."""
    ppw = 4 if bpp == 4 else 2
    chunks = nbytes // 0x800
    out = bytearray(chunks * 0x800)
    for k in range(chunks):
        col, row0 = k // 16, (k % 16) * 16
        base = k * 0x800
        for r in range(16):
            row = indices[row0 + r]
            for hw in range(64):
                x = col * 64 * ppw + hw * ppw
                if bpp == 4:
                    v = row[x] | (row[x + 1] << 4) | (row[x + 2] << 8) | (row[x + 3] << 12)
                else:
                    v = row[x] | (row[x + 1] << 8)
                o = base + (r * 64 + hw) * 2
                out[o] = v & 0xFF; out[o + 1] = v >> 8
    return bytes(out)


def rgb_bgr555(rgb) -> int:
    r, g, b = rgb[:3]
    return ((r * 31 + 127) // 255) | (((g * 31 + 127) // 255) << 5) | (((b * 31 + 127) // 255) << 10)


def cmd_pack(a) -> int:
    import tomllib
    sys.path.insert(0, str(Path(__file__).parent))
    from pac_tool import parse as pac_parse, build as pac_build   # container codec
    d = Path(a.dir)
    with open(d / "gfx.toml", "rb") as f:
        m = tomllib.load(f)
    src = Path(a.pac) if a.pac else Path(m["source"])
    if not src.exists():
        sys.exit(f"original PAC not found: {src} (pass --pac)")
    data = src.read_bytes()
    _count, _total, plist, _end = pac_parse(data)
    secs = {t: data[off:off + sz] for t, off, sz in plist}
    bpp = int(m.get("bpp", 4))
    ppw = 4 if bpp == 4 else 2
    warnings = 0

    # palette
    pal = None
    if "palette" in m and (d / m["palette"]["file"]).exists():
        pt = int(m["palette"]["type"])
        orig = secs.get(pt)
        pb = Image.open(d / m["palette"]["file"]).convert("RGB")
        rows = pb.size[1]
        new = bytearray(rows * 512)
        for r in range(rows):
            for i in range(256):
                v = rgb_bgr555(pb.getpixel((i, r)))
                if orig is not None and (r * 256 + i) * 2 + 1 < len(orig):
                    ov = struct.unpack_from("<H", orig, (r * 256 + i) * 2)[0]
                    if bgr555_rgb(ov) == pb.getpixel((i, r)):
                        v = ov                       # untouched entry: keep exact bits (STP)
                    else:
                        v |= ov & 0x8000             # edited: keep its STP bit
                struct.pack_into("<H", new, (r * 256 + i) * 2, v)
        secs[pt] = bytes(new)
        pal = bytes(new)

    # pixel sections from the indexed PNGs
    pixels = {}
    for px in m.get("pixels", []):
        t = int(px["type"])
        img = Image.open(d / px["file"])
        if img.mode != "P":
            sys.exit(f"{px['file']}: must stay an indexed-colour (mode P) PNG — the indices are the pixels")
        w, h = img.size
        idx = [[img.getpixel((x, y)) for x in range(w)] for y in range(h)]
        pixels[t] = (idx, int(px["size"]))

    # optional: overlay tile edits from tiles.png
    if a.from_tiles:
        tiles_png = d / "tiles.png"
        if not tiles_png.exists():
            sys.exit("--from-tiles: tiles.png not found in the extract dir (run `pac_gfx.py tiles` first)")
        defs = secs.get(4, b"")
        pal_src = pal if pal is not None else secs.get(9)
        if 259 not in pixels or pal_src is None:
            sys.exit("--from-tiles needs section 259 and a palette section")
        sheet = Image.open(tiles_png).convert("RGBA")
        per_row = 32
        idx259, _ = pixels[259]
        written = {}
        ndef = len(defs) // 4
        nearest_used = 0
        for i in range(ndef):
            uvb, slot, cb, _fl = struct.unpack_from("<BBBB", defs, i * 4)
            u, v, slot = (uvb & 0xF) << 4, uvb & 0xF0, slot & 7
            cl = clut_from_byte(pal_src, cb)
            lut = {c[:3]: k for k, c in reversed(list(enumerate(cl)))}
            sx, sy = (i % per_row) * 16, (i // per_row) * 16
            if sx + 16 > sheet.size[0] or sy + 16 > sheet.size[1]:
                continue
            for yy in range(16):
                for xx in range(16):
                    r, g, b, al = sheet.getpixel((sx + xx, sy + yy))
                    if al == 0:
                        k = 0
                    elif (r, g, b) in lut:
                        k = lut[(r, g, b)]
                    else:
                        k = min(range(16), key=lambda q: (cl[q][0] - r) ** 2 + (cl[q][1] - g) ** 2 + (cl[q][2] - b) ** 2)
                        nearest_used += 1
                    X, Y = slot * 64 * ppw + u + xx, v + yy
                    if Y < len(idx259) and X < len(idx259[0]):
                        key = (X, Y)
                        if key in written and written[key] != k:
                            warnings += 1
                            if warnings <= 5:
                                print(f"warning: tile def {i} disagrees with an earlier def on shared pixel {key} (page cell reused with another palette); last one wins", file=sys.stderr)
                        written[key] = k
                        idx259[Y][X] = k
        if nearest_used:
            print(f"note: {nearest_used} pixels of tiles.png were not exact CLUT colours and were quantised to the nearest entry", file=sys.stderr)

    for t, (idx, size) in pixels.items():
        secs[t] = encode_section(idx, size, bpp)

    rebuilt = pac_build([(t, secs[t]) for t, _off, _sz in plist])
    Path(a.out).write_bytes(rebuilt)
    same = rebuilt == data
    print(f"packed {a.out}: {len(rebuilt)} bytes ({'identical to the original' if same else 'modified'})"
          + (f", {warnings} shared-cell conflicts" if warnings else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("pac"); e.add_argument("outdir")
    e.add_argument("--clut", default="4:2", help="palette ROW:INDEX (row 0-7, index 0-15)")
    e.add_argument("--bpp", type=int, default=4, choices=(4, 8))
    e.add_argument("--palette-type", type=int, default=None,
                   help="section type holding the palette block (default 9; PLAYER.PAC keeps its 16 CLUTs in type 2)")
    e.set_defaults(fn=cmd_extract)
    t = sub.add_parser("tiles"); t.add_argument("pac"); t.add_argument("outdir"); t.set_defaults(fn=cmd_tiles)
    m = sub.add_parser("map"); m.add_argument("pac"); m.add_argument("outdir"); m.set_defaults(fn=cmd_map)
    sp = sub.add_parser("sprites", help="streamed character sheet: per-frame strips + assembled poses")
    sp.add_argument("pac", help="sheet PAC (STDATA/PLAYER.PAC)"); sp.add_argument("outdir")
    sp.add_argument("--exe", default="disc/SLUS_004.53", help="boot EXE holding the frame/cell tables")
    sp.add_argument("--stage", help="a STDATA stage PAC whose section 5 holds the metasprite part lists (poses.png)")
    sp.add_argument("--type", type=int, default=0, help="character type (actor+0x49); 0 = Mega Man")
    sp.add_argument("--sheet-section", type=int, default=1); sp.add_argument("--palette-type", type=int, default=2)
    sp.add_argument("--clut", type=int, default=0, help="CLUT index inside the palette section (row*16+i; Mega Man: 0 = normal, 1-15 weapons)")
    sp.add_argument("--palette-pac", help="take the palette section from this PAC instead (bosses: the stage PAC)")
    sp.add_argument("--group", type=int, default=0, help="metasprite group inside section 5 (0 = Mega Man)")
    sp.set_defaults(fn=cmd_sprites)
    k = sub.add_parser("pack"); k.add_argument("dir"); k.add_argument("out")
    k.add_argument("--pac", help="original PAC (default: the one recorded in gfx.toml)")
    k.add_argument("--from-tiles", action="store_true", help="take tile pixels from an edited tiles.png")
    k.set_defaults(fn=cmd_pack)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
