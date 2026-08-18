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
| Widescreen 16:9 (native-wide, **left-anchored** reveal, bg2d, HUD anchoring, edge-bound + spawn-window logic; centred menus) | ✅ (#16 resolved 2026-08-18) |
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
| B1 | **Texture identity** | ✅ `runtime/src/texture_pack.c` hooked in `gpu_render.c` (all backends): **texel id** (indices + size + depth, VRAM-location and CLUT independent) + **palette id** (CLUT contents) per primitive; rects exact, triangles by uv-bbox with the inclusive/exclusive rule. `psxrecomp/docs/TEXTURE_PACKS.md`. | done |
| B2 | **Dump mode** | ✅ `texture_dump` debug cmd / `PSX_TEXTURE_DUMP`: `<tex>-<pal>.png` + `textures.tsv`; unit test `texture_pack_test`. Measured boot → intro stage: 1.2 M notes, 9,701 (texel,palette) pairs, **776 texel ids** (fades ×32 → the split identity is the right call). ⬜ `[video]` key + coverage helper script. | done |
| B3 | **Load + replace (software hi-res path)** | ✅ `texture_pack` debug cmd / `PSX_TEXTURE_PACK`: `<tex>[-<pal>].png` at integer scale; sampled by the S× rect/scaled-rect/triangle rasterisers (alpha, native STP bit, existing modulation/blend); native VRAM untouched (verified byte-identical); partial packs fall back. Verified with a 776-image 2× pack on the intro stage. `[video]` key = B7, fade-aware palettes = B9. ⬜ shaded-textured tris. | done |
| B4 | **GL renderer twin** | ✅ pack atlas + two flat vertex attributes + shader sampling in `gpu_gl_renderer.c`; verified identical replacements to the SW path on the intro stage at 2×. Documented divergence: on GL the FBO is VRAM, so replaced framebuffer pixels are visible to VRAM readbacks. ⬜ parity tool (SW vs GL ≤ 1 LSB), bilinear pack sampling. | done |
| B5 | **Present at S× / filter interplay** | ✅ Rule on both backends (`psxrecomp/docs/VIDEO_FILTERS.md` → *With supersampling*): at internal scale > 1 the pixel-art upscalers stand down (GL pass B sharp fit / SW plain hi-res present; ESC menu row says `(1X ONLY)`), the display looks (sharp / scanlines / crt) apply at native line pitch — new `video_filter_apply_cpu_ss()` for the software present + headless `present_capture`, GL `vf_present` stand-down, `video_filter` debug fields `applies_at_scale` / `internal_scale` / `stood_down`, unit test. Verified SW 2× (weapon menu: xbr2x/scale3x/sharp ≡ none, scanlines at native pitch) and GL 2× windowed. GL frame interpolation goes through the same `vf_present`. | done |
| B6 | **Backgrounds / tiles** | MM8 backgrounds are 16×16 tile quads built in scratchpad from `0x80171C3C` — they go through B3 naturally (per-tile keys). Parallax layers likewise. Nothing engine-side needed for 2D tiles. | covered by B3 |
| B7 | **Pack authoring workflow** | ✅ `[video] texture_pack` + `texture_pack_enabled`, launcher "HD textures" checkbox (recomp-ui, persisted in settings.toml, live from the in-game launcher), `psxrecomp/tools/texpack.py summary/starter/coverage/validate/sheet`; MM8 points at `game-assets/textures/pack` (a 2× starter pack is there locally). ⬜ per-stage coverage runs, naming from Track A sheets. | done |
| B8 | **FMV** | ✅ HD movie packs (`psxrecomp/docs/FMV_PACKS.md`): `<pack>/<MOVIE>/NNNNN.png|jpg` presented in place of the depth24 MDEC picture, keyed by the STR file the CD is streaming (`cdrom_current_file` via a one-time ISO tree walk) and the MDEC decode index (helper thread + prefetch, never stalls); STR audio/timing untouched. `[video] fmv_pack`, launcher "HD movies", `PSX_FMV_PACK`, debug `fmv_pack`; `fmv_dump` / `PSX_FMV_DUMP` writes the native frames 1:1; `tools/fmv_pack.py info/upscale/from-video(ffmpeg)/check`. Verified SW headless + windowed SW + windowed GL with an index-encoded synthetic pack. ⬜ Vulkan present unverified; no video container (frame sequences only). | done |
| B10 | **Whole-game coverage** | ✅ `tools/pac_texpack.py` hashes every tile definition of all 31 tile-pipeline PACs offline (37,621 texel ids: every background of every stage/menu/demo/ending, palettes + map draw counts, dump layout) — proven against the intro-stage dump pair for pair; `tools/texdump_sweep.sh` = PACs + headless dumps (title/menus, developer-warp stages 00–03 with a walk/jump/shoot loop, all savestate slots) → `texpack.py merge` (new) → `starter` → coverage. Result 38,644 texel ids / 46,716 images at 2× (364 MB), pixel-identical on stage / pause / title savestates, 100 % hits; parallel pack loading (10 s → 1.2 s). Bookmarks (`saves/bookmarks/*.pst`, `tools/bookmark.sh`) are dump sources too: with the first five stage bookmarks the merged set is 40,817 texel ids / 69,625 images, 100 % hits and pixel-identical on the Grenade Man bookmark. ⬜ the remaining stages/bosses/endings as bookmarks, or `PSX_TEXTURE_DUMP` while playing, then re-run the sweep. | done |
| B11 | **SW ↔ GL parity tool** | ✅ `psxrecomp/tools/texpack_parity.py` (+ `tools/texpack_parity.sh`): four scripted runs per savestate at the same `PSX_SUPERSAMPLING` (SW headless `screenshot_hires`, GL windowed `present_capture` `.src.png` = exact FBO readback), pass = the pack adds no SW/GL divergence over the no-pack baseline (tolerance 8/255). MM8 slots 12/1/3: baseline max 1/255, pack delta 0. | done |
| B12 | **Names from Track A** | ✅ `tools/pac_texpack.py` writes `names.tsv` (tex_id → `STAGE00/tile0123` / `PLAYER/strip057_cell07` / `BOSSAQU/strip003_cell00`, aliases across PACs) and, with `--sprites`, adds Mega Man's strip cells to the dump (in-game CLUT 0 + the 15 weapon palettes as variants) and the bosses' texel ids (names only — CLUTs unknown); player cell hashes verified against a play dump. `texpack.py` gained `merge` name union, `starter` copies names into the pack, `export`/`import` (human-named working copies ↔ pack, hardlinks, `index.tsv`) and `sheet --names/--group` (captioned). Pack now 39,986 texel ids / 67,101 images at 2× (weapon palettes are 20 k of them), still pixel-identical on the stage/pause savestates. ⬜ boss/enemy CLUTs and the enemy metasprite groups (A3b open items) would name/cover enemies offline. | done |
| B13 | **Odds and ends** | ✅ `[video] texture_pack_filter = auto|nearest|linear` — bilinear (alpha-weighted, clamped) pack sampling on both backends, auto = only when the image is not 1 px per hi-res pixel (2× pack at 2× stays byte-identical; nearest is SW≡GL, linear within ~2 % of changed pixels); on-demand GL atlas (4096², images placed when first drawn, flush+reset when full — a 67 k-image pack costs ~800 resident) with `texture_pack stats` `gl_atlas`; 8bpp dump/pack/lookup/fit covered by the unit test. ⬜ shaded-textured triangles (3D only); boss/enemy CLUTs + enemy metasprite groups (Track A) for offline enemy coverage. | done |
| B9 | **Palettes, fades, governance** | ✅ `.clut` sidecars per pack entry (dump writes them, `starter` copies them), two-model uniform-fade fit (multiplicative / subtractive, rms < 2) applied as scale+offset in the SW rasterisers and the GL shader (`a_rep_mod`/`a_rep_off`), variant selection by best-fitting reference palette over the entries the texture uses (else **native texels** — never authored art under a foreign palette; `stats.native_recolour`), `pairs.tsv` draw counts → `starter --palette common` (+ automatic `<tex>-<pal>` recolour variants), native-0x0000 transparency honoured, usage accounting (`stats.used`, `texture_pack usage`, unload log), `PSX_TEXTURE_PACK` applied at startup, `vram_peek hires`. **Verified pixel-identical to native** (2× starter pack, software) through the title fade-in, white flash + fade back, intro stage, stage select, pause menu, title menu; GL ≤ 2/255. ⬜ SW-vs-GL parity tool, palette-cycling variants (buster charge flash etc. are recolours → native until a variant exists). | done |

**Measurements (done with B2)**: intro-stage slice = 776 texel ids (whole
game: expect low thousands); ~500 textured primitives per frame, 98% 16×16
rects (`0x7C`) + a few quads; sprite frames ARE streamed per animation frame
(player slot) but the texel id is location-independent so that costs nothing;
hashing every primitive every frame is ~1.2 M texel reads/s — no cache needed
so far.

## 3. Track C — Engine-side enhancements (after A/B; each its own decision)

* ✅ Widescreen #16 — resolved by anchoring the reveal on the left
  (`[widescreen] nw_anchor = "left"`, gate + world veto for menus) and moving
  the game's off-screen logic (keep-alive / inscrn / spawn strip / edge parks,
  main EXE + per-stage overlays) with the reveal (2026-08-18,
  `docs/WIDESCREEN.md`). Left over: overlay-local edge idioms not yet
  understood (listed there), boss rooms unverified, in-stage text (READY /
  boss names) stays at its 4:3 position, the wipes cover only 320 px.
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
