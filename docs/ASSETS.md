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
| `STDATA/*.PAC` (48) | stage / boss / player / cutscene graphics + layout data | **PAC container** (below) | `tools/pac_tool.py unpack/pack` |
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

The graphics are palette + raw VRAM pages, uploaded by the stage loader
(`StageModuleLoad` = `0x801014E8`) with geometry that lives in the game code,
not in the data — decoding them to PNG needs the upload/tile RE that
`docs/WIDESCREEN.md`'s bg2d notes started (`0x80171C3C` tile definitions,
16×16 blocks of 512 bytes). Until then, edits at the byte level (palette
swaps in type 9, pixel edits in 258/259 with a VRAM-page-aware editor) are
already possible and served through the tree.

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

**Replace a cutscene**: decode `MOVIE/ROCK8_0.STR` with jPSXdec, replace
frames/audio there, save the STR back as 2336-byte sectors (or 2352 with
sync — both are accepted) to the same path. Longer movies are relocated
automatically; the table's STR size (sectors × 2336) is rewritten.

**Prove nothing broke / go back**

```sh
python3 psxrecomp/tools/disc_tree.py status game-assets/disc      # what changed
build-release/psx-disc-tree verify game-assets/disc "game-assets/Mega Man 8 (USA)/Mega Man 8 (USA).cue"
bash tools/extract_disc.sh --force                                 # re-extract = pristine again
build-release/psx-disc-tree build game-assets/disc out/mm8-mod.cue --game-toml game.toml   # bin/cue for an emulator
```
