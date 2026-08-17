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

## A3 — tile pipeline (decoded from `func_800F99F8`, the column renderer, and the scratchpad ctx)

The loader copies every non-pixel section to a fixed RAM address from a
destination table at **`0x80137840`** (u32 per slot; STDATA type *t* → slot
*t*+4, PLAYER.PAC types 1–3 → slots 1–3): STAGE type 0/1/2 → `0x8016EF34/F334/F734`,
type 3 → `0x80190040` (working copy at `0x80171C3C`), type 4 → `0x8015EA88`,
type 5 → `0x80078000`, 7 → `0x80170348`, 8 → `0x80159F64`, 9 → `0x8015A064`,
12/13/14 → `0x8016D408/DC0C/E40C`, 15 → `0x801AE040`, 18 → `0x800A0000`;
PLAYER 1 → `0x80020000`, 2 → `0x8018FC40`, 3 → `0x80054000`.

Background drawing, per layer (`func_800F98D8` drives 21 columns × N rows,
scratchpad ctx: +4 start col, +6 start row, +8/+A screen x/y, +C **map
base**, +0x10 packet cursor, +0x14/+0x34 two banks of 8 OT list heads,
+0x74 CLUT base word `0x7900`):

```
map     = section 0 / 1 / 2  (one per layer): 32 × 32 bytes, block id per 256×256-px cell,
          index = (row >> 4) * 32 + (col >> 4)             (0 = empty cell)
block   = section 3: 512 bytes per id = 16×16 u16 entries, index (col & 15) + ((row & 15) << 4)
          entry: bits 0-11 tile-def id (0 = empty), bit 12 = OT bank (front/back), bit 13 = semi-transparent
def     = section 4: 4 bytes per id: [ (v_row << 4) | u_col ] [ page slot 0-7 (& 7) ] [ clut byte ] [ flags ]
          u = (b0 & 15) * 16, v = b0 & 0xF0 (16×16 tile inside a 256×256 page column)
          page = VRAM (512 + 64*slot, 256)  → column *slot* of section 259
          clut word = 0x7900 + (b2 & 15) + ((b2 & 0x30) << 2) → palette row 4 + (b2 >> 4 & 3), CLUT index b2 & 15
          b1 & 7 also selects the OT list (one per page → one E1 texpage packet per list)
packet  = SPRT_16 (0x7C) at (screen x, y), (u, v), clut — colour 0x808080
```

`tools/pac_gfx.py tiles STAGE.PAC out/` renders every definition with its
own CLUT (`tiles.png`, 32 per row; `tiles.txt` lists slot/u/v/clut/flags);
`tools/pac_gfx.py map STAGE.PAC out/` renders the three layer maps to
`map_layer<N>.png` + `map.txt` (block grid). Verified on the intro stage: all
540 background tiles of a live frame resolve to exactly one definition each,
and the rendered map is the playable level (beach → ruins → underground);
STAGE01/05/0B render likewise (rooms scattered over the 32×32 grid).

### Sprites — streamed characters (A3b: player done, bosses' strips done)

Found by write-tracing the strip pointer (`wtrace_arm 0x80171038`): the
LoadImage queue routine `0x8010B940` (entries `{src, x, y, w, h}` at
`0x80171038 + 12n`, splitting frames wider than 64 halfwords into consecutive
64-halfword pieces of 2 KB) is fed by `0x80103180`:

```
type   = actor+0x49                                  (0 = Mega Man, 1 = PLAYER sec 3, 2..7 = Robot Masters)
cell   = actor+0x2E & 0xFFF                          (animation cell)
T1     = *(0x8013A428 + 4*type)  : u8[]  cell  -> frame id
T2     = *(0x8013A3F4 + 4*type)  : u32[] frame -> (width_units << 24) | strip offset
src    = actor+0x4C (sheet base in RAM) + offset;  width = width_units * 4 halfwords (= 16 px cells), 16 rows
dest   = actor+0x2C (packed VRAM slot; Mega Man: (320,192))
```

Frames are stored back to back, so T2 exactly tiles the sheet: **Mega Man =
131 frames = `PLAYER.PAC` section 1** (193,280 B); type 1 = 21 frames = PLAYER
section 3; types 2–7 = the Robot Masters' section 17 (BOSSTNG/FRO/GRE/AQU/CLO/DUO
.PAC and the `STAGExxB.PAC` copies: 28/22/10/26/22/24 frames). A frame wider
than 64 halfwords is stored as 64-wide pieces (row stride = piece width).

Metasprites: **section 5 is a sequence of groups** — each `{u16 count, u16
offset}[N]` header (offsets group-relative, N = first offset / 4) followed by
its part lists `{u16 cell, s8 dx, s8 dy}`; the file is fully consumed by 26–27
groups per stage. **Group 0 = Mega Man** (302 entries, one per animation cell:
`cell c → strip T1[c], parts group0[c]`; parts index 16-px cells of the strip,
`u = 16·idx`; bit 15 / 14 of the cell word = H/V flip). Verified against the
live frame (cells 28/29 = strip 14 with/without the arm cell).

`tools/pac_gfx.py sprites PLAYER.PAC out/ --stage STAGE00.PAC` renders
`frames.png` (all strips, in CLUT 0 of PLAYER section 2 = the in-game
palette; `--clut 1..15` = weapon colours) and `poses.png` (all 302 animation
cells assembled). `--type 5 --sheet-section 17` on `BOSSAQU.PAC` renders Aqua
Man's 26 strips (`frames.png`; grey ramp until his CLUT is known — pass
`--palette-pac/--clut`).

⬜ Open: which section-5 group belongs to which enemy/boss (an actor→group
table, plus the boss CLUT); enemy sprites drawn from the section-258 pages
(their cell words presumably carry page/CLUT bits). `--group N` renders any
group's lists against a strip sheet for experiments.

### Sprites — earlier notes

* **Player**: every animation frame is a 16-px-tall *strip* (24–64 halfwords
  = 48–128 px wide, 4bpp) inside `PLAYER.PAC` section 1 (all strips back to
  back, 193 KB, in RAM at `0x80020000`), streamed by LoadImage into the VRAM
  slot (320,192) when the frame changes. Drawn as a **metasprite of 0x2C
  quads**: each part is a 16×16 cell of the strip (`u = 16k`, `v = 192`, CLUT
  `0x7808`, page (320,0)) placed at `(dx, dy)` from the actor position,
  mirrored by vertex order when facing left (`chrdir` bit 0x40/0x80).
* **Metasprite tables** — STAGE section 5 (`0x80078000`, 78 KB): a header
  of 302 `{u16 part_count, u16 offset}` followed by part lists of 4-byte
  `{u16 cell index, s8 dx, s8 dy}`; PLAYER sections 2/3 (`0x8018FC40`,
  `0x80054000`) are pixel data (4bpp).
* ⬜ Open: the **frame → strip (offset, width)** mapping is not a data table
  in the PACs (searched all encodings) — the animation *scripts* (`scrptr` in
  the actor struct, DEBUG-MENU name) compute the source pointer, and the
  LoadImage for the (320,192) slot is issued from the game code (caller of
  `0x800D53F0`'s LoadImage with `s2` = strip pointer). Resolving it (Ghidra on
  the animation interpreter, or logging `s2`/width per frame with the
  `a0_history` extras) gives per-frame sprite sheets. Same for enemies:
  section 258 sheets are cut by their metasprite cells; the cell→(u,v) rule
  is presumably `u = 16*(idx & 15)`, `v = 16*(idx >> 4)` per page — unverified.

## A5 — writing graphics back (`tools/pac_gfx.py pack`)

`extract` now also writes `palette_block.png` (one pixel per BGR555 entry,
256 wide × rows) and `gfx.toml` (source PAC, palette section, pixel sections);
`pack DIR NEW.PAC [--from-tiles]` rebuilds the container: pixel sections
from the indexed `sec<T>_idx.png` (the PNG's palette *indices* are the 4bpp
pixels — keep them indexed), palette from `palette_block.png` (untouched
entries keep their exact bits, edited ones keep the STP bit), or — with
`--from-tiles` — every tile definition's 16×16 pixels from an edited
`tiles.png`, quantised against that tile's own CLUT (exact colours expected;
nearest with a note otherwise; conflicting edits to a page cell shared by two
definitions are reported). All 44 STDATA PACs round-trip byte-identical
through extract → pack (and STAGE00 through `--from-tiles`).

Palette facts learned on the way: `PLAYER.PAC` section 2 (512 B, extract
with `--palette-type 2`) is Mega Man's palette row — **CLUT 0 = normal, CLUTs
1–15 = weapon colours**; the game copies the active one into VRAM row 0 / CLUT
8 (`0x7808`) itself (that is one of the "computed" 256×8 uploads). Each
stage's section 9 row 0 also carries a copy of CLUT 0 without the STP bit
(row 0 / 8), unused for the in-game player. Verified: swapping R↔B in section
2 CLUT 0, `pack`, cold boot from the tree → orange Mega Man in the intro
stage; editing only the stage copy changes nothing.

Workflow:

```sh
python3 tools/pac_gfx.py extract game-assets/disc/cdrom/STDATA/PLAYER.PAC work/player --palette-type 2
#   edit work/player/palette_block.png (entries 0..15 = CLUT 0)
python3 tools/pac_gfx.py pack work/player game-assets/disc/cdrom/STDATA/PLAYER.PAC
python3 tools/pac_gfx.py extract game-assets/disc/cdrom/STDATA/STAGE00.PAC work/st00 && python3 tools/pac_gfx.py tiles ... work/st00
#   edit work/st00/tiles.png (each tile in its own colours) or sec259_idx.png (indices) or palette_block.png
python3 tools/pac_gfx.py pack work/st00 game-assets/disc/cdrom/STDATA/STAGE00.PAC --from-tiles
bash tools/run_mm8.sh          # or a headless screenshot; `bash tools/extract_disc.sh --force` restores pristine
```

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
| `tools/pac_gfx.py extract / tiles / map / pack` | sections → PNG (+ palettes), tile sheet, stage maps, PNG → PAC |
| `tools/pac_tool.py` | container list/unpack/pack |

## Next (ROADMAP A3b–A5)

* A3b: player + Robot-Master strips done; enemy/boss metasprite groups and
  page-based enemy sprites open (see above).
* A5 done (above). Not yet: writing an edited `map_layer*.png` back (needs
  tile matching against the definition set — a level-editor feature), and
  8bpp sections should any PAC turn out to use them.
