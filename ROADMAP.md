# MegaMan8Recomp — roadmap

Where the project stands (2026-08-17), what is pending, and the scoping of the
long road towards **an engine that can draw upscaled / redrawn graphics**.
Status legend: ✅ done · 🔧 in progress · ⬜ pending · ❓ needs a measurement
before it can be sized.

## 0. Where we are

| Area | State |
|---|---|
| Static recompile of `SLUS_004.53`, boots to gameplay, 0 dispatch misses (15-min attract soak) | ✅ |
| Streamed overlays (OVL/*.BIN) captured → compiled shards, in-session autocompile (Linux) | ✅ |
| Widescreen 16:9 (native-wide bg2d), HUD anchoring; stage-start geometry glitch | ✅ / ⬜ (#16) |
| Video filters, F9 bug bundles, headless script mode | ✅ |
| Symbols/annotations pipeline; actor / hitbox / camera structs documented | ✅ (73 named of 7,292 — ongoing) |
| **Extracted disc tree** — game runs from `game-assets/disc/` without the bin/cue, byte-identical while pristine, files editable/relocatable, LBA table rewritten | ✅ |
| PAC container decoded; `pac_tool.py`; STR/XA/CD-DA parameters known; media replacement procedures | ✅ (README → *Customizing media*, `docs/ASSETS.md`) |
| Framework fixes as real commits on the `mm8` fork branches; fresh clone reproducible | ✅ (`upstream/README.md`) |
| Framework PRs to `mstan/psxrecomp` (7) and `mstan/recomp-ui` (1) | ⬜ |

## 1. Track A — Graphics assets: PNG in, PNG out (the prerequisite for everything below)

**Goal:** `tools/pac_gfx.py extract STAGE00.PAC out/` writes every image the
PAC contributes as PNG (with palette), and `tools/pac_gfx.py pack` rebuilds a
PAC from edited PNGs, so an artist can repaint sprites, tiles and backgrounds
without touching hex. Served through the disc tree like everything else.

**What we know** (`docs/ASSETS.md`): STDATA PACs carry pixel data as raw VRAM
pages (sections 256–260, 32–352 KB, no TIM headers) and palettes as BGR555
CLUT sets (section 9, 8–16 × 256 entries); tile definitions for the
background renderer sit in the EXE at `0x80171C3C` (16×16 blocks, 512 bytes
each, two layers, tile map at `layer+12`); sprite drawing uses `0x7C`
sprites / `0x2C` quads with texpage + CLUT. Where each section lands in VRAM
(x, y, w, h, bit depth) and how sprites/tiles index those pages lives in **code**
(`StageModuleLoad` = `0x801014E8` and its LoadImage calls, the per-stage
tables in sections 4–8/10–15), not in the data.

**Steps**

| # | Task | How | Size |
|---|---|---|---|
| A1 | Map PAC sections → VRAM rects | ✅ **done** (`docs/GRAPHICS.md`): framework `vram_upload_log` + `tools/vram_map.py`; sections stream in 2 KB chunks (64 hw × 16 rows) → column ⌊k/16⌋ / row 16·(k mod 16) of a base rect: 258 → (512,0), 259 → (512,256), COMNCHAR 256/257/260 → (320,0)/(320,256)/(384,256), palette block 9 → (0,480), player frames streamed to (320,192). Graphics are uncompressed. | done |
| A2 | Determine bit depth + CLUT per rect | ✅ intro stage: everything 4bpp; CLUT = 16-entry segment `(16·i, 480+row)` of the section-9 block (128 CLUT16s). ⬜ confirm for boss/cutscene PACs (8bpp?). | mostly done |
| A3 | Sprite / tile *definitions* | ✅ **tiles done** (`docs/GRAPHICS.md`): layer maps (sec 0/1/2, 32×32 block ids) → blocks (sec 3) → tile defs (sec 4: uv, page slot, clut, flags) → page columns of sec 259; `pac_gfx.py tiles` / `map` render tile sheets and full stage maps from the PAC alone. ✅ **Mega Man**: frame tables in the EXE (`0x8013A3F4/0x8013A428`), 131 strips, section-5 group 0 metasprites → `pac_gfx.py sprites` renders all frames + 302 assembled poses; Robot Masters' strips (types 2–7, section 17) decode. ⬜ enemy/boss metasprite group mapping + page-based enemy sprites. | done for the player |
| A4 | `tools/pac_gfx.py extract` | ✅ section → PNG (indexed + grey), palette block + swatches, `tiles` (every def in its own CLUT), `map` (full stage layers). ⬜ per-sprite sheets (needs A3b). | done |
| A5 | `tools/pac_gfx.py pack` | ✅ indexed PNGs / `palette_block.png` / `--from-tiles tiles.png` → PAC; all 44 STDATA PACs round-trip byte-identical; **recolour of Mega Man (PLAYER.PAC sec 2 CLUT 0) verified in game from a cold boot off the tree**. ⬜ map write-back (tile matching), 8bpp. | done |
| A6 | Docs: `docs/GRAPHICS.md` — page maps per PAC type, sprite tables, limits (VRAM page budget, palette rules) | small |

Deliverable check ✅ (2026-08-17): Mega Man recoloured via `PLAYER.PAC`
section 2 CLUT 0, repacked, cold boot headless into the intro stage shows the
new colours; `extract` → `pack` of every STDATA PAC round-trips byte-identical.

## 2. Track B — Upscaled graphics in the framework (the long road)

**Goal:** the game draws with **higher-resolution replacement art** (2×/4×
sprites, tiles, backgrounds; later redrawn assets), opt-in, faithful path
untouched. This is a *framework* feature (every psxrecomp title benefits) and
must follow the framework's verified-enhancement carve-out
(`psxrecomp/docs/SHADOW_ENHANCEMENTS.md`): opt-in, present-time/renderer-side,
byte-identical with it off, the canon path stays the oracle.

**What already exists to build on**

* Software renderer **S× hi-res mirror** (`gpu_sw_renderer.c`:
  `sw_renderer_set_scale(S)`, `g_hr`, `rt_hires()`): every primitive is
  rasterised a second time at S× into a scaled VRAM mirror; the present path
  downsamples. Today textured primitives sample the *native* texels (nearest,
  block-upscaled). **This is the hook**: at S× a textured rect/quad can sample
  an S× replacement texture instead of VRAM.
* VRAM dirty tracking (`gpu_vram_dirty.c`), depth24 handling, the GL renderer
  with a VRAM FBO, GLSL filter twins, and the video-filter pipeline
  (`docs/VIDEO_FILTERS.md`) as the model for "CPU reference + GL twin +
  parity tool".
* Widescreen bg2d machinery (extra tile columns) — the HD path must compose
  with it (same tile draw calls, wider).

**Design sketch (texture-replacement pack)** — the approach DuckStation /
PCSX-Redux / Dolphin use, adapted to a recomp:

| # | Task | Notes | Size |
|---|---|---|---|
| B1 | **Texture identity** | Key = hash of the referenced VRAM rect (texpage + uv rect of the primitive, in the primitive's bpp) + CLUT contents (+ optional page/CLUT coords). Compute per primitive at S× draw time; cache by (page,clut,rect) invalidated by the VRAM dirty bitmap. Sprites (`0x7C`) and quads (`0x2C`) give exact rects; polygons need uv-bbox. | medium |
| B2 | **Dump mode** | `[video] texture_dump = true` (or debug cmd): write `textures/dump/<hash>.png` (de-palettised RGBA) the first time each key is seen, plus a `dump.json` with page/clut/rect/bpp/first-seen frame. Playing through the game populates the set. Sits beside the disc tree (`game-assets/textures/`). | small |
| B3 | **Load + replace (software hi-res path)** | `[video] texture_pack = "…"`: on start index `<hash>.png` files (any integer scale N ≤ S); in `raster_textured_rect_scaled` / the S× textured triangle path sample the replacement (bilinear or nearest per pack setting) instead of VRAM. Semi-transparency, colour modulation (`texel*color*2/256`), STP bit and 15-bit output stay as on PSX. Missing entries fall back to native texels — a partial pack still works. | medium–large (rasterizer + cache) |
| B4 | **GL renderer twin** | Same lookup as a texture atlas / array in the GL path (the FBO renderer draws from VRAM textures today); parity tool like `tools/video_filter_check.py` (GL == CPU ≤ 1 LSB with the same pack). | large |
| B5 | **Present at S×** | Presenting the S× mirror already exists (supersampling); with replacements it becomes real detail. Video filters run after (or are disabled at S>1). Windowed/GL frame-interpolation interplay to check. | small |
| B6 | **Backgrounds / tiles** | MM8 backgrounds are 16×16 tile quads built in scratchpad from `0x80171C3C` — they go through B3 naturally (per-tile keys). Parallax layers likewise. Nothing engine-side needed for 2D tiles. | covered by B3 |
| B7 | **Pack authoring workflow** | `game-assets/textures/dump/` → artist upscales/redraws → `game-assets/textures/pack/`; `tools/texpack.py` validates sizes (multiple of native), lists coverage per stage; docs. Ties to Track A: A4's sprite sheets tell the artist *what* a texture is (name it), the dump tells *how it's sampled*. | small |
| B8 | **FMV** | The five cutscenes are MDEC 320×240 — no texture to replace. HD path = play a host video (e.g. an upscaled mp4/webm) in place of the STR: hook the STR player's frame presentation (24-bit depth24 path already isolates FMV) and substitute decoded frames at S×, keeping the game's timing/audio from the STR (or the file's own audio). Separate feature; sized only after Track A/B basics. | large |
| B9 | **Governance** | Opt-in launcher toggle, off = byte-identical (frame hashes on canon), DEGRADED logging when a pack entry mismatches its recorded native hash, tests (unit: hash stability across identical VRAM content; parity: CPU vs GL). | small, continuous |

**Open measurements before sizing B3/B4 firmly** (all cheap with the debug
build): number of distinct texture keys in the intro stage / whole game
(cache size, dump volume); how many primitives per frame are textured rects vs
polys (MM8 is 2D: expect ~all rects); whether the game re-uploads sprite
frames each frame (VRAM streaming ⇒ hash churn, needs the dirty bitmap to be
per-page granular) or keeps stage sheets resident (likely, given the PAC page
layout).

## 3. Track C — Engine-side enhancements (after A/B; each its own decision)

* ⬜ Widescreen #16 (stage-start geometry corruption) — root cause narrowed to
  the parallax builder at stage start; finish before HD packs stress it.
* ⬜ Higher internal *geometry* precision (sub-pixel sprite positions,
  16.16 actor positions already exist) — only meaningful once S× art exists.
* ⬜ Optional 60 Hz smoothing / frame pacing tweaks (framework: GL frame
  interpolation thread never swaps on this box — pre-existing #16-framework).
* ⬜ Redrawn HUD at S× (HUD sprites are ordinary `0x7C` sprites → covered by
  B3, but the anchored-HUD widescreen rule must apply to the replacement).

## 4. Track D — Framework & project hygiene

* ⬜ Open the seven PRs against `mstan/psxrecomp` and one against
  `mstan/recomp-ui` from the `mm8` fork branches (`upstream/README.md`,
  bodies for §1–3 in `upstream/pr/`); rebase `mm8` when they land, re-pin.
* ⬜ Windows build of the disc-tree code (std::filesystem/ifstream only, but
  unbuilt there); CI job that runs `disc_tree_test`, `iso_reader_cdda_test`,
  `video_filter_test`.
* ⬜ Disc-tree follow-ups: launcher shows "disc tree" as the mounted source;
  mod packages that overlay *files by path* on top of a tree (today disc mods
  are keyed on the stock image SHA-256, so they are inert on a tree);
  extraction from CHD (runtime already mounts CHD).
* ⬜ `docs/ASSETS.md` unknowns: SOUND section 5/2 tables, STDATA section
  types 0–3, 10–15 (fall out of Track A's RE).
* ⬜ Symbolization: keep growing `symbols.toml`/annotations from the DEBUG MENU
  printers and the stage loader RE.
* ⬜ ISSUES.md #4 (verification backlog), #7, #5 (generated C size, dev-only).

## 5. Suggested order

1. **A1–A2 measurements** (one debug session): the VRAM map turns the rest of
   Track A into scripting.
2. **A4/A5 page-level PNG round trip + palette recolour demo** — first visible
   artist-facing win.
3. **B1–B2 dump mode** on the software renderer (small, and it produces the
   dataset that tells us how big B3 really is).
4. **A3 sprite tables** in parallel (Ghidra), so dumps and PACs can be
   cross-named.
5. **B3 software replace path** → 2× pack of the intro stage as the proof; then
   B4 GL twin, B7 tooling, B9 governance; B8 FMV last.
6. Track D PRs whenever a piece is stable — the fork branch makes each one
   a cherry-pick.
