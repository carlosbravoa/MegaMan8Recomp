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

Sprites (player / enemies / bosses) are drawn as metasprite cells, not tiles;
those still come from play-through dumps (or from A3b's tables, B12).
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


def process_pac(path: Path, out: Path, seen: dict, tsv, pairs: collections.Counter, stats: dict):
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
    with open(out / "textures.tsv", "w") as tsv:
        tsv.write("tex_id\tpal_id\tw\th\tbpp\ttexpage_x\ttexpage_y\tclut_x\tclut_y\tu\tv\tfirst_frame\n")
        for p in pacs:
            process_pac(Path(p), out, seen, tsv, pairs, stats)
    with open(out / "pairs.tsv", "w") as f:
        f.write("tex_id\tpal_id\tdraws\n")
        for (tid, pid), n in pairs.items():
            f.write(f"{tid:016x}\t{pid:016x}\t{n}\n")
    texels = len({t for t, _ in seen})
    print(f"{out}: {len(seen)} (texel, palette) pairs, {texels} texel ids from {len(stats)} PACs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
