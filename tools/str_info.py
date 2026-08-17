#!/usr/bin/env python3
"""str_info.py — describe a PSX .STR movie (2336- or 2352-byte sectors) so a
replacement can be checked against the original before dropping it into
game-assets/disc/cdrom/MOVIE/ (docs/ASSETS.md "Replace a cutscene").

Prints: sector count, video/audio sector split, frame count, frame size(s),
STR version, sectors per frame (-> fps at 2x = 150 sectors/s), XA coding
(rate / stereo / bit depth) and XA file/channel numbers, plus a verdict against
the Mega Man 8 originals (320x240, ~10 sectors/frame, XA stereo 37.8 kHz 4-bit,
file 1 channel 1).

    python3 tools/str_info.py MOVIE/ROCK8_0.STR [more.STR ...]
"""

import collections
import struct
import sys
from pathlib import Path

SYNC = bytes([0x00] + [0xFF] * 10 + [0x00])


def sectors_of(data: bytes):
    if len(data) % 2352 == 0 and data[:12] == SYNC:
        return [data[i * 2352 + 16:(i + 1) * 2352] for i in range(len(data) // 2352)], 2352
    if len(data) % 2336 == 0:
        return [data[i * 2336:(i + 1) * 2336] for i in range(len(data) // 2336)], 2336
    raise SystemExit("size is neither a multiple of 2336 nor a 2352-byte raw file with sync")


def describe(path: Path) -> bool:
    data = path.read_bytes()
    secs, geom = sectors_of(data)
    video = audio = other = 0
    dims = collections.Counter(); versions = collections.Counter(); chunks = collections.Counter()
    coding = collections.Counter(); filech = collections.Counter()
    frames = {}
    for i, s in enumerate(secs):
        sub = s[:8]
        submode = sub[2]
        if submode & 0x04 and submode & 0x20:            # audio (Form 2)
            audio += 1
            coding[sub[3]] += 1
            filech[(sub[0], sub[1])] += 1
        elif s[8:10] == b"\x60\x01":                     # STR video chunk header
            video += 1
            (_magic, _type, chunk, nchunks, frame, _size, w, h,
             _codes, _m3800, _q, ver) = struct.unpack_from("<HHHHIIHHHHHH", s, 8)
            dims[(w, h)] += 1; versions[ver] += 1; chunks[nchunks] += 1
            frames.setdefault(frame, i)
        else:
            other += 1
    nframes = len(frames)
    spf = len(secs) / nframes if nframes else 0
    print(f"{path}: {len(secs)} sectors ({geom}-byte), video {video}, audio {audio}, other {other}")
    print(f"  frames {nframes}, dims {dict(dims)}, STR version {dict(versions)}, video chunks/frame {dict(chunks)}")
    print(f"  ~{spf:.2f} sectors/frame -> ~{150 / spf if spf else 0:.1f} fps at 2x, ~{len(secs) / 150:.1f} s")
    for c, n in coding.items():
        rate = 18900 if c & 0x04 else 37800
        print(f"  XA coding 0x{c:02x} x{n}: {'stereo' if c & 1 else 'mono'}, {rate} Hz, {'8' if c & 0x10 else '4'}-bit;"
              f" file/channel {dict(filech)}")
    ok = True
    def want(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            print("  !! " + msg)
    want(dims and set(dims) <= {(320, 240), (0, 0)}, "Mega Man 8 movies are 320x240")
    want(audio > 0, "no XA audio sectors (the game's player expects interleaved audio)")
    # the last audio sector of a movie may be an end marker with a different subheader
    want(coding[0x01] >= 0.95 * audio, "audio should be XA stereo 37.8 kHz 4-bit (coding 0x01)")
    want(filech[(1, 1)] >= 0.95 * audio, "audio subheader should be file 1 / channel 1")
    want(8 <= spf <= 12, "expected ~10 sectors per frame (15 fps)")
    print("  OK for Mega Man 8" if ok else "  differs from the originals — may still play, test it")
    return ok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(0 if all(describe(Path(p)) for p in sys.argv[1:]) else 1)
