#!/usr/bin/env python3
"""
actor_watch.py — live actor inspector for Mega Man 8 over the TCP debug server.

Reads the player and the object arrays straight out of guest RAM and prints
them decoded. Requires a debug-tools build running (RelWithDebInfo; port 4545
per `game.toml [runtime] debug_port`) — e.g. `bash tools/run_mm8.sh --debug`.

The struct layout and the array bases/strides are documented, with their
evidence, in docs/ACTOR_STRUCT.md. Everything printed here is decoded from
Capcom's own debug-menu field printers; the PLAYER record and the ENEMY array
have both been confirmed causally at runtime.

Usage:
    python3 tools/actor_watch.py                 # one snapshot of everything live
    python3 tools/actor_watch.py --watch         # refresh until Ctrl-C
    python3 tools/actor_watch.py --player        # just the player
    python3 tools/actor_watch.py --boxes         # include decoded hitboxes
    python3 tools/actor_watch.py --overlay hb.png   # hitbox viewer: boxes drawn on a frame
    python3 tools/actor_watch.py --set-hp 40     # write the player's HP
    python3 tools/actor_watch.py --port 4545
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time

# --- map from docs/ACTOR_STRUCT.md -----------------------------------------
PLAYER = 0x8015E23C
ARRAYS = [
    # name, base, stride, slots, confidence
    ("ENEMY", 0x8015B174, 0x60, 24, "confirmed"),
    ("SET", 0x801B1EEC, 0x50, 24, "from code"),
    ("MSET", 0x801CF848, 0x40, 24, "from code"),
]
REC = 0x50            # bytes of the record we decode
OFF_LIFE = 0x47
OFF_HITPTR = 0x3C
PEN_X, PEN_Y = 0x801C7384, 0x801C7388   # collision penetration depths
CAM_X, CAM_Y = 0x8016EC0C, 0x8016EC10   # camera scroll (plain s32 world pixels)

FIXED = 65536.0


class Dbg:
    def __init__(self, port: int, host: str = "127.0.0.1"):
        self.addr = (host, port)

    def cmd(self, cmd: str, **kw):
        req = {"id": 1, "cmd": cmd}
        req.update(kw)
        try:
            s = socket.create_connection(self.addr, timeout=20)
        except OSError as e:
            sys.exit(f"cannot reach the debug server on {self.addr[0]}:{self.addr[1]} "
                     f"({e}).\nIs a debug build running?  bash tools/run_mm8.sh --debug")
        with s:
            s.sendall((json.dumps(req) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode(errors="replace").splitlines()[0])

    def read(self, addr: int, length: int) -> bytes:
        r = self.cmd("read_ram", addr=addr, len=length)
        if not r.get("ok"):
            sys.exit(f"read_ram failed: {r}")
        return bytes.fromhex(r["hex"])

    def write_u8(self, addr: int, val: int):
        return self.cmd("write_ram", addr=addr, val=val & 0xFF)


def decode(m: bytes, o: int = 0, avail: int = REC) -> dict:
    """Decode one record. `avail` is how many bytes actually belong to it —
    an array whose stride is smaller than the known 0x49-byte extent simply
    does not have the later fields (they are the next element), so they come
    back as None rather than as a neighbour's data."""
    def u8(k):
        return m[o + k] if k < avail and o + k < len(m) else None

    def s32(k):
        if k + 4 > avail or o + k + 4 > len(m):
            return None
        return struct.unpack_from("<i", m, o + k)[0]

    def u32(k):
        if k + 4 > avail or o + k + 4 > len(m):
            return None
        return struct.unpack_from("<I", m, o + k)[0]

    def fx(k):
        v = s32(k)
        return None if v is None else v / FIXED

    return {
        "beflag": u8(0x00), "routn": tuple(m[o + 1:o + min(5, avail)]),
        "inscrn": u8(0x05), "id": u8(0x06), "tye": u8(0x07),
        "x": fx(0x0C), "y": fx(0x10), "sx": fx(0x14), "sy": fx(0x18),
        "gx": fx(0x1C), "gy": fx(0x20),
        "chrdir": u8(0x25), "seqnum": u8(0x30), "kabeat": u8(0x33),
        "scrptr": u32(0x38), "hitptr": u32(0x3C),
        "norifg": u8(0x40), "jmpflg": u8(0x43),
        "dmg_id": u8(0x44), "str": u8(0x45),
        "muteki": u8(0x46), "life": u8(0x47), "lockon": u8(0x48),
    }


def hitbox(d: "Dbg", ptr):
    """Decode the 4-byte hitbox record at `ptr` (see docs/HITBOX.md)."""
    if ptr is None or not (0x80010000 <= ptr < 0x80200000):
        return None
    b = d.read(ptr, 4)
    s = lambda v: v - 256 if v > 127 else v
    return {"hw": s(b[0]), "hh": s(b[1]), "ox": s(b[2]), "oy": s(b[3])}


def hitbox_str(hb, chrdir):
    if hb is None:
        return ""
    flips = ("H" if (chrdir or 0) & 0x40 else "") + ("V" if (chrdir or 0) & 0x80 else "")
    return (f"  box={hb['hw']*2}x{hb['hh']*2}@({hb['ox']:+d},{hb['oy']:+d})"
            + (f" flip={flips}" if flips else ""))


def _n(v, w=0, prec=None, hexfmt=False):
    if v is None:
        return "-".rjust(w)
    if hexfmt:
        return f"0x{v:08X}"
    if prec is not None:
        return f"{v:{w}.{prec}f}"
    return f"{v:<{w}}" if w else str(v)


def line(tag: str, a: dict) -> str:
    return (f"{tag:<10} hp={_n(a['life'],4)}mut={_n(a['muteki'],3)} "
            f"pos=({_n(a['x'],8,1)},{_n(a['y'],7,1)}) "
            f"vel=({_n(a['sx'],6,2)},{_n(a['sy'],6,2)}) "
            f"g=({_n(a['gx'],5,2)},{_n(a['gy'],5,2)}) id={_n(a['id'],3)} "
            f"rt={a['routn']} dir={_n(a['chrdir'],3)} kabe={_n(a['kabeat'],3)} "
            f"jmp={_n(a['jmpflg'])} nori={_n(a['norifg'],3)} "
            f"hit={_n(a['hitptr'],hexfmt=True)}")


def camera(d: "Dbg"):
    """Camera scroll in world pixels: screen = world - camera."""
    b = d.read(CAM_X, 8)
    return struct.unpack_from("<i", b, 0)[0], struct.unpack_from("<i", b, 4)[0]


def box_rect(a: dict, hb: dict, camx: int, camy: int):
    """Screen-space (x0,y0,x1,y1) for an actor's hitbox — mirrors the engine's
    own flip handling in func_801076CC (see docs/HITBOX.md)."""
    ix, iy = int(a["x"]), int(a["y"])
    cx = (ix - 1) - hb["ox"] if (a["chrdir"] or 0) & 0x40 else ix + hb["ox"]
    cy = (iy - 1) - hb["oy"] if (a["chrdir"] or 0) & 0x80 else iy + hb["oy"]
    return (cx - hb["hw"] - camx, cy - hb["hh"] - camy,
            cx + hb["hw"] - camx, cy + hb["hh"] - camy)


def overlay(d: "Dbg", path: str, scale: int = 3) -> None:
    """Screenshot the game and draw every actor's hitbox on it."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("--overlay needs Pillow (pip install --user pillow)")
    shot = path + ".raw.png"
    r = d.cmd("screenshot", path=shot)
    if not r.get("ok"):
        sys.exit(f"screenshot failed: {r}")
    camx, camy = camera(d)
    im = Image.open(shot).convert("RGB")
    im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    dr = ImageDraw.Draw(im)

    def draw(tag, a, colour):
        hb = hitbox(d, a["hitptr"])
        if hb is None:
            return
        x0, y0, x1, y1 = [v * scale for v in box_rect(a, hb, camx, camy)]
        dr.rectangle([x0, y0, x1, y1], outline=colour, width=2)
        dr.text((x0 + 3, y0 + 2), f"{tag} hp{a['life']}", fill=colour)
        ox, oy = (int(a["x"]) - camx) * scale, (int(a["y"]) - camy) * scale
        dr.line([ox - 6, oy, ox + 6, oy], fill=colour, width=2)
        dr.line([ox, oy - 6, ox, oy + 6], fill=colour, width=2)

    draw("P", decode(d.read(PLAYER, REC)), (0, 255, 0))
    for name, base, stride, slots, _conf in ARRAYS:
        if name != "ENEMY":
            continue
        m = d.read(base, stride * slots)
        for i in range(slots):
            o = i * stride
            if not any(m[o:o + min(stride, REC)]):
                continue
            draw(f"E{i}", decode(m, o, avail=min(stride, len(m) - o)), (255, 40, 40))
    im.save(path)
    print(f"wrote {path}  (camera {camx},{camy})")


def show(d: Dbg, player_only: bool, boxes: bool = False) -> None:
    frame = d.cmd("frame").get("frame", "?")
    hdr = f"--- frame {frame}"
    if boxes:
        pen = d.read(PEN_X, 8)
        hdr += (f"   penetration=({struct.unpack_from('<h', pen, 0)[0]},"
                f"{struct.unpack_from('<h', pen, 4)[0]})")
    print(hdr)
    pa = decode(d.read(PLAYER, REC))
    print(line("PLAYER", pa) + (hitbox_str(hitbox(d, pa["hitptr"]), pa["chrdir"]) if boxes else ""))
    if player_only:
        return
    for name, base, stride, slots, conf in ARRAYS:
        m = d.read(base, stride * slots)
        live = []
        for i in range(slots):
            o = i * stride
            if not any(m[o:o + min(stride, REC)]):
                continue
            live.append((i, decode(m, o, avail=min(stride, len(m) - o))))
        note = "" if conf == "confirmed" else f"  [{conf}]"
        print(f"  {name}: {len(live)}/{slots} live  "
              f"(0x{base:08X} stride 0x{stride:02X}){note}")
        for i, a in live[:12]:
            extra = hitbox_str(hitbox(d, a["hitptr"]), a["chrdir"]) if boxes else ""
            print("    " + line(f"[{i}]", a) + extra)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=4545)
    ap.add_argument("--watch", action="store_true", help="refresh until Ctrl-C")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--player", action="store_true", help="only the player record")
    ap.add_argument("--set-hp", type=int, metavar="N",
                    help="write the player's life field (0-255)")
    ap.add_argument("--boxes", action="store_true",
                    help="also resolve each actor's hitbox (docs/HITBOX.md)")
    ap.add_argument("--overlay", metavar="PNG",
                    help="screenshot the game and draw every hitbox on it")
    args = ap.parse_args()
    d = Dbg(args.port)

    if args.overlay:
        overlay(d, args.overlay)
        return

    if args.set_hp is not None:
        before = d.read(PLAYER + OFF_LIFE, 1)[0]
        d.write_u8(PLAYER + OFF_LIFE, args.set_hp)
        after = d.read(PLAYER + OFF_LIFE, 1)[0]
        print(f"player life {before} -> {after}")
        return

    if not args.watch:
        show(d, args.player, args.boxes)
        return
    try:
        while True:
            show(d, args.player, args.boxes)
            sys.stdout.flush()   # --watch is usually redirected to a log file
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
