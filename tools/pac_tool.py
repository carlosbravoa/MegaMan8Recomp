#!/usr/bin/env python3
"""pac_tool.py — list / unpack / repack Mega Man 8 `.PAC` containers.

Every `STDATA/*.PAC` and `SOUND/*.PAC` on the disc is the same container
(observed on all 119, see docs/ASSETS.md):

    u32 count            number of sections
    u32 total_size       file size (multiple of 2048)
    { u32 type, u32 size } x count
    ... zero padding to 0x800 ...
    section 0 payload    (2048-byte aligned start), then section 1, ...

Section payloads are stored back to back, each starting on a 2048-byte
boundary; the file is padded to a 2048-byte multiple. `type` is the game's
section kind (STDATA: 0..21 + 256..260, SOUND: 1 = SEQ, 4 = VAB header, 5 =
unknown, 513 = VAB sample body ...). Sections have no names, so unpacking
writes `NN_typeT.bin` (NN = index) plus `sections.toml` recording the order and
types; `pack` rebuilds a byte-identical container from that directory (edit or
replace payloads freely — sizes are recomputed).

    pac_tool.py list   FILE.PAC
    pac_tool.py unpack FILE.PAC OUTDIR
    pac_tool.py pack   DIR OUT.PAC
    pac_tool.py roundtrip FILE.PAC        # unpack + pack in memory, assert identical
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ALIGN = 0x800

MAGIC = {b"pQES": "SEQ (PsyQ sequence)", b"pBAV": "VAB header (PsyQ voice bank)",
         b"VAGp": "VAG sample", b"\x10\x00\x00\x00": "TIM image"}


def parse(data: bytes):
    count, total = struct.unpack_from("<II", data, 0)
    if 8 + count * 8 > ALIGN:
        raise SystemExit("not a PAC (header overflow)")
    entries = [struct.unpack_from("<II", data, 8 + i * 8) for i in range(count)]
    off = ALIGN
    sections = []
    for t, sz in entries:
        if off + sz > len(data):
            raise SystemExit(f"section extends past EOF (off {off:#x} size {sz:#x})")
        sections.append((t, off, sz))
        off = (off + sz + ALIGN - 1) & ~(ALIGN - 1)
    return count, total, sections, off


def build(sections: list[tuple[int, bytes]]) -> bytes:
    hdr = bytearray(ALIGN)
    off = ALIGN
    body = bytearray()
    for i, (t, payload) in enumerate(sections):
        struct.pack_into("<II", hdr, 8 + i * 8, t, len(payload))
        body += payload
        pad = (-len(payload)) % ALIGN
        body += bytes(pad)
        off += len(payload) + pad
    struct.pack_into("<II", hdr, 0, len(sections), off)
    return bytes(hdr) + bytes(body)


def describe(payload: bytes) -> str:
    for m, name in MAGIC.items():
        if payload[:4] == m:
            return name
    if len(payload) >= 32 and all(b == 0 for b in payload[:32]):
        return "zero-led"
    return ""


def cmd_list(a):
    data = Path(a.pac).read_bytes()
    count, total, sections, end = parse(data)
    print(f"{a.pac}: {count} sections, total_size {total:#x} (file {len(data):#x}, computed end {end:#x})")
    for i, (t, off, sz) in enumerate(sections):
        print(f"  #{i:2d} type {t:4d} (0x{t:03x}) off {off:#8x} size {sz:#8x} {sz:8d}  {describe(data[off:off + sz])}")
    return 0


def cmd_unpack(a):
    data = Path(a.pac).read_bytes()
    count, total, sections, end = parse(data)
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"# unpacked from {Path(a.pac).name}", f"source = \"{Path(a.pac).name}\"", ""]
    for i, (t, off, sz) in enumerate(sections):
        name = f"{i:02d}_type{t}.bin"
        (out / name).write_bytes(data[off:off + sz])
        lines += ["[[section]]", f"index = {i}", f"type = {t}", f"file = \"{name}\"", ""]
    (out / "sections.toml").write_text("\n".join(lines), encoding="utf-8")
    print(f"unpacked {count} sections to {out}")
    return 0


def cmd_pack(a):
    import tomllib
    d = Path(a.dir)
    with open(d / "sections.toml", "rb") as f:
        m = tomllib.load(f)
    secs = []
    for s in sorted(m["section"], key=lambda s: s["index"]):
        secs.append((int(s["type"]), (d / s["file"]).read_bytes()))
    data = build(secs)
    Path(a.out).write_bytes(data)
    print(f"packed {len(secs)} sections -> {a.out} ({len(data)} bytes)")
    return 0


def cmd_roundtrip(a):
    data = Path(a.pac).read_bytes()
    count, total, sections, end = parse(data)
    rebuilt = build([(t, data[off:off + sz]) for t, off, sz in sections])
    if rebuilt == data:
        print(f"{a.pac}: round-trip identical ({count} sections)")
        return 0
    print(f"{a.pac}: round-trip DIFFERS ({len(rebuilt)} vs {len(data)} bytes)")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("pac"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("unpack"); p.add_argument("pac"); p.add_argument("outdir"); p.set_defaults(fn=cmd_unpack)
    p = sub.add_parser("pack"); p.add_argument("dir"); p.add_argument("out"); p.set_defaults(fn=cmd_pack)
    p = sub.add_parser("roundtrip"); p.add_argument("pac"); p.set_defaults(fn=cmd_roundtrip)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
