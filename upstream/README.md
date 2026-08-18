# Pending upstream (framework) changes — the `mm8` fork branches

Fixes that belong in **`mstan/psxrecomp`** / **`mstan/recomp-ui`**, not in
this game repo (per `CLAUDE.md`: "Codegen/runtime fixes belong in the
framework … prefer a class fix that the next title inherits").

They live as **real commits on fork branches**, and the game's submodules are
pinned to them:

| submodule | pinned to | = upstream + |
|---|---|---|
| `psxrecomp` | `carlosbravoa/psxrecomp` branch **`mm8`** (`070e058`) | `mstan/psxrecomp` `dca482e` + 9 commits (§1–8 below; `478cc09` scheduler lost-return recovery + host-menu input isolation, `070e058` §8) |
| `recomp-ui` | `carlosbravoa/recomp-ui` branch **`mm8`** (`4ee44bd`) | `mstan/recomp-ui` `1b91c14` + 1 commit (§ui-1) |

So `git submodule update --init --recursive` reproduces the exact framework
state this title is developed and tested against; there is nothing to apply.
(Until 2026-08-17 the same work was parked as `upstream/000N-*.patch` files —
they were diffed against successive working-tree states, did not apply cleanly
onto the bare pin, and a `git submodule update` silently discarded the
uncommitted submodule tree. The fork replaces that.)

Commits on `psxrecomp/mm8` (oldest first): `ace0c3a` gpu depth24 span (§1),
`c3294e0` bg2d unmasked sra (§2), `b293249` portable autocompile (§3),
`b4cb44b` video filters + bug reports + headless scripts (§4–6),
`0d2228d`→`2276657` disc trees (§7), `53d1ad8` vram_upload_log (§5), `e585beb` compact ESC scanline row (§4). `recomp-ui/mm8`: `4ee44bd` video filter row.

## Workflow

Inside each submodule `origin` = your fork (fetch https, push ssh), `upstream`
= mstan.

```sh
# hack in psxrecomp/ on branch mm8, commit, push, re-pin:
git -C psxrecomp commit -am "..." && git -C psxrecomp push origin mm8
git add psxrecomp && git commit -m "psxrecomp: bump mm8 pin (...)"

# follow upstream:
git -C psxrecomp fetch upstream
git -C psxrecomp rebase upstream/master          # resolve, rebuild, test
git -C psxrecomp push --force-with-lease origin mm8
git add psxrecomp && git commit -m "psxrecomp: rebase mm8 onto upstream <sha>"

# open PRs to mstan: one branch per commit, cherry-picked off upstream/master
git -C psxrecomp switch -c fix/depth24-span upstream/master
git -C psxrecomp cherry-pick ace0c3a && git -C psxrecomp push origin fix/depth24-span
~/tools/gh pr create -R mstan/psxrecomp --head carlosbravoa:fix/depth24-span --body-file upstream/pr/0001-body.md
```

`upstream/pr/*.md` are ready PR bodies for §1–3; `upstream/pr/open_prs.sh`
predates the fork branch (it forked + pushed patch files) — use the
cherry-pick flow above instead. Rebuild the emitters after touching the
recompiler (§2), and re-run `tools/regen.sh`.

The sibling `../psxrecomp` checkout mentioned in `CLAUDE.md` is NOT the
submodule; point it at the fork too (`git remote add fork
git@github.com:carlosbravoa/psxrecomp.git && git fetch fork && git checkout
mm8`) or it drifts.

Per-fix write-ups follow (the PR material).

---

## 1 — depth24 upload span must intersect the scanout band

**Files:** `runtime/src/gpu.c`, `runtime/src/debug_server.c`
**Class fix:** yes — affects any title whose 24-bit movie path uploads
framebuffer-class rectangles outside the display band.

### Symptom

Mega Man 8's intro FMV rendered only its **left ~53%**, horizontally
magnified, with the right side black. Reproduced on both the OpenGL and
software present paths, so it was never a renderer bug.

### Root cause

`depth24_note_upload()` tracked how far right the movie had been written, so
`depth24_fix_trailing_margin()` could black out trailing columns that MDEC had
not covered yet (a MotK/Star-Wars-crawl fix). It accepted **any** CPU→VRAM
upload ≥ 256 halfwords wide as evidence of coverage, without checking *where in
VRAM it landed*.

MM8 breaks that assumption two ways at once:

- as the 24-bit intro starts it stages two `256×8` blits at **y=480** — far
  outside the CRTC scanout band (`display_y` 0 or 240, 240 lines tall);
- it then streams each movie frame as **24-halfword (16-pixel) macroblock
  strips**, which never reach the 256-halfword width guard at all.

So the tracked span latched at 256 halfwords → `(256 * 2) / 3` = **170 RGB
pixels**, and every present blanked columns 170..319 of a 320-wide movie.

### Fix

Require the upload to intersect the CRTC display band in **both** axes before
it grows the span. With no on-band framebuffer-class upload the span stays `0`,
which `gpu_depth24_rgb_limit()` already defines as "unknown" and the presenters
already treat as "apply the default 8-column margin only" — the correct
behaviour for a title that never does a full-width blit.

The `y` and `h` of the transfer were not previously passed to
`depth24_note_upload()`; the patch threads them through from
`gp0_commit_cpu_to_vram()`.

### Verification

The patch also exposes the tracked value as `d24_rgb_limit` in the
`gpu_state` debug command — the observability that made this diagnosable at
all. Measured during the MM8 intro on the debug build:

| Build | `gpu_state.d24_rgb_limit` | Result |
|---|---|---|
| `dca482e` stock | **170** | movie cropped to left 53% |
| with this patch | **0** | full-width movie, correct |

Regression risk: MotK (the title the original margin logic was written for)
does a genuine full-width on-band blit, so its span is unchanged and its
trailing-junk fix still engages. That claim is **reasoned, not tested** — no
MotK dump is available here. Worth stating in the PR.

---

## 2 — `[widescreen.bg2d] startcol_site` should accept an unmasked `sra`

**File:** `recompiler/src/code_generator.cpp`
**Class fix:** yes — applies to any 2D title whose background renderer indexes
its tile map directly instead of through a power-of-two ring.

### Problem

`startcol_site` accepted only `andi rt,rs,imm` and hard-failed otherwise:

```
ERROR: [widescreen.bg2d] startcol_site 0x... is not andi (opcode 0x..)
```

That assumes the X4/X5/X6 shape, where the start tile column is masked into a
32- or 64-column ring. A renderer that reads its tile map **directly** has no
ring and therefore no mask — it derives the start column by arithmetic-shifting
the scroll value. Mega Man 8's `func_800F98D8` does exactly that:

```mips
800F993C: sra $v0, $v0, 20     ; start column = (s16)scroll >> 4, unmasked
800F9940: sh  $v0, 4($s0)
```

With no way to hook it, only the column *count* could be widened, so the
background grew rightward and left the left reveal black.

### Fix

Accept the `sra rd,rt,sa` form too and pass an all-ones mask, so
`psx_ws_bg2d_startcol()` subtracts the reveal without wrapping. Mirrors the way
`startx_site` already accepts two instruction forms (`sra` and `subu rd,zero,rt`).
Identity at 4:3 like every other bg2d hook, and the error message now names both
accepted forms.

### Verification

Mega Man 8, native-wide 16:9 (426x240), measured black margins on a live frame:

| | before | after |
|---|---|---|
| mid-stage | L=53 R=37 | **L=0 R=0** (full 426 px of background) |
| at the stage's left boundary | L=53 R=37 | L=53 R=0 |

The residual 53 px at a stage boundary is correct, not a defect: the camera
clamps there, so no map exists further left.

Note for adopters: `psx_ws_bg2d_*` helpers call `mmx6_bg_refill_tick()`, and
`g_mmx6_freshfix` **defaults to 1**. A title without an MMX6-style ring must
call `gpu_ws_mmx6_set_freshfix(0)` (Mega Man 8 does so in its widescreen mod
plugin), otherwise the refill writes through the framework's default layer/ring
addresses — arbitrary RAM in that title.

---

## 3 — portable overlay autocompile: POSIX spawner + one shared pipeline

**Files:** `runtime/src/autocompile.c`, `runtime/CMakeLists.txt`,
`runtime/tests/test_autocompile_publication.c`,
`runtime/tests/test_autocompile_degraded.c`
**Class fix:** yes — affects every psxrecomp title on Linux and macOS.

### Problem

The runtime can compile freshly captured overlays to native shards in the
background *during play* and hot-load them (`overlay_autocompile_cmd`). All of
it was `#ifdef _WIN32`: `autocompile_request()` ended in
`return 0;  /* non-Windows hosts: manual compile flow only */`, and
`autocompile_report_broken_once()` was an empty stub.

Consequence on Linux: newly visited areas stayed in the dirty-RAM interpreter
for the rest of the session, and forever unless the developer knew to run an
offline shard build by hand. Two smaller casualties travelled with it —
`autocompile_now_ms()` returned a constant `0`, so the failure backoff never
advanced off-Windows, and both autocompile tests were `if(WIN32)`-gated, so no
CI on any other host covered this file at all.

### Fix

Not a second implementation. The Windows path was never *just* a spawner — it
carries the publication pipeline (off-thread prepare worker, depth-one
backpressure, main-thread commit, shutdown reference conservation), and
duplicating ~450 lines of that for POSIX would guarantee the two drift.

Instead the file gained a **thin platform-primitive layer** — mutex, condvar,
thread, sleep, monotonic clock, and an `ac_proc_t` child-process handle — and
everything above it is now compiled once for both platforms. On Windows each
primitive expands to exactly the call the code made inline before, so that path
is unchanged by construction; reviewing the Windows side means checking the
expansions rather than re-reading the pipeline.

Platform specifics of the spawn:

| | Windows | POSIX |
|---|---|---|
| shell | `cmd.exe /C` | `/bin/sh -c` (what the config format documents) |
| priority | `BELOW_NORMAL_PRIORITY_CLASS` | `nice(10)` |
| tree teardown | kill-on-close **job object** | child leads its own **process group**, one `killpg()` |
| crash orphans | job object | `PR_SET_PDEATHSIG` on Linux |

The process-group + pdeathsig pair is the closest POSIX equivalent to a job
object. It is honestly weaker for the shell-builtin/pipeline forms of the
command: `sh -c` execs a simple command in place, so in the normal
configuration the death signal lands on python itself, but a command that keeps
a shell alive would leave the shell — not its children — holding the signal.
Getting job-object parity would need a supervisor process, which is not worth
it here.

Also fixed in passing: `s_state`/`s_exit_code` are now atomic on **both**
platforms (they are written by worker threads and read by the emulation
thread — Windows used interlocked ops, POSIX had them as plain `int`), and the
retry backoff has a real monotonic clock everywhere.

Both previously Windows-only tests are now portable and registered on every
host, which is the real regression guard for this file.

### Verification

Measured on Linux, Mega Man 8, debug build, live play session:

| | before | after |
|---|---|---|
| `autocompile_status.compile.configured` | 1 | 1 |
| compile runs spawned | **0** (hard `return 0`) | **6** |
| failures / `last_exit` | n/a | **0 / 0** |
| shards on disk during one session | 3 (all offline-built) | **3 → 12, compiled in-session** |
| `overlay_loader_status.registered` | — | 32, `last_msg` = `loaded …/001D8000_1A49860E.so` |
| dispatch misses | 0 | 0 |

Teardown, both paths checked:

* clean shutdown — the child `sh` is confirmed in its own process group
  (`PGID == its own pid`), and after quit no `compile_overlays.py`, `cc1` or
  `python3` descendant survives;
* **crash** (`SIGKILL` the runtime, so `autocompile_shutdown()` never runs) —
  also no survivors, i.e. `PR_SET_PDEATHSIG` covers the case the job object
  covers on Windows.

Tests:

* `autocompile_publication_test` — **passes on Linux under ThreadSanitizer with
  no data races**. It is the strong result: it pins off-thread prepare,
  backpressure at one mapped image, commit on the emulation thread, and
  reference conservation across a mid-run shutdown — the whole pipeline now
  running on pthreads.
* `autocompile_degraded_test` — passes under ASan+UBSan. Its hardcoded
  `py -3` interpreter had to become `/bin/sh` off-Windows: the test asserts that
  a missing `--recompiler` is the *first* recorded cause, and on Linux an
  unresolvable `py` was legitimately being reported first instead.

**Not verified: Windows.** No Windows host or cross-toolchain was available
here. The Windows arms are unchanged in behaviour by construction, but they
have not been compiled or run — say so in the PR and let CI be the judge.

Note for adopters: with this landed, `[runtime] overlay_autocompile_cmd` is
worth setting on Linux game configs. Mega Man 8 now ships one (see its
`game.toml`); `--captures`/`--out-dir` are deliberately omitted from the command
because the runtime injects `PSX_OVERLAY_CAPTURES` / `PSX_OVERLAY_CACHE_DIR`,
which `compile_overlays.py` prefers.

---

## 4 — present-time video filters (framework) + `recomp-ui` "Video filter" row

**Files (psxrecomp):** `runtime/include/video_filter.h`, `runtime/src/video_filter.c`,
`runtime/src/gpu_gl_filter_shaders.h`, `runtime/src/gpu_gl_renderer.c`,
`runtime/include/gpu_gl_renderer.h`, `runtime/src/main.cpp`,
`runtime/src/debug_server.c`, `runtime/include/mod_plugins.h`,
`recompiler/src/config_loader.{h,cpp}`, `runtime/runtime.cmake`,
`runtime/CMakeLists.txt`, `runtime/tests/test_video_filter.c`,
`docs/VIDEO_FILTERS.md`, `THIRD_PARTY_ATTRIBUTION.md`.
**Files (recomp-ui):** `src/recomp_launcher.h`, `src/common/launcher_model.{h,c}`,
`src/common/backends/imgui/launcher_imgui.cpp`.
**Class feature:** yes — every psxrecomp title gets the launcher row and the
`[video] filter` key.

(§4, §5 and §6 are one commit on `mm8`, `b4cb44b`, because their `main.cpp` /
`debug_server.c` / `runtime.cmake` edits were made in one working tree; split
by file when cherry-picking for PRs.) Historical note from the patch era: the
`main.cpp` hunks in patch 4 were taken from a working
tree that also carried earlier uncommitted savestate/menu edits from previous
sessions (they are not part of patches 1–3 either); the video-filter hunks are the
ones touching `g_video_filter`, `video_filter_*`, `sdl_filter_*`,
`psx_present_*` and `RECOMP_LAUNCHER_HAS_VIDEO_FILTER`.

### What it does

Opt-in, presentation-only filters between the finished frame and the window:
Scale2x/3x, 2xSaI / Super 2xSaI / Super Eagle, xBR 2x/3x/4x, sharp-bilinear,
scanlines, a Lottes-style CRT look. `none` (default) is byte-identical to before.
CPU reference (`video_filter.c`, also the software present) + GLSL twins on the
OpenGL present (VRAM / wide / hold / FMV CPU-readout / interpolation paths).
Selection: launcher row, `[video] filter`, `settings.toml`, `PSX_VIDEO_FILTER`,
`psx_mod_set_video_filter()`, debug `video_filter`. See `docs/VIDEO_FILTERS.md`.

### Verification

* `video_filter_test` (ASan/UBSan clean): names, sizes, flat-field fixed point,
  EPX corner rules, edge-blend locality, xBR transpose symmetry, thin lines.
* Mega Man 8, GL, `tools/video_filter_check.py`: for all eight upscalers the
  presented drawable at an exact integer window equals the CPU reference of the
  same source to ≤1 LSB (Scale2x/3x identical), on the title screen, the intro
  FMV (24-bit CPU-readout path) and intro-stage gameplay.
* Software renderer: xbr2x / 2xsai / crt captured through `present_capture`.
* Launcher: `LNG_SCRIPT` run cycles the row and PLAY persists
  `filter = "xbr4x"` to `settings.toml`; the runtime boots with it.
* Not exercised: Vulkan (unfiltered by design), the GL frame-interpolation
  thread (on this Wayland/Mesa box that thread never swaps even without the
  filter — pre-existing, see the game repo's ISSUES.md).

---

## 5 — bug-report bundles (F9 / `bug_report`): one-key telemetry

**Files:** `runtime/include/bug_report.h`, `runtime/src/bug_report.c`,
`runtime/src/host_keymap.{c,h}` (BugReport action, default F9),
`runtime/src/savestate.c` + `.h` (`savestate_request_save_path`),
`runtime/src/debug_server.c` + `.h` (`debug_server_run_local`, `bug_report`,
`savestate op=save_path|load_path`, `present_capture companions`),
`runtime/src/main.cpp` (hotkey, notify hook, `psx_host_report_json`),
`runtime/runtime.cmake`, `docs/BUG_REPORT.md`.
NOTE: the main.cpp / debug_server.c / gpu_gl_renderer.c hunks of this feature
are inside patch 0004's diff of those files (same working tree); patch 0005
holds only the new/other files. Regenerate both from the tree when landing.

Verified once on Mega Man 8 (debug build): `{"cmd":"bug_report"}` produced
frame.png, frame_hires.png, screen.png, state.pst, report.json (all 13 queries
answered), README.txt; `savestate op=load_path` reloaded the bundle's state.

---

## 6 — headless session script (`--script`, `PSX_SCRIPT`)

**Files:** `runtime/include/psx_script.h`, `runtime/src/psx_script.c`,
`docs/HEADLESS.md` (+ `main.cpp` / `runtime.cmake` hunks inside patch 0004's
diff of those files: CLI/env parsing, `psx_script_poll()` at the vblank safe
point, production input-override, `psx_frontend_request_quit`,
`headless_capture_present`). Class feature: every title gets a windowless,
unpaced, scriptable run for CI/bug-repro; steps are debug-server command lines
plus wait/expect/quit. Verified on Mega Man 8 (release build): load slot →
screenshot → filtered present capture → bug_report bundle → exit 0, ~5 s.

2026-08-17 additions folded into patch 4's files: CRT one-line flicker fix
(`fetch_px` reciprocal-multiply floor), parametric scanlines (opacity/size/glow:
`VideoScanlineParams`, ESC rows, `[video] scanline_*`, debug `video_filter`
scan_* fields), and `debug_server_shutdown()` `shutdown(SHUT_RDWR)` before
`close()` so the I/O thread's `accept()` wakes — every windowed quit on a Linux
debug build used to hang in `SDL_WaitThread`.
Follow-up: the three ESC scanline rows overflowed the 12-row panel (QUIT was
cut off) — collapsed into one `[DARK 60%] SIZE 35% GLOW 50%` row shown only
while the scanlines filter is active (LEFT/RIGHT adjust, ENTER cycles the
bracket), and `psx_savestate_menu.c` now shrinks the row pitch to fit whatever
row count it is handed (max 16) instead of dropping rows.

---

## 7 — disc trees: run from extracted files (`docs/DISC_TREE.md`)

**Files:** `runtime/include/disc_tree.h`, `runtime/src/disc_tree.cpp` (new
engine), `runtime/include/iso_reader.h` + `runtime/src/iso_reader.cpp`
(`ISOReader::Open()` accepts a tree directory; `SetDiscTreeHints`,
`LastDiscTreeMount`), `runtime/src/disc_identity.cpp` (identify trees like
CHDs — through the reader; also applies the netplay gate on that branch),
`runtime/src/disc_path.cpp` (a tree resolves as "from cue"), `runtime/src/main.cpp`
(`[disc_tree]` selection + `PSX_DISC_TREE`, hints, layout log, guard blessing),
`recompiler/src/config_loader.{h,cpp}` (`[disc_tree] dir`, `[[disc_tree.lba_table]]`),
`runtime/runtime.cmake` (source + `psx-disc-tree` tool target; also stamps
`psx_game_version.txt` once per build tree so `BUILD_TESTING` configures on
Ninja), `runtime/CMakeLists.txt` (tests), `runtime/tools/disc_tree_cli.cpp`,
`tools/disc_tree.py`, `runtime/tests/test_disc_tree.cpp`, `docs/DISC_TREE.md`,
`docs/config_schema.md`.
**Class feature:** yes — any title can run from an extracted directory.

### What it does

`tools/disc_tree.py extract` unpacks a MODE2/2352 bin/cue into a directory
(`cdrom/` files — Form 1 cooked, Form 2/XA/STR raw 2336 B/sector —,
`audio/trackNN.wav`, `meta/` licence area + PVD + odd raw runs, `disc.toml`).
The runtime mounts that directory as the disc: descriptors, path tables and
directory records are rebuilt from the manifest, Form 1 sectors get
subheader + EDC + ECC, raw and audio sectors are served verbatim. Pristine
tree ⇒ byte-identical disc; edited/added files ⇒ served in place, grown files
relocated after the original data area with the title's hardcoded LBA table
rewritten in the served EXE (`[[disc_tree.lba_table]]`), and the rewritten
bytes blessed into the text-image guard.

### Verification

* `psx-disc-tree verify game-assets/disc "<MM8 dump>.cue"`: **IDENTICAL,
  177,992 sectors** (all three tracks, licence area, ECC, pregaps) in 0.8 s.
* `disc_tree_test` (new): EDC vectors + P/Q fingerprint, synthetic tree
  round-trip walked back through the reader's ISO9660 parser, relocation of a
  grown file + new dir/file + CD-DA alias + LBA-table patch and RamPatches.
  `iso_reader_cdda_test`, `disc_path_resolve_test`, `mod_runtime_test`,
  `mod_packages_test` still pass.
* Mega Man 8 headless from the tree with the dump directory moved away: cold
  boot → Capcom logo → intro FMV (STR + XA from raw storage) → title, 0
  dispatch misses. Modified tree (STAGE00.BIN +4 KB → LBA 142096, table entry
  9 rewritten): title → GAME START → intro stage running, RAM 0x801D8000 holds
  the overlay header, 0 misses. Added dir/file + 22 kHz mono WAV replacing
  track 3: layout/build/ISO listing/path table all correct.
* Not exercised: Windows build (std::filesystem/ifstream only, nothing
  platform-specific), CHD sources for extraction (the extractor needs a raw
  bin/cue; the runtime can still mount a CHD as before).

## 8 — native-wide anchor, 2D screen-edge bounds, headless widescreen, build-agnostic savestates

Four related framework changes from the Mega Man 8 widescreen work
(2026-08-18; `docs/config_schema.md`, `docs/HEADLESS.md`, `docs/BOOKMARKS.md`).

* **`[widescreen] nw_anchor = "center"|"left"|"right"`** — how the native-wide
  EXTRA width splits between the sides. A 2D side-scroller authored against the
  4:3 left edge (camera clamps, player walls, spawn windows, stage-start
  positions) keeps every left-side alignment with `"left"` and reveals the
  whole width on the right; the centred split needed a camera-inset hack that
  fell over at every map boundary. Plumbed through the compositor
  (`gr_wide_configure(wide_w, left_offset, native_w)` — the renderers no longer
  assume `native_w = wide_w - 2*offset`; SW/GL/VK), the draw-area widen, the
  cull helpers (`psx_ws_cull_*` per side; overlay preamble too, ABI v22 adds
  `ws_x_margin_left/right` callbacks), `[widescreen.bg2d]` (left/right column
  counts), HUD corner re-anchoring, fullscreen-rect / backdrop stretch, and the
  mod API (`psx_mod_widescreen_x_margin_left/right`). `psx_ws_x_margin()`
  keeps its symmetric per-side meaning, so every existing (centred / 3D) title
  is byte-identical. `nw_anchor_gate = "bg2d"` applies the anchor only on
  frames the bg2d tile renderer built (menus / loading screens drawn as fixed
  4:3 layouts stay centred; the flip is re-derived before every draw command),
  and `psx_mod_widescreen_set_world()` lets a plugin veto it for screens it
  knows are not the world. `gpu_state.ws` reports the split.
* **`[[widescreen.cull.edge]]`** — full-word-guarded `ADDI/ADDIU/SUBU` sites
  for a 2D title's camX-relative keep-alive / on-screen / spawn bounds that
  carry the 4:3 width as immediates; `side = left|right|width` moves them by
  the per-side reveal (identity at 4:3). Codegen + overlay shards + the
  dirty-RAM interpreter share the arithmetic; part of the overlay cache
  identity. Without it a widened spawn window spawned enemies the game's own
  keep-alive killed on the same frame (measured with `wtrace`).
* **Headless widescreen** — the game-entry engage step now runs before the
  headless early-out and `headless_capture_present` renders the wide
  compositor surface, so `[widescreen]` work is verifiable with a script
  (`present_capture` = the wide frame). Previously a headless run always
  reported `mode 0`, indistinguishable from a broken config.
* **`BOOT_STATE_ANY_BUILD`** — user savestate slots and bookmarks accept a
  differing build key (codegen hash / overlay ABI / codegen version): the image
  is a complete hardware snapshot and host-side state is re-derived from guest
  RAM (as `boot_state.h` already documents), so a recompiler rebuild no longer
  orphans every save the player has taken. The fast-boot snapshot, rewind ring
  and netplay pins keep the strict key; BIOS checksum and entry PC are always
  required. Surfaced by this very change: the emitter edit bumped the hash and
  every existing bookmark refused to load.

### Verification (Mega Man 8, headless)

Left 320 columns of the left-anchored wide frame pixel-identical to the 4:3
frame at the intro stage start; five stage starts show authored map across
426 px; pause menu / title / stage select / NOW LOADING centred with the flip on
the black wipe frame (captured every 3–5 frames both ways); actor telemetry:
spawns at `dx_cam 462–469` vs 4:3 `355–367`, despawns `448–460` vs `331–343`,
no per-frame spawn/kill flicker; mod off: every margin 0, 320×240. Recompiler
unit tests (`recompiler_patch_test`, `full_function_emitter_test`,
`video_enhancement_settings_test`, `l2_structural_test`) pass; the
source-grep launcher tests (`launcher_vulkan_option`, `mod_load_acceleration`)
already failed at the previous pin (unrelated strings).
