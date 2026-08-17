#!/usr/bin/env python3
"""vram_map.py — map CPU->VRAM uploads back to disc files / PAC sections.

Input: a payload dump directory written by the runtime's `vram_upload_log`
debug command (`{"cmd":"vram_upload_log","op":"arm","dir":DIR}` — files named
`<seq>_f<frame>_<x>_<y>_<w>x<h>.bin`, raw halfwords) and the extracted disc
tree. For every distinct payload the tool searches the bytes in every disc file
(PAC sections are resolved to `type/offset`) and prints where each VRAM
rectangle came from. This is ROADMAP track A1: the section -> VRAM map.

    python3 tools/vram_map.py build-debug/vram_dump [--tree game-assets/disc]
                                    [--json out.json] [--min-bytes 512] [--skip-fmv]

Uploads that match nothing are reported too (procedurally generated, FMV
strips, cleared areas...).
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import struct
import sys
from pathlib import Path

NAME_RE = re.compile(r"^(\d+)_f(\d+)_(\d+)_(\d+)_(\d+)x(\d+)\.bin$")


def pac_sections(data: bytes):
    """[(type, offset, size)] for a .PAC container, [] when not a PAC."""
    if len(data) < 0x800:
        return []
    count, total = struct.unpack_from("<II", data, 0)
    if total != len(data) or count == 0 or 8 + count * 8 > 0x800:
        return []
    out = []
    off = 0x800
    for i in range(count):
        t, sz = struct.unpack_from("<II", data, 8 + i * 8)
        out.append((t, off, sz))
        off = (off + sz + 0x7FF) & ~0x7FF
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump")
    ap.add_argument("--tree", default="game-assets/disc")
    ap.add_argument("--json")
    ap.add_argument("--min-bytes", type=int, default=64, help="ignore payloads smaller than this")
    ap.add_argument("--skip-fmv", action="store_true", help="skip 24-halfword-wide 24-bit movie strips")
    a = ap.parse_args()

    files = []   # (relpath, bytes, sections)
    root = Path(a.tree) / "cdrom"
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.upper() != ".STR":
            d = p.read_bytes()
            files.append(("/".join(p.relative_to(root).parts), d, pac_sections(d)))
    print(f"[vram_map] {len(files)} disc files loaded ({sum(len(f[1]) for f in files) // 1024} KB)")

    dumps = []
    for p in sorted(Path(a.dump).iterdir()):
        m = NAME_RE.match(p.name)
        if not m:
            continue
        seq, frame, x, y, w, h = (int(g) for g in m.groups())
        dumps.append((seq, frame, x, y, w, h, p))
    print(f"[vram_map] {len(dumps)} uploads in {a.dump}")

    seen = {}
    results = []
    unmatched = collections.Counter()
    for seq, frame, x, y, w, h, p in dumps:
        if a.skip_fmv and w == 24 and h == 240:
            continue
        payload = p.read_bytes()
        if len(payload) < a.min_bytes:
            continue
        key = (x, y, w, h, payload)
        if key in seen:
            continue
        seen[key] = True
        hits = []
        for rel, data, secs in files:
            i = data.find(payload)
            while i != -1 and len(hits) < 4:
                sec = next(((t, i - off) for t, off, sz in secs if off <= i < off + sz), None)
                hits.append({"file": rel, "offset": i, "section_type": sec[0] if sec else None,
                             "section_offset": sec[1] if sec else None})
                i = data.find(payload, i + 1)
        rec = {"seq": seq, "frame": frame, "x": x, "y": y, "w": w, "h": h, "bytes": len(payload), "hits": hits}
        results.append(rec)
        if not hits:
            unmatched[(w, h)] += 1

    # report grouped by file/section
    by_src = collections.defaultdict(list)
    for r in results:
        if r["hits"]:
            h0 = r["hits"][0]
            by_src[(h0["file"], h0["section_type"])].append(r)
    print(f"\n[vram_map] {len(results)} distinct payloads; {sum(1 for r in results if r['hits'])} matched, "
          f"{sum(1 for r in results if not r['hits'])} unmatched")
    for (f, t), rs in sorted(by_src.items()):
        rs.sort(key=lambda r: (r["hits"][0]["section_offset"] if r["hits"][0]["section_offset"] is not None else r["hits"][0]["offset"]))
        xs = sorted({r["x"] for r in rs}); ys = sorted({r["y"] for r in rs})
        print(f"\n== {f}  section type {t}: {len(rs)} uploads, VRAM x {xs[0]}..{xs[-1]+max(r['w'] for r in rs)}, y {ys[0]}..{ys[-1]+max(r['h'] for r in rs)}")
        for r in rs[:12]:
            h0 = r["hits"][0]
            where = f"sec@{h0['section_offset']:#8x}" if h0['section_offset'] is not None else f"file@{h0['offset']:#8x}"
            print(f"   f{r['frame']:5d} {where} -> VRAM ({r['x']:4d},{r['y']:3d}) {r['w']:3d}x{r['h']:<3d}"
                  f"{'  (+%d more hits)' % (len(r['hits']) - 1) if len(r['hits']) > 1 else ''}")
        if len(rs) > 12:
            print(f"   ... {len(rs) - 12} more")
    if unmatched:
        print("\n[vram_map] unmatched payload shapes:", dict(unmatched))
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1))
        print(f"[vram_map] wrote {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
