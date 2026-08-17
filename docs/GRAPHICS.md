# Mega Man 8 graphics — VRAM map and section formats (ROADMAP track A)

Measured 2026-08-17 on the debug build: every CPU→VRAM upload from cold boot
through title → GAME START → intro stage was logged with the framework's new
`vram_upload_log` debug command (payload dump), matched byte-for-byte against
the disc tree by `tools/vram_map.py`, and one gameplay frame's GP0 stream
(`gpu_frame_dump`) gave the texture-page depths and CLUTs.

## A1 — where each PAC section lands in VRAM

Graphics are **uncompressed**. The loader streams pixel sections in **2 KB
chunks = 64 halfwords × 16 rows**; chunk *k* of a section goes to

```
x = base_x + 64 * (k // 16)        (a 64-halfword-wide column per 16 chunks = 32 KB)
y = base_y + 16 * (k % 16)         (16 rows per chunk, 256 rows per column)
```

| PAC section | base (x,y) | covers | seen as |
|---|---|---|---|
| `STDATA/<stage>.PAC` **258** | (512, 0) | up to 8 columns → VRAM (512..1024, 0..256) | enemy / object sprite sheets (4bpp) |
| `STDATA/<stage>.PAC` **259** | (512, 256) | up to 8 columns → (512..1024, 256..512) | the stage tileset (16×16 tiles, 4bpp) |
| `STDATA/COMNCHAR.PAC` **256** | (320, 0) | 3 columns → (320..512, 0..256) | common sprites: HUD, shots, explosions |
| `STDATA/COMNCHAR.PAC` **257** | (320, 256) | 3 columns → (320..512, 256..512) | common sprites B |
| `STDATA/COMNCHAR.PAC` **260** | (384, 256) | 1 column | common (overwrites part of 257 later) |
| `STDATA/<stage>.PAC` **9** | (0, 480) | 256 × 8 halfwords | the stage palette block: 8 rows × 256 BGR555 |
| `STDATA/PLAYER.PAC` **1** | (320, 192) | one 64×16 slot, rewritten per animation frame | Mega Man's current sprite frame, streamed (24–64 halfwords wide × 16) |
| `MOVIE/*.STR` (MDEC) | (0..480, 0) / (0..480, 240) | 20 strips of 24×240 | 24-bit FMV, double-buffered display |
| (code) | various | 256×8 | 34 palette blocks that match no file: palette fades/flashes computed from section 9 |

Verified: STAGE00.PAC 258 → 108/108 uploaded chunks at (512,0), 259 → 77/77
at (512,256), PDEMO00.PAC 259 → 77/77, LABO.PAC 259 → 25/25, COMNCHAR 260 →
16/16 (`build-debug/vram_map_intro.json`). Chunks that appear identical in
several PACs (shared blocks) are attributed to the first file found — that is
a property of the search, not of the loader.

## A2 — depth and palettes

In the intro-stage frame examined (670 primitives): 549 `0x7C` textured
16×16 rects + 8 `0x2C` quads, **all 4bpp** (`E1` texpage depth 0), texture
pages (512,256), (576,256), (640,256) [section 259 columns], (320,0) and
(320,256) [COMNCHAR]. Every CLUT is a 16-entry row segment inside the palette
block: `(16·i, 480 + row)` → **section 9 = 128 CLUT16s** (8 rows × 16). So a
4bpp texel index selects within one of these 16-colour CLUTs; which CLUT a
tile/sprite uses is per primitive (from the game's tables), not per page.
8bpp/15bpp usage was not observed in that frame (bosses / cutscene PACs
untested).

## Rendering a section (what `tools/pac_gfx.py extract` does)

```
python3 tools/pac_gfx.py extract game-assets/disc/cdrom/STDATA/STAGE00.PAC out/ [--clut ROW:INDEX]
```

writes `sec258_idx.png` (2048×256, one CLUT applied), `sec259_idx.png`
(1280×256), `sec*_gray.png` (palette index as grey — CLUT independent),
`palettes.png` / `palettes.txt` (all 128 CLUT16 swatches). The pictures are
recognisable at 4bpp with the stage palette (tileset: cliffs, water, ship
parts; 258: enemies), which is the proof of the map above.

## Tools

| | |
|---|---|
| runtime `vram_upload_log` (debug server; framework) | `{"op":"arm","dir":D}` dumps every upload payload; `list` returns `{seq,frame,x,y,w,h,crc,fw}` |
| `tools/vram_map.py DUMP_DIR [--skip-fmv] [--json out]` | payload → disc file / PAC section / offset |
| `tools/pac_gfx.py extract PAC OUT` | sections → PNG (+ palettes) |
| `tools/pac_tool.py` | container list/unpack/pack |

## Next (ROADMAP A3–A5)

* A3 sprite/tile definition tables (which CLUT + rect per sprite frame / tile
  id) so PNGs can be cut per sprite and coloured correctly — Ghidra on
  `0x80171C3C` (tile defs) and the STDATA 16-bit tables (types 5/6/7).
* A5 `pac_gfx.py pack`: PNG → indexed pixels against a recorded CLUT → chunks
  → section (byte-identical round trip on untouched art). Palette recolours
  (section 9) are the first end-to-end edit.
