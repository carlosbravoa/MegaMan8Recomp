# Mega Man 8 assets — where they live and how to change them

Everything the game loads comes off the disc through the LBA table at
`0x80136F7C` (DISC.md). With the **extracted disc tree** in place
(`bash tools/extract_disc.sh` → `game-assets/disc/`, `psxrecomp/docs/DISC_TREE.md`)
each of those files is a plain host file you can edit, replace or grow; the
runtime serves the result in place and patches the table when a file moves.
This page maps the disc to formats and tools.

| Disc path | What | Format | Edit with |
|---|---|---|---|
| `SLUS_004.53` | boot EXE (the recompiled target) | PS-X EXE | code changes go through the recompiler / mods, not by editing the file |
| `SYSTEM.CNF` | boot config | text | — |
| `OVL/DEMO.BIN`, `OVL/STAGE00..0D.BIN` | streamed engine/stage code overlays (loaded at `0x801D8000`) | raw MIPS + pointer header (`first u32` = id 5..19) | overlay work: see the framework overlay pipeline |
| `STDATA/*.PAC` (44) | stage / boss / player / cutscene graphics + layout data | **PAC container** (below); graphics = 4bpp page columns + CLUT16 palettes, tile maps/blocks/defs (`docs/GRAPHICS.md`) | `tools/pac_gfx.py extract/tiles/map/pack` (PNG in/out), `tools/pac_tool.py unpack/pack` (raw sections) |
| `SOUND/PBGM00..45.PAC` (70), `SOUND/PCOMMON.PAC` | sequenced music + sample banks / common SFX bank | PAC of PsyQ **SEQ / VAB (VH + VB)** | `pac_tool.py`, then any PsyQ SEQ/VAB tool (vgmtrans, PSound, seq2mid, VAB → WAV) |
| `MOVIE/CAPCOM15.STR`, `MOVIE/ROCK8_0..4.STR` | Capcom logo + the five anime cutscenes | STR (MDEC video Form 1 + XA-ADPCM audio Form 2, **raw 2336 B/sector in the tree**) | jPSXdec (decode / replace frames & audio; keep 2336-byte sector output), MC32/mkpsxiso `str` tools |
| `END1.DA` → track 02, `ZNULL.DAT` → track 03 | Red Book CD audio | `audio/track02.wav`, `audio/track03.wav` (44.1 kHz s16 stereo) | any audio editor; drop the WAV in place (other rates/mono are converted at mount) |

Sizes may change freely: a smaller file keeps its LBA, a larger one is
relocated and the table entry (LBA + size, in the game's own unit) rewritten
in the served EXE. `build-release/psx-disc-tree layout game-assets/disc
--game-toml game.toml` shows exactly what will be served; `python3
psxrecomp/tools/disc_tree.py status game-assets/disc` lists what differs from
the pristine dump.

## PAC container

All 119 `.PAC` files share one layout (verified byte-for-byte round-trip by
`tools/pac_tool.py roundtrip` on every file):

```
0x000  u32 count           number of sections
0x004  u32 total_size      = file size (2048-byte multiple)
0x008  { u32 type, u32 size } × count
       zero pad to 0x800
0x800  section 0 payload, padded to the next 2048-byte boundary
       section 1 payload, ...
```

Sections carry no names; `pac_tool.py unpack` writes `NN_typeT.bin` +
`sections.toml`, `pack` rebuilds. Type ids observed:

**SOUND** — `PBGMxx.PAC` = `[5, 4, 513, 1]`, `PCOMMON.PAC` = `[2, 3, 512]`:

| type | content |
|---|---|
| 1 | `pQES` PsyQ SEQ (the song) |
| 4 / 3 | `pBAV` VAB header (VH: programs, tones, VAG offsets) |
| 513 / 512 | VAB body (VB: concatenated VAG ADPCM samples) |
| 5 / 2 | small table (0x140–0x4B8 bytes; per-song/bank parameters — not decoded) |

**STDATA** — 0..21 plus 256..260; the same slots recur across stages:

| type | typical size | notes |
|---|---|---|
| 0, 1, 2 | 0x400 (PLAYER.PAC: type 1 = 0x2F300) | small fixed tables (per-stage headers / CLUT sets?) |
| 3 | 0xC00–0x1BC00 | mid-size block; zero-led in STAGE00 |
| 4 | 0x2FC–0x2D60 | u32 index list (starts `0,1,2,3,...`) |
| 5 | 0x16FC–0x212CC | 16-bit records — the largest structured table (tile map / object layout candidates) |
| 6, 7, 8 | ≤ 0x2A4 | u32 offset tables (type 6 = offsets into another section) |
| 9 | 0x800–0x1000 | **palettes**: 16-bit BGR555 entries (`0x7FFF` white, ...) — 8/16 CLUTs of 256 |
| 10, 12, 13, 14 | 0x800 | fixed 2 KB tables |
| 15 | 0x4E0 | fixed |
| 16, 17, 21 | 0xC00–0x16000 | mid-size, stage-dependent |
| 18 | 0x563–0xBA1 | 16-bit values |
| 256–260 | 0x8000–0x58000 | **pixel data** (raw 4/8 bpp texture pages, no TIM header): 258 in 41 PACs, 259 in 31 |

The graphics pipeline is decoded in `docs/GRAPHICS.md` (VRAM map, tile
maps → blocks → definitions → page columns, palettes) and `tools/pac_gfx.py`
turns it into PNGs and back (`extract`, `tiles`, `map`, `pack`).

## Workflows

**Replace a CD-DA track**

```sh
cp mysong.wav game-assets/disc/audio/track03.wav      # any PCM WAV; 44.1k/16/stereo is served as-is
build-release/psx-disc-tree layout game-assets/disc --game-toml game.toml | grep 'track 3'
bash tools/run_mm8.sh
```

**Edit a sound bank**

```sh
python3 tools/pac_tool.py unpack game-assets/disc/cdrom/SOUND/PBGM00.PAC /tmp/pbgm00
#   03_type1.bin = SEQ, 01_type4.bin = VH, 02_type513.bin = VB — edit / replace
python3 tools/pac_tool.py pack /tmp/pbgm00 game-assets/disc/cdrom/SOUND/PBGM00.PAC
```

**Replace a cutscene** — the originals are STR v2, 320×240, ~15 fps
(10 sectors/frame: 8–9 video + 1 audio at 2×), XA-ADPCM stereo 37.8 kHz 4-bit
on file 1 / channel 1 (`python3 tools/str_info.py MOVIE/ROCK8_0.STR` prints
this for any STR and flags deviations). Two routes:

* *Keep the movie, change the pictures/sound* — jPSXdec (open the loose `.STR`,
  it accepts 2336-byte sectors): "replace frames" (`-replaceframes`) /
  "replace XA" (`-replacexa`) rewrite frames in place at the same size, so the
  sector layout, timing and length stay identical. Safest.
* *A different movie* — encode a new STR v2 with the same geometry: e.g.
  `ffmpeg -i in.mp4 -vf scale=320:240,fps=15 …` then `psxavenc -t str2 …`
  (or PsyQ MOVCONV) with XA stereo 37800 Hz 4-bit, file 1 channel 1, ~10
  sectors/frame; check with `tools/str_info.py`. Any length works: a longer
  file is relocated and the table's STR size (sectors × 2336) rewritten.

Then `cp new.STR game-assets/disc/cdrom/MOVIE/ROCK8_0.STR` (2336 or
2352-with-sync accepted), `build-release/psx-disc-tree layout game-assets/disc
--game-toml game.toml | grep -A1 ROCK8_0`, and a windowless check:
`bash tools/mm8_headless.sh --script 'wait:900;{"cmd":"screenshot","path":"build-release/headless/movie.png"};quit'`
(cold boot: the Capcom logo plays first, `ROCK8_0` from ~frame 500).

**Prove nothing broke / go back**

```sh
python3 psxrecomp/tools/disc_tree.py status game-assets/disc      # what changed
build-release/psx-disc-tree verify game-assets/disc "game-assets/Mega Man 8 (USA)/Mega Man 8 (USA).cue"
bash tools/extract_disc.sh --force                                 # re-extract = pristine again
build-release/psx-disc-tree build game-assets/disc out/mm8-mod.cue --game-toml game.toml   # bin/cue for an emulator
```

## Borrowing files from another dump (e.g. the Japanese movies)

Do not copy STRs saved by an ISO browser: they are cooked (2048 B/sector) and
lose the XA audio sub-headers/payload — the movie plays without sound
(`tools/str_info.py` says "size is neither a multiple of 2336 nor …"). Copy
them raw straight out of the other bin/cue instead:

```
python3 psxrecomp/tools/disc_tree.py copy "Rockman 8 (Japan).cue" game-assets/disc/cdrom 'MOVIE/*.STR'
python3 tools/str_info.py game-assets/disc/cdrom/MOVIE/*.STR        # must say OK for Mega Man 8
```

Nothing else in the tree changes; `disc_tree.py status` lists them as MODIFIED.
