# MegaMan8Recomp

> _This recompilation is a **byproduct of developing
> [psxrecomp](https://github.com/mstan/psxrecomp)** — the games are the proving
> ground, the framework is the goal. **This is an in-development bring-up, not a
> finished port — expect rough edges.**_

Mega Man 8 (USA, SLUS-00453) statically recompiled to a native PC executable
with [PSXRecomp](https://github.com/mstan/psxrecomp) — the same framework behind
[TombaRecomp](https://github.com/mstan/TombaRecomp),
[MegaManX4Recomp](https://github.com/mstan/MegaManX4Recomp),
[MegaManX5Recomp](https://github.com/mstan/MegaManX5Recomp) and
[MegaManX6Recomp](https://github.com/mstan/MegaManX6Recomp).

## What This Is

This repository contains the game-specific configuration, seeds, tools, and
build glue for running Mega Man 8 on the PSXRecomp framework. The game's MIPS
code is machine-translated ("recompiled") ahead of time into native C, then
compiled into a native Linux or Windows program that runs the game's own logic
on a faithful simulation of the PS1 hardware (GPU, SPU, GTE, CD-ROM, memory
cards) plus a real, recompiled PS1 BIOS (the bundled OpenBIOS or your own
SCPH1001 dump) — no high-level emulation shims.

It does **not** contain the Mega Man 8 disc image, the PS1 BIOS, generated game
code, or any decompiled game C. Those are produced locally from your own legally
obtained assets.

| | |
|---|---|
| Serial | SLUS-00453 (`SLUS_004.53`) |
| Players | 1 |
| Region | USA |
| Publisher | Capcom |
| Year | 1997 |

Important files:

- `game.toml`: runtime / recompiler / video / controller config (autofilled by
  the framework's disc probe, then hand-tuned).
- `seeds/ghidra_funcs.txt`: function-start seeds (entry + boot-EXE JAL scan).
- `symbols.toml` → `psx_symbols.h`: progressive symbol map (`tools/sync_symbols.py`).
- `tools/regen.sh`: regenerates the BIOS backends + recompiled game C.
- `tools/run_mm8.sh`: launches the dev build with the local BIOS + disc baked in.
- `tools/build_overlay_shards.sh`: compiles captured `OVL/*.BIN` overlays into
  native Linux shards offline. Optional — the runtime now does this during play
  (see below); this is the bulk pre-build path.
- `tools/analyze_symbols.py` + `docs/SYMBOLS.md`: evidence-driven symbol
  discovery — names the generated C from BIOS thunks, self-logging library
  literals, and Capcom's shipped debug menu.
- `docs/ACTOR_STRUCT.md`: Mega Man 8's actor structure and object arrays,
  decoded from that debug menu's field printers and confirmed causally against
  the live player and enemies.
- `docs/HITBOX.md`: the 4-byte hitbox record and the engine's AABB test.
- `docs/WIDESCREEN.md`: the opt-in 16:9 toggle, how it engages, and what is left.
- `mods/preloaded/` + `src/mods/`: the game-owned mod catalog and its trusted
  plugins (currently the widescreen activation plugin).
- `tools/actor_watch.py`: live actor inspector over the debug server
  (`--watch`, `--boxes`, `--set-hp`) — the seed of practice/hitbox tooling.
- `tools/mm8_headless.sh`: windowless, unpaced scripted run (load a save slot,
  screenshot, capture the filtered present, write a telemetry bundle, exit) —
  the default way to verify things without opening the game.
- `tools/video_filter_check.py`: proves the OpenGL video-filter shaders match
  the CPU reference pixel-for-pixel on a live frame.
- `docs/VIDEO_FILTERS.md`: the filter set and how it is verified.
- `upstream/`: framework fixes not yet landed upstream, kept as tracked patches.
- `scripts/package_setup_release.sh` + `.github/workflows/release.yml`:
  setup-host release packaging (CI ships no game C — players Generate locally).
- `DISC.md`: source-disc identity and verification hashes.
- `ISSUES.md`: game-specific issue log.
- `ghidra/instructions.txt`: Ghidra import notes for the boot EXE.

## Status

**Early bring-up — `v0.1.0` (unreleased).** On the first generated build
Mega Man 8 **boots and plays**: the Capcom logo and intro FMV decode, the title
screen and menu respond, and GAME START drops into the intro stage with working
(digital) controller input and **no dispatch misses** on that path. It has
**not** been verified deep into stages, with audio, or on OpenBIOS; uncovered
code paths halt loudly rather than misbehave silently (see `ISSUES.md`).

| Area | State |
|---|---|
| PS1 BIOS boot | Works (recompiled SCPH1001 core, HLE boot-skip); OpenBIOS backend linked, not yet exercised |
| Disc-detect / boot | Works (multi-track cue; XA/MDEC intro FMV plays — needs the local `gpu.c` depth24 fix, ISSUES #6) |
| Title / menus | Work (Start accepted on the digital pad) |
| Intro stage gameplay | Starts; walk/jump verified headless via the debug server |
| Attract-mode soak | 15 min / 112k frames / 23.5M dispatch hits, **0 misses** (ISSUES #8) |
| Streamed overlays (`OVL/*.BIN`) | Captured at 0x801D8000; compiled to native shards **during play** and hot-loaded (6 runs / 0 failures / 3→12 shards in one session, verified) |
| Controller | Digital pad, locked (`lock_mode`) — MM8 ignores analog pads, verified |
| Audio / CD-DA | Works (user-confirmed: SPU/XA mix + CD-DA tracks) |
| Memory-card save / load | Works (user-confirmed end-to-end) |
| Renderers | OpenGL default; Software available; Vulkan builds as a stub without `glslc` |
| Widescreen | **Opt-in 16:9 launcher toggle** (Mods page, default off) — native-wide 426x240, full-width background, HUD anchored to the wide edge (ISSUES #14) |
| Video filters | Scale2x/3x, 2xSaI / Super 2xSaI / Super Eagle, xBR 2x–4x, sharp bilinear, scanlines, CRT — launcher Display → Video filter, ESC menu → VIDEO FILTER, `[video] filter`; GL shaders verified against the CPU reference (ISSUES #15) |
| Bug reports | **F9** writes a telemetry bundle (screenshots + reloadable savestate + report.json) to `saves/bugreports/` (ISSUES #17) |
| Headless / scripted runs | `tools/mm8_headless.sh` — no window, seconds long, drives the debug-server vocabulary from a script (ISSUES #18) |
| Mods catalog | Game-owned widescreen + developer stage-select packages, plus the framework's loading mods |

## Setup

### Building From Source (Linux)

Requirements:

- GCC or Clang, CMake ≥ 3.20, Ninja, pkg-config, Python 3, OpenGL dev files.
  SDL3 dev headers are optional — the framework fetches a pinned SDL 3.4.x if
  no system package is found (`-DPSX_SDL_BACKEND=SDL2` is the offline fallback).
- Mega Man 8 (USA, SLUS-00453) disc image as a **multi-track** `.cue` + 3
  `.bin` (Redump). Not included. Verify it against `DISC.md`. Do **not** convert
  it to a cooked `.iso` — that drops the XA movie sectors and both CD-DA tracks.
- Optional: Sony SCPH1001 BIOS ROM (`SCPH1001.BIN`). Without it the bundled
  OpenBIOS is used.

This checkout keeps its local assets under `game-assets/` (gitignored):

```text
game-assets/Mega Man 8 (USA)/Mega Man 8 (USA).cue   (+ 3 .bin tracks)
game-assets/psx-bios-SCPH1001/scph1001.bin
```

Then:

```sh
git submodule update --init --recursive          # psxrecomp + recomp-ui from the carlosbravoa forks, branch mm8
bash psxrecomp/tools/ci/build_emitters.sh        # psxrecomp-game + psxrecomp-bios → build-recompiler/
bash tools/regen.sh                              # BIOS backends + generated/SLUS_004.53_*.c
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --target psx-runtime -j"$(nproc)"   # also builds build-release/psx-disc-tree
bash tools/run_mm8.sh                            # or: build-release/MegaMan8_Recompiled --game game.toml --disc "<cue>" [--bios <BIN>]
```

The framework submodules are pinned to branch `mm8` of the
`carlosbravoa/psxrecomp` and `carlosbravoa/recomp-ui` forks: upstream
`mstan/*` plus the fixes this title needs that are not merged upstream yet
(depth24 movie fix, bg2d startcol, POSIX autocompile, video filters, bug-report
bundles, headless scripts, extracted disc trees — see `upstream/README.md`).
`git submodule update` gives you exactly that state; nothing to patch.

### Running from extracted files (no disc image needed after this)

```sh
bash tools/extract_disc.sh       # dump → game-assets/disc/ (~2 s), then proves it byte-identical
bash tools/run_mm8.sh            # mounts game-assets/disc/ instead of the .cue
```

`game-assets/disc/cdrom/` holds every disc file as a plain file, `audio/` the
two CD-DA tracks as WAV. Edit, replace or add files there and the game serves
them (`psxrecomp/docs/DISC_TREE.md`); `python3 psxrecomp/tools/disc_tree.py
status game-assets/disc` shows what you changed, `bash tools/extract_disc.sh
--force` restores the pristine tree, `MM8_USE_IMAGE=1 bash tools/run_mm8.sh`
runs from the .cue again. Needs Python ≥ 3.11 (`tomllib`).

### Customizing media (videos, music, sound, graphics)

Everything is a file under `game-assets/disc/`; the runtime serves what is
there and rewrites the game's file table when a file grew. Details, formats and
tool names: `docs/ASSETS.md`. What is pending: `ROADMAP.md`.

| I want to change… | Do this |
|---|---|
| **CD music** (2 tracks) | Overwrite `audio/track02.wav` / `track03.wav` with any PCM WAV (44.1 kHz/16-bit/stereo served as-is, other formats converted at mount; the track length follows the file). |
| **A cutscene** (`cdrom/MOVIE/ROCK8_0..4.STR`, `CAPCOM15.STR`) | Same movie, new pictures/sound: jPSXdec → *replace frames* / *replace XA* on the loose `.STR` (keeps timing and length). Different movie: encode STR v2 320×240 ~15 fps with XA stereo 37.8 kHz on file 1/channel 1 (`psxavenc -t str2` or MOVCONV), copy over the original path. Check with `python3 tools/str_info.py <file.STR>` ("OK for Mega Man 8"). Longer files are fine (relocated automatically). |
| **Sequenced music / sound effects** (`cdrom/SOUND/PBGMxx.PAC`, `PCOMMON.PAC`) | `python3 tools/pac_tool.py unpack <PAC> <dir>` → edit the PsyQ `SEQ` (song), `VAB` header (`VH`) / body (`VB`) with vgmtrans / PSound / MIDI→SEQ / `psxavenc -t vag` → `pac_tool.py pack <dir> <PAC>` back to the same path. |
| **Graphics** (`cdrom/STDATA/*.PAC`) | `python3 tools/pac_gfx.py extract <PAC> <dir>` → indexed PNGs of the sprite/tile pages, `palette_block.png`, `tiles <PAC> <dir>` → every tile in its own colours, `map` → whole stage layers as PNG. Edit `palette_block.png` / `tiles.png` / the indexed PNGs, then `pac_gfx.py pack <dir> <PAC> [--from-tiles]` writes the PAC back (byte-identical when untouched). Mega Man's own palette: `PLAYER.PAC` with `--palette-type 2`, CLUT 0 = entries 0–15; his sprites: `pac_gfx.py sprites PLAYER.PAC <dir> --stage STAGE00.PAC` (131 frame strips + 302 assembled poses). Details: `docs/GRAPHICS.md`. |
| **HD textures** (upscaled / redrawn art at draw time, both renderers) | Dump what the game draws (`{"cmd":"texture_dump","op":"arm","dir":D}` on the debug build, or `PSX_TEXTURE_DUMP=D`; end with `op":"stats"` so `pairs.tsv` is written), `python3 psxrecomp/tools/texpack.py starter D game-assets/textures/pack --scale 2`, repaint the PNGs (keep the `.clut` sidecars: they let palette fades / flashes dim your art like the original), set Display → Supersampling ≥ 2 and tick **HD textures** in the launcher. `{"cmd":"texture_pack","op":"stats"}` / `"usage"` tell you which files were actually drawn. `psxrecomp/docs/TEXTURE_PACKS.md`. |
| **Anything else** | Any file under `cdrom/`, or new files/directories, are served; overlays/EXE are code (use the recompiler / mods). |

Always available: `build-release/psx-disc-tree layout game-assets/disc --game-toml
game.toml` (what will be served, relocations, table patches), `psx-disc-tree
verify … "<cue>"` (pristine proof), `psx-disc-tree build … out.cue` (bin/cue of
your modded tree for an emulator), `bash tools/mm8_headless.sh` (windowless
screenshot checks).

`tools/regen.sh` wraps `python3 psxrecomp/psxrecomp_cli.py generate --config
game.toml --project-root . --disc "<cue>" [--bios <BIN>]`. For a debug build with
the TCP debug server (port 4545) use `-B build-debug -DCMAKE_BUILD_TYPE=RelWithDebInfo`
and `tools/run_mm8.sh --debug`.

### Setup-host release

`.github/workflows/release.yml` (from the framework template) builds a
setup-host zip per platform (`mm8-<version>-<platform>.zip`) that contains the
launcher, the framework and this repo's sources but **no** generated game C,
disc data or BIOS. Players run Generate once from their own disc.

## Help make your game faster — just by playing

Most of Mega Man 8's code is recompiled ahead of time from the boot EXE, but the
game streams per-stage code from `OVL/DEMO.BIN` and `OVL/STAGE00..0D.BIN` at
runtime. Those overlays cannot be recompiled until they have been seen. While
you play, the runtime records newly loaded overlays into
`build-release/overlay_captures.json`, compiles them to native shards **in the
background during the same session**, and hot-loads them — so a newly visited
area stops running interpreted within seconds rather than at the next launch.

That in-session path was Windows-only in the framework until
`upstream/0003-*.patch` made it portable; `tools/build_overlay_shards.sh` is
still available to pre-build a full cache offline.

**Do not post `overlay_captures.json` publicly** — it contains verbatim
snapshots of the game's code read from your disc.

## Controls

Keyboard defaults are the framework's (see `keybinds.ini` beside the exe once
it has been written): arrows = D-pad, X = Cross, Z = Square, S = Circle,
A = Triangle, Q/W = L1/R1, E/R = L2/R2, Enter = Start, Right Shift = Select,
Tab = turbo, Alt+Enter = fullscreen. SDL gamepads are supported.

## Memory Cards

Standard PS1 memory-card images (`.mcd` / `.mcr`) under `saves/`, compatible
with DuckStation, PCSX-Redux, Mednafen, ePSXe. Save/load is verified end-to-end.

## Reporting a bug

Press **F9** while playing (rebind with `config.ini` `[KeyMap] BugReport=`).
The runtime writes `saves/bugreports/<date>_hotkey/` with the frame on screen
(`frame.png`, `screen.png`), a savestate of that exact moment (`state.pst`),
and `report.json` (settings, renderer, video filter, frame counter, dispatch
misses, GPU/overlay/autocompile status). Attach the folder to your report —
`state.pst` lets the bug be reloaded on a debug build
(`{"cmd":"savestate","op":"load_path","path":".../state.pst"}` or
`tools/mm8_headless.sh`). Nothing in it is personal beyond file paths.

## Development Rules

- Use the real recompiled BIOS and real hardware simulation in PSXRecomp.
- No HLE BIOS shims, no stubs, no fake events, no hand-edited generated files.
- Framework changes go in `mstan/psxrecomp`, not here.
- Game binaries, generated code, memory cards, Ghidra databases, overlay
  captures and build outputs stay local.
- Prefer `tools/mm8_headless.sh` for verification; open the window only for
  renderer-specific (OpenGL/Vulkan) or visual bugs.

## Work in progress

- **Framework patches not yet upstream** (`upstream/`): depth24 FMV span fix,
  bg2d `sra` start-column form, portable overlay autocompile, video filters
  (+ the recomp-ui "Video filter" row), F9 bug-report bundles, headless session
  script. They are applied to the submodule working trees here and must be
  re-applied after `git submodule update` (see `upstream/README.md`).
- **Vulkan** builds as a stub without `glslc` and does not run the video filters.
- **GL frame interpolation** never swaps on Wayland/Mesa here (framework, ISSUES #16).
- **Widescreen** is experimental: background fill and HUD anchoring are in,
  stage-start reveal and some scrollers still need work (`docs/WIDESCREEN*.md`).
- **Symbols**: ~73 of 7,292 functions named; `docs/SYMBOLS.md` describes the
  evidence-only naming pipeline.
- **OpenBIOS** backend is linked but not exercised; **Windows** builds untested here.
- The ESC menu / launcher change the video filter live and persist it; the
  in-game recomp-ui overlay does not yet expose the row.

## Acknowledgements

- [Matthew Stan](https://github.com/mstan) — [PSXRecomp](https://github.com/mstan/psxrecomp)
  and [recomp-ui](https://github.com/mstan/recomp-ui), the framework and launcher this
  repository is built on, and the sibling Tomba / Mega Man X4–X6 recomps that
  charted the bring-up path.
- The [N64Recomp](https://github.com/N64Recomp/N64Recomp) project for the static
  recompilation model the whole family follows.
- [PCSX-Redux](https://github.com/grumpycoders/pcsx-redux) for OpenBIOS;
  [Beetle PSX](https://github.com/libretro/beetle-psx-libretro) as the framework's
  hardware oracle; the [psx-spx](https://psx-spx.consoledev.net/) documentation.
- Video-filter algorithms: Eric Johnston / Andrea Mazzoleni (Scale2x/EPX),
  Derek "Kreed" Liauw Kie Fa (2xSaI family), Hyllian (xBR, MIT), Timothy
  Lottes (public-domain CRT shader). Implementations here are independent;
  see `psxrecomp/THIRD_PARTY_ATTRIBUTION.md`.
- Jrickey ([gba-recomp](https://github.com/JRickey/gba-recomp)) for the
  screen-colour science reused by the framework's CRT/composite/Trinitron models.
- Capcom, for Mega Man 8. This project is not affiliated with or endorsed by
  Capcom; it contains none of the game's binaries or assets.

## License

No `LICENSE` file has been chosen for this repository yet; the sibling recomp
repos (TombaRecomp, MegaManX4Recomp, …) use PolyForm Noncommercial 1.0.0. Mega
Man 8 is copyright Capcom. This repository contains none of the game's original
binaries or assets.
