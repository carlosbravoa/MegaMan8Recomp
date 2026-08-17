#!/usr/bin/env python3
"""pac_texpack.py — texture-pack coverage straight from the PAC files (ROADMAP B10).

Every background tile the game can draw is a 16×16 4bpp cell of a STDATA .PAC
tile pipeline (docs/GRAPHICS.md A3: section 4 tile definitions → page column of
section 259 + a CLUT byte into section 9). The runtime keys texture packs by
the TEXEL id (FNV-1a over the palette indices + size + depth) and the PALETTE
id (FNV-1a over the CLUT halfwords) — both computable offline. This tool writes
a texture DUMP directory (the same layout `texture_dump` produces:
`<tex>-<pal>.png`, `<tex>-<pal>.clut`, `textures.tsv`, `pairs.tsv`) for every
tile definition of the given PACs, with `draws` = how many map cells reference
the definition (so `texpack.py starter --palette common` picks the palette a
tile is really used with). Merge it with play-through dumps
(`texpack.py merge`) and build the pack as usual — the whole game's
backgrounds are covered without playing through it.

    python3 tools/pac_texpack.py OUTDUMP game-assets/disc/cdrom/STDATA/STAGE*.PAC ...
    python3 tools/pac_texpack.py OUTDUMP --all       # every STDATA .PAC with a tile pipeline

Sprites: `--sprites` adds the streamed characters of A3b (docs/GRAPHICS.md):
Mega Man (PLAYER.PAC section 1, drawn as 16×16 metasprite cells of 16-row
strips) with the in-game CLUT 0 of PLAYER section 2 as the common palette and
CLUTs 1–15 (weapon colours) as recolour variants, PLAYER section 3 (type 1),
and the Robot Masters' section-17 strips of the BOSS*.PAC files (texel ids and
names only — their CLUTs are not known yet, so no PNGs). Enemies drawn from the
section-258 pages still need play-through dumps.

`names.tsv` (tex_id, name, aliases): a human name per texel id —
`STAGE00/tile0123`, `PLAYER/strip014_cell02`, `BOSSAQU/strip003_cell00` —
for texpack.py export/import/sheet (ROADMAP B12).
"""
from __future__ import annotations

import argparse
import collections
import glob
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pac_gfx import sections, decode_pages  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("pac_texpack.py needs Pillow (pip install pillow)")

FNV_OFF = 0xcbf29ce484222325
FNV_PRM = 0x100000001B3
M64 = (1 << 64) - 1


def fnv1a(h: int, v: int) -> int:
    """runtime/src/texture_pack.c fnv1a(): the low two bytes of v, low first."""
    h ^= v & 0xFF; h = (h * FNV_PRM) & M64
    h ^= (v >> 8) & 0xFF; h = (h * FNV_PRM) & M64
    return h


def texel_id(indices, w: int, h: int, depth: int = 0) -> int:
    hh = fnv1a(FNV_OFF, depth); hh = fnv1a(hh, w); hh = fnv1a(hh, h)
    for row in indices:
        for t in row:
            hh = fnv1a(hh, t)
    return hh


def palette_id(clut) -> int:
    hp = FNV_OFF
    for c in clut:
        hp = fnv1a(hp, c)
    return hp


def rgb(c: int):
    return ((c & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31, ((c >> 10) & 31) * 255 // 31)


def tile_draw_counts(secs: dict[int, bytes]) -> collections.Counter:
    """def id -> number of block entries referencing it across the layer maps."""
    blocks = secs.get(3, b"")
    nblk = len(blocks) // 512
    per_block: dict[int, collections.Counter] = {}
    cnt: collections.Counter = collections.Counter()
    for layer in (0, 1, 2):
        m = secs.get(layer)
        if not m:
            continue
        for bid in m[:1024]:
            if bid == 0 or bid >= nblk:
                continue
            if bid not in per_block:
                c = collections.Counter()
                for i in range(256):
                    e = struct.unpack_from("<H", blocks, bid * 512 + i * 2)[0]
                    d = e & 0xFFF
                    if d:
                        c[d] += 1
                per_block[bid] = c
            cnt.update(per_block[bid])
    return cnt


EXE_LOAD = 0x800C0000
FRAME_TABLE_PTRS = 0x8013A3F4   # u32 per character type: -> u32[] {width_units << 24 | strip offset}
CELL_TABLE_PTRS = 0x8013A428    # u32 per character type: -> u8[] animation cell -> frame id
# type -> (PAC basename, sheet section); PLAYER section 2 CLUT row 0 = Mega Man's palettes
SPRITE_TYPES = {0: ("PLAYER", 1), 1: ("PLAYER", 3), 2: ("BOSSTNG", 17), 3: ("BOSSFRO", 17),
                4: ("BOSSGRE", 17), 5: ("BOSSAQU", 17), 6: ("BOSSCLO", 17), 7: ("BOSSDUO", 17)}


def exe_read(exe: bytes, addr: int, n: int) -> bytes:
    off = 0x800 + (addr - EXE_LOAD)
    return exe[off:off + n]


def strip_frames(exe: bytes, t: int, sheet_len: int):
    """[(width_units, offset)] of character type t (contiguous strips until the sheet ends)."""
    t2 = struct.unpack_from("<I", exe_read(exe, FRAME_TABLE_PTRS + 4 * t, 4))[0]
    frames, pos = [], 0
    while True:
        e = struct.unpack_from("<I", exe_read(exe, t2 + 4 * len(frames), 4))[0]
        w, off = e >> 24, e & 0xFFFFFF
        if w == 0 or w > 64 or off != pos or off + w * 128 > sheet_len:
            break
        frames.append((w, off))
        pos = off + w * 128
    return frames


def strip_cell_indices(sheet: bytes, w: int, off: int, j: int):
    """16x16 palette indices of cell j of a strip: pieces of <= 64 halfwords, row stride = piece width."""
    total = w * 4
    hw0 = 4 * j
    p_start = (hw0 // 64) * 64
    pw = min(64, total - p_start)
    base = off + (p_start // 64) * 64 * 16 * 2 if p_start else off
    # pieces are stored back to back: piece p starts at off + sum(prev piece sizes)
    base = off
    x0 = 0
    while x0 + 64 <= hw0:
        base += min(64, total - x0) * 16 * 2
        x0 += 64
    hw_in = hw0 - x0
    rows = []
    for y in range(16):
        row = []
        for hw in range(hw_in, hw_in + 4):
            o = base + (y * pw + hw) * 2
            v = sheet[o] | (sheet[o + 1] << 8)
            row += [v & 15, (v >> 4) & 15, (v >> 8) & 15, (v >> 12) & 15]
        rows.append(row)
    return rows


def process_sprites(exe_path: Path, stdata: Path, out: Path, seen: dict, tsv, pairs, names: dict):
    exe = exe_path.read_bytes()
    if exe[:8] != b"PS-X EXE":
        sys.exit(f"{exe_path}: not a PS-X EXE")
    player = sections((stdata / "PLAYER.PAC").read_bytes())
    pal = player.get(2)
    cluts = []
    if pal:
        for idx in range(16):
            cluts.append([struct.unpack_from("<H", pal, (idx * 16 + i) * 2)[0] for i in range(16)])
    for t, (pac, sec) in SPRITE_TYPES.items():
        path = stdata / f"{pac}.PAC"
        if not path.exists():
            continue
        secs = sections(path.read_bytes())
        sheet = secs.get(sec)
        if not sheet:
            continue
        frames = strip_frames(exe, t, len(sheet))
        n_new = 0
        for k, (w, off) in enumerate(frames):
            for j in range(w):
                idx = strip_cell_indices(sheet, w, off, j)
                if not any(any(r) for r in idx):
                    continue                     # empty cell: never drawn as art
                tid = texel_id(idx, 16, 16)
                nm = f"{pac}/strip{k:03d}_cell{j:02d}" if t != 1 else f"PLAYER3/strip{k:03d}_cell{j:02d}"
                names.setdefault(tid, []).append(nm)
                if t not in (0,) or not cluts:
                    continue                     # no palette known: names only
                for ci, clut in enumerate(cluts):
                    pid = palette_id(clut)
                    key = (tid, pid)
                    pairs[key] += 1000 if ci == 0 else 1     # CLUT 0 = the common (in-game) palette
                    if key in seen:
                        continue
                    seen[key] = pac
                    im = Image.new("RGBA", (16, 16))
                    px = im.load()
                    for y in range(16):
                        for x in range(16):
                            v = idx[y][x]
                            px[x, y] = (0, 0, 0, 0) if v == 0 else rgb(clut[v]) + (255,)
                    im.save(out / f"{tid:016x}-{pid:016x}.png")
                    (out / f"{tid:016x}-{pid:016x}.clut").write_bytes(b"".join(struct.pack("<H", c) for c in clut))
                    tsv.write(f"{tid:016x}\t{pid:016x}\t16\t16\t4\t320\t0\t{ci * 16}\t480\t{16 * j}\t192\t0\n")
                    n_new += 1
        print(f"{pac}.PAC type {t}: {len(frames)} strips, {sum(w for w, _ in frames)} cells" + (f", {n_new} new pairs" if n_new else " (names only)"))


def process_pac(path: Path, out: Path, seen: dict, tsv, pairs: collections.Counter, stats: dict, names: dict):
    data = path.read_bytes()
    secs = sections(data)
    if 4 not in secs or 9 not in secs or 259 not in secs:
        print(f"{path.name}: no tile pipeline (sections 4/9/259), skipped")
        return
    defs, pal = secs[4], secs[9]
    pages = decode_pages(secs[259])
    counts = tile_draw_counts(secs)
    ndef = len(defs) // 4
    new = 0
    for did in range(ndef):
        uvb, slot, cb, _fl = struct.unpack_from("<BBBB", defs, did * 4)
        u, v, slot = (uvb & 0xF) << 4, uvb & 0xF0, slot & 7
        if slot >= len(pages):
            continue
        pg = pages[slot]
        indices = [pg[v + y][u:u + 16] for y in range(16)]
        row, idx = 4 + ((cb & 0x30) >> 4), cb & 0xF
        clut = [struct.unpack_from("<H", pal, (row * 256 + idx * 16 + i) * 2)[0] for i in range(16)]
        tid, pid = texel_id(indices, 16, 16), palette_id(clut)
        key = (tid, pid)
        draws = counts.get(did, 0) or 1
        pairs[key] += draws
        nm = f"{path.stem}/tile{did:04d}"
        lst = names.setdefault(tid, [])
        if nm not in lst:
            lst.append(nm)
        if key in seen:
            continue
        seen[key] = path.name
        im = Image.new("RGBA", (16, 16))
        px = im.load()
        for y in range(16):
            for x in range(16):
                t = indices[y][x]
                px[x, y] = (0, 0, 0, 0) if t == 0 else rgb(clut[t]) + (255,)
        im.save(out / f"{tid:016x}-{pid:016x}.png")
        (out / f"{tid:016x}-{pid:016x}.clut").write_bytes(b"".join(struct.pack("<H", c) for c in clut))
        tsv.write(f"{tid:016x}\t{pid:016x}\t16\t16\t4\t{512 + 64 * slot}\t256\t{idx * 16}\t{480 + row}\t{u}\t{v}\t0\n")
        new += 1
    stats[path.name] = (ndef, new)
    print(f"{path.name}: {ndef} tile defs, {new} new (texel, palette) pairs")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("pacs", nargs="*")
    ap.add_argument("--all", action="store_true", help="every STDATA .PAC under game-assets/disc/cdrom/STDATA")
    ap.add_argument("--sprites", action="store_true", help="add the streamed characters (player + bosses) from the EXE tables")
    ap.add_argument("--exe", help="boot EXE for --sprites (default game-assets/disc/cdrom/SLUS_004.53)")
    a = ap.parse_args()
    pacs = list(a.pacs)
    if a.all:
        root = Path(__file__).resolve().parent.parent
        pacs += sorted(glob.glob(str(root / "game-assets/disc/cdrom/STDATA/*.PAC")))
    if not pacs:
        sys.exit("no PACs given (use --all)")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    seen: dict = {}
    pairs: collections.Counter = collections.Counter()
    stats: dict = {}
    names: dict = {}
    root = Path(__file__).resolve().parent.parent
    with open(out / "textures.tsv", "w") as tsv:
        tsv.write("tex_id\tpal_id\tw\th\tbpp\ttexpage_x\ttexpage_y\tclut_x\tclut_y\tu\tv\tfirst_frame\n")
        for p in pacs:
            process_pac(Path(p), out, seen, tsv, pairs, stats, names)
        if a.sprites:
            exe = Path(a.exe) if a.exe else root / "game-assets/disc/cdrom/SLUS_004.53"
            stdata = Path(pacs[0]).resolve().parent if pacs else root / "game-assets/disc/cdrom/STDATA"
            process_sprites(exe, stdata, out, seen, tsv, pairs, names)
    with open(out / "names.tsv", "w") as f:
        f.write("tex_id\tname\taliases\n")
        for tid, lst in names.items():
            f.write(f"{tid:016x}\t{lst[0]}\t{' '.join(lst[1:])}\n")
    with open(out / "pairs.tsv", "w") as f:
        f.write("tex_id\tpal_id\tdraws\n")
        for (tid, pid), n in pairs.items():
            f.write(f"{tid:016x}\t{pid:016x}\t{n}\n")
    texels = len({t for t, _ in seen})
    print(f"{out}: {len(seen)} (texel, palette) pairs, {texels} texel ids from {len(stats)} PACs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
