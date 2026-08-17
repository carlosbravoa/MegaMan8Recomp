# MegaMan8Recomp — Issues

Current state (2026-08-15, bring-up day 1, framework `psxrecomp` @ dca482e +
local gpu.c fix, see #6): the game **boots and plays** on the first generated build — Capcom logo + intro
FMV (MDEC/XA) decode, the title screen and main menu respond to Start, GAME
START loads the intro stage overlay and Mega Man walks/jumps under (digital)
pad input — with **zero dispatch misses** on that path (7.4 M static dispatch
hits, `miss_total = 0` after ~32 k frames headless). Verified over the TCP
debug server (`build-debug/`, port 4545): `screenshot`, `dispatch_stats`,
`unknown_dispatch_log`, `dirty_ram_stats`, `overlay_loader_status`.

---

## #8 — 15-minute attract soak: zero dispatch misses — PASSED

2026-08-15. Left the attract loop cycling (intro FMV → title → stage demo →
FMV …) on the debug build for 15 minutes: **112,182 frames, 23.5 M static
dispatch hits, `miss_total = 0` throughout.** Overlay coverage grew from 2
regions to **5** (`0x801D8000`, `0x801DC000`, `0x801E0000`, `0x801E4000`,
`0x801E8000`) as the demos exercised code the intro stage never touched.
`tools/build_overlay_shards.sh` then compiled them (6 `.so` shards, 0 failures)
and after `overlay_rescan` the loader registered 12 entries with
`dispatch_native` at 9.7 M — the demo code now runs native rather than
interpreted.

This is the cheapest broad-coverage tool available and needs no gameplay skill:
attract mode drives itself. It does NOT reach boss stages or Wily stages
(`OVL/STAGE00..0D.BIN`), which still need real play — see #4.

## #9 — The retail build still contains Capcom's debug menu, but it is unreachable — CLOSED (informational)

`DebugMainMenu` (`0x80134FA0`) and its driver (`0x80134E7C`) are fully linked,
including a 6-entry jump table at `0x800F76D8`
(MAINMENU / FLAGCHANGE / WORKVIEW / VABVIEW / POWERUP / PARTS) and pad handling
off `0x801B2960`. But the driver has **zero callers and zero data-word
references** anywhere in the image: Capcom cut the entry point and the linker
kept the code. There is no button combo that opens it — do not go looking for
one. (Forcing a jump to it would be a mod, not a test route.)

Its value is as documentation: the field printers decode Mega Man 8's actor
struct. See `docs/ACTOR_STRUCT.md`.

## #1 — Early bring-up: uncovered code regions halt loudly — OPEN (by design)

The recompiler emitted 7,292 functions from the boot EXE (1,862 found by scan,
5,275 more by the control-flow pre-pass), with 24 "out-of-function branch"
fallthrough warnings during emit (`generate.log`), mostly in the
`0x800DE7xx` run — inspect these in Ghidra; they may be a jump table the
walker classified as separate one-instruction functions. If gameplay reaches
code the recompiler classified as data, the program **fail-fasts with an
"unknown dispatch" report** rather than misbehaving silently. The covered path
(boot → logo/intro FMV → title → menu → intro stage) is clean. If you hit a
halt, note where you were and what you did; each report pins the exact address
the recompiler needs (`seeds/ghidra_funcs.txt`).

## #2 — Streamed OVL overlays run in the interpreter until sharded — RESOLVED

MM8 loads `OVL/DEMO.BIN` / `OVL/STAGE00..0D.BIN` at **0x801D8000** (just above
the text end 0x801D3000) and executes them there. The runtime's dirty-RAM
interpreter runs them correctly (`dirty_ram_stats` showed 62 overlay PCs in
0x801D80A8..0x801E0174 for the intro stage) and captures them into
`<exe dir>/overlay_captures.json`.

This used to need a manual offline step, because the framework's in-session
autocompile spawner was `#ifdef _WIN32` — on Linux it was a hard
`return 0`, so a newly visited area stayed interpreted for the whole session.

**Fixed in the framework** (`upstream/0003-*.patch`): `autocompile.c` gained a
platform-primitive layer, so the spawner *and* its publication pipeline are now
one shared implementation running on both hosts. `game.toml` sets
`overlay_autocompile_cmd` accordingly, and overlays are compiled and hot-loaded
**during play**.

Verified in a live session: 6 compile runs, 0 failures, `last_exit = 0`,
shards on disk growing 3 → 12 while playing, `overlay_loader_status.registered`
= 32 with `last_msg = loaded …/001D8000_1A49860E.so`, 0 dispatch misses.
Teardown checked on both paths — clean quit and `SIGKILL` — leaves no orphaned
`compile_overlays.py`/`cc1` process, because the child leads its own process
group and Linux additionally arms `PR_SET_PDEATHSIG`.

`tools/build_overlay_shards.sh` remains the offline bulk path (useful for
pre-building a full cache, e.g. the 14-stage tour); it is no longer required
for ordinary play.

## #16 — Widescreen corrupts geometry at a stage START — OPEN (root cause narrowed)

At the beginning of a stage the 16:9 frame renders as large black wedges (a
bowtie across the screen) with the stage visible only in the remaining
triangles. Reported by the player as "a big black bar on the left"; the left
run really is black, but the rest of the corruption is diagonal, which a
per-column darkness metric does not see (that cost real time — measure dark
pixel FRACTION, not contiguous dark columns).

**Isolated to widescreen.** Same build, same stage, same entry:

| | frame | dark pixels |
|---|---|---|
| widescreen OFF | 320x240 | **0%** — clean |
| widescreen ON  | 426x240 | **44-49%** — wedges |

Mid-stage 16:9 is clean (`black L=0 R=0` measured while scrolling), so this is
specific to the camera sitting at a stage's left boundary.

**Ruled out:**

* Not the camera-inset mod hooks — the wedges persist with the inset disabled
  entirely (probe build: hook returns immediately, corruption unchanged).
* Not `[widescreen.bg2d] startcol` going negative. That IS a real hazard for a
  direct-index title (an unmasked `startcol` has no ring to wrap into, so the
  expansion can index before the map), and a clamp was written and tested — it
  changed nothing here, so it was reverted rather than left in as an unproven
  framework change. Worth revisiting as correctness, not as this fix.

**Prime suspect:** `[widescreen.cull] auto_screen_x`. It widens MM8's own
screen-extent reject (`func_800FA050`, `slti v0,v0,320`) so primitives the game
would have discarded are now produced. At a stage start the parallax builder
(`func_800F90D4`) is working with layer state that is not fully initialised, so
the primitives it emits are plausibly degenerate — normally rejected, and now
drawn as large triangles. Next step: force `psx_ws_x_margin()` to 0 for the
cull sites only (`gpu_ws_set_margin_override(0)` exists as a live probe) and see
whether the wedges disappear while the reveal stays.

**Camera inset, separately:** the inset now runs, but is bounded by the stage's
authored travel. Stage 02 starts with `Xmin=256, Xmax=280` — 24 px against a
53 px reveal — so the camera cannot be inset the full margin and ~29 px of the
reveal still hangs off the map. Raising `Xmax` to make room was tried and
reverted: that bound also feeds the tile fetch, and lifting it walked the
background off the end of the map.

## #15 — Stage-select transition showed a black stage once — NOT REPRODUCED

Reported 2026-08-16: after the intro, selecting a stage gave a black screen with
only the health bar, Mega Man unable to move (no ground), and the **intro's
music still playing**. Rewinding (F8) to the loading screen and replaying the
same transition loaded the stage perfectly.

**Current status: cannot reproduce.** Manual play afterwards confirmed **all
stages load correctly**.

What the investigation did establish, so a recurrence is not re-litigated from
scratch:

* Not the overlay shard cache (`overlay_cache=false` changes nothing),
  not the in-session autocompile (`PSX_OVERLAY_AUTOCOMPILE_OFF=1` changes
  nothing), not the renderer (identical on OpenGL and software), not disc
  layout (all `OVL/*.BIN` are contiguous in track 1, LBA 126122–126558), and
  not a CD/DMA stall (`int1_lost: 0`, `schedule_late: 0`, no active channels).
* The stage table at `0x80137A5C` has exactly 14 entries (0–13 → asset ids
  `0x73`–`0x87`). Index **14 is Dr. Light's Lab**, reached through a different
  code path — *not* an out-of-bounds read, despite looking like one.
* The stage index lives at `0x801C336E` and is written by `func_800FFCFC` only
  when a destination is actually chosen. **Selecting with the cursor unmoved
  never writes it** — a harness trap that produced convincing false positives.

**Methodology note for the next attempt.** Automated navigation of this menu is
unreliable: verify a known-good selection renders its stage *before* trusting
any failure it produces, and classify frames by mean brightness — the
distinct-colour count reads ~150 on a visually black frame and will lie to you.

If it recurs, capture immediately: `gpu_state`, `overlay_loader_status`,
`dirty_ram_unsupported`, and a `vram_peek` grid, plus whether it was the first
stage entered after the intro.

## #3 — Controller: analog pad ignored → digital locked — RESOLVED

The launcher's default `settings.toml` wrote `p1_mode = "analog"`; MM8 (US Jan
1997, pre-DualShock) ignores every button from an analog pad (id 0x73):
verified on the debug build — 40+ START presses during title/attract were
ignored, while a digital pad (id 0x41) is accepted immediately (X4 finding,
same class). `game.toml` now sets `[controller] lock_mode = true` with
`default_mode = "digital"`: every port is forced digital regardless of
`settings.toml` and the launcher hides the pad-mode selector. Re-verified: with
the stale `p1_mode = "analog"` still in `settings.toml`, START reaches the
title screen.

## #6 — 24-bit FMV cropped to the left ~53% (framework bug) — FIXED LOCALLY, needs upstream

Symptom (windowed, GL or SW): the intro STR showed only its left half, magnified,
black on the right. Cause in `psxrecomp/runtime/src/gpu.c`
`depth24_note_upload()`: any CPU→VRAM upload ≥ 256 halfwords wide was counted
as movie coverage regardless of where in VRAM it landed. MM8 stages two
256×8 blits at y=480 (outside the scanout band) as the 24-bit intro starts,
then streams every movie frame as 24-halfword (16-px) macroblock strips that
never pass the width guard — so the tracked span stuck at 256 hw = 170 RGB
px and `depth24_fix_trailing_margin()` blanked columns 170..319. Fix: the
upload must also intersect the CRTC display band (columns and rows); with no
on-band FB-class upload the span stays 0 = "unknown" → default 8-column
margin only. Verified via the new `gpu_state.d24_rgb_limit` field (170 before,
0 after). The change lives in the `psxrecomp/` submodule working tree
(uncommitted). It is preserved as a tracked patch in **`upstream/`** — see
`upstream/README.md` for the full write-up, how to re-apply it after a
submodule reset, and how to land it upstream.

## #4 — Not yet verified — OPEN (narrowed)

- ~~Audio~~ **CONFIRMED WORKING** by the user, 2026-08-16 (SPU/XA mix + CD-DA
  tracks 02/03 on a real audible run).
- ~~Memory-card save/load~~ **CONFIRMED WORKING** end-to-end by the user,
  2026-08-16.
- Deeper stage coverage / boss stages / Wily stages (each loads a different
  `OVL/STAGEnn.BIN`) — new overlays each need a capture + shard pass. The
  attract soak (#8) covered 5 overlay regions; the stage set is untouched.
- OpenBIOS backend boot (`tools/run_mm8.sh --openbios`) — only the SCPH1001
  path was exercised.
- Windows / macOS builds and the setup-host CI zip.

## #10 — Player actor located and struct confirmed at runtime — DONE

`0x8015E23C` is Mega Man's actor record. Found by differential RAM scan (hold
Right → hold Left, keep records whose `pos_x` rises then falls and whose
pointer fields are plausible) — exactly one match across all 2 MB, and it is
the same global `DebugActorPointers` receives statically.

Causally confirmed: writing `12` over `life` at `+0x47` dropped the on-screen
health bar to ~30% (full HP = 40). Also verified live: `pos_x`/`pos_y` are
16.16 fixed, walk `speedx` = 1.50 px/frame, jump `speedy` = −0.25 with
`spedgy` = 0.25 gravity, `jmpflg` = 1 for exactly the airborne frames, and
`kabeat` = 128 the moment he stops against a wall. Full table in
`docs/ACTOR_STRUCT.md`.

Follow-up (same day) — the object arrays are now mapped and the ENEMY array is
confirmed causally; see #11. `+0x08` / `+0x2C` are still unnamed.

## #11 — Object arrays mapped; ENEMY array confirmed — DONE

The debug object viewer (`0x80135368`) indexes each category with inline
arithmetic, so bases and strides come from the code, not from guessing:

| Category | Base | Stride | Status |
|---|---|---|---|
| PLAYER | `0x8015E23C` | single record | confirmed live (#10) |
| ENEMY | `0x8015B174` | 0x60 (96) | **confirmed live** |
| SET | `0x801B1EEC` | 0x50 (80) | from code; empty in the intro stage |
| MSET / CTRL | `0x801CF848` | 0x40 (64) | from code; populated, semantics unverified |

ENEMY confirmed causally: walking x=416→815 populated slots 0–2 at x=832/1008,
y≈454 (just ahead of the player, same ground band); firing then drove slot 0's
`life` 10→7→5→2→0 with `muteki` latching to 1 on death, and only then began
draining slot 1 (12→…→0). That also closes `muteki`, the last unexercised
field from #10.

Correction worth recording: `0x80160000` is **not** an array base — it is the
`lui 0x8016` half of the player's address (`−7620` → `0x8015E23C`). A tracker
that ignores the paired `addiu` reports it wrongly; an earlier pass here did.

`hitptr` (`+0x3C`) is now decoded — see #12 and `docs/HITBOX.md`.

## #12 — Hitbox format decoded — DONE

`actor+0x3C` points at a 4-byte record: `int8 half_w, half_h, off_x, off_y`.
Decoded from the collision routine `func_801076CC` (`0x801076CC`, 13 callers),
which runs the standard AABB test `|rel| < half_wA + half_wB` in integer pixels
— it reads positions as the HIGH halfword of the 16.16 fields (`lh 0x0E` /
`lh 0x12`), which re-confirms the fixed-point format independently. `chrdir`
bit `0x40`/`0x80` mirrors the offsets horizontally/vertically. On a hit the
routine writes X/Y penetration depths to `0x801C7384` / `0x801C7388`.

Confirmed live: forcing contact (writing the player's position onto an enemy)
produced `life` 40→36→33→30 with `muteki` cycling for i-frames and knockback
965→939→913, and the penetration globals went non-zero exactly during contact.
`chrdir` was independently confirmed as the facing bit (0x40 walking right,
0x00 walking left).

Camera found (#13), so the boxes were then drawn on a live frame and match the
sprites exactly. Remaining limit: the penetration globals cannot be attributed
to one actor pair — every collision test in the frame overwrites them — so no
pairwise numeric match was established. Full detail in `docs/HITBOX.md`.

## #13 — Camera found; hitbox viewer working — DONE

`screen = world − camera`, camera X/Y are plain `s32` world pixels at
**`0x8016EC0C`** / **`0x8016EC10`** (a packed s16 `(camY,camX)` copy sits at
`0x801D2918`). Found by sampling RAM at four distinct player positions and
solving for a value that keeps the player within a 320-wide screen: it clamps
at the stage edge (playerX 272 → cam 256, screenX 16) and otherwise locks the
player at screen centre (452→292, 633→473, 799→639, all screenX 160).

`tools/actor_watch.py --overlay out.png` now screenshots the game and draws
every actor's hitbox. The player's 16×38 box wraps Mega Man exactly and the
tall 16×114 box wraps a palm-tree trunk ground-to-fronds — confirming the
hitbox fields, flip handling, camera and 16.16 positions in one image. It also
resolved a puzzle from #12: the `life = 12` "enemy" blocking the player was a
destructible palm tree.

The camera is also what the widescreen cull work will need (#4 / X4 template).

## #14 — Widescreen: launcher toggle, full-width background, anchored HUD — WORKING (experimental)

Opt-in 16:9 ships as a launcher Mods toggle (`mm8.enhancement.widescreen`),
default OFF. Engaged state measured: `mode=2`, `nw_extra=106`, `x_margin=53` —
a 426x240 native-wide frame (exactly 16:9), presented 1:1, nothing stretched.
With the mod off every widescreen value is 0 and the runtime prints no
widescreen line: the default path is untouched. See `docs/WIDESCREEN.md`.

Three pieces were needed:
  * `[widescreen] full_2d = true` (native-wide, not the GTE squash hack);
  * `[widescreen.cull] auto_screen_x = true` + **`screen_h_imms = ["0x100"]`** —
    MM8's funnel is `func_800FA050` (`slti ...,256` Y paired with
    `slti ...,320` X). Its height bound is 0x100, not the framework default
    0xE0/0xF1 nor X4's 0xF0; without the override the detector never qualifies
    the function and the widening silently does nothing;
  * a trusted mod plugin calling `psx_mod_set_fixed_display_aspect(16,9)` —
    required, because the framework treats widescreen as mod-owned on PSX and
    clamps a bare `[video] aspect_ratio` back to 4:3.

**Background solved (same day).** Found the renderer from the GPU stream, not
by pattern matching: a frame dump showed 577 GP0 0x7C (textured 16x16) prims on
a 21x16 grid in a packet arena at 0x801CB400; write-tracing that arena named
`func_800F98D8` (column loop) and `func_800F99F8` (column emitter). MM8 has NO
tile ring or streamer — it indexes its map directly — so only three sites are
hooked:

    count_site    = "0x800F99CC"   sltiu v0,s2,21
    startcol_site = "0x800F993C"   sra   v0,v0,20   (UNMASKED)
    startx_site   = "0x800F994C"   subu  v1,zero,v1

`startcol_site` needed a framework change (it only accepted the `andi` ring-mask
form) — parked as `upstream/0002-bg2d-startcol-accept-unmasked-sra.patch`. The
plugin must also call `gpu_ws_mmx6_set_freshfix(0)`: the bg2d helpers run an
MMX6 ring refill that defaults ON and would write through default layer/ring
addresses, i.e. arbitrary RAM in this title.

Measured: mid-stage margins went from L=53/R=37 black to **L=0/R=0** — the full
426 px is background. Verified stable across walking/jumping with 0 dispatch
misses, and mod-off still produces an untouched 320x240.

At a stage's left boundary 53 px of black remains, which is correct: the camera
clamps at the map edge and no tiles exist further left.

**HUD anchoring solved (same day).** MM8 builds its HUD into a dedicated
double-buffered packet arena; isolating ordering-table rank 8 in a gameplay
frame found a 0x2C quad + nine 0x7C sprites at native x 10..30, y 24..88 (bar,
weapon icon, life counter), in buffers 0x80152974..0x80152AE4 and
0x80152D54..0x80152DD4. Config (runtime-only, no regen):

    nw_left_hud_packet_lo = "0x80152900"
    nw_left_hud_packet_hi = "0x80152E00"

`nw_hud_corners` stays OFF — MM8's world is itself screen-space 2D, so the
unfiltered mode would drag scenery to the edges too. Result: HUD at x=20 of 426
instead of x=54, stable across walk/jump/fire, 0 dispatch misses, and mod-off
still an untouched 320x240.

**Stage-boundary black bar and enemy pop-in fixed** via two trusted mod-plugin
hooks (`[recompiler] mod_function_entry_funcs`, identity at 4:3):
  * `func_801023BC` (camera min/max clamp) — pre-clamp camX to the INSET range
    [Xmin+margin, Xmax-margin]. Stateless: the inset range is a subset of the
    game's own, so its clamp is a no-op on our value and the authored bounds are
    never mutated. At the intro stage's left edge camX is now 309 (was 256) and
    the frame measures black L=0 R=0.
  * `func_80101C54` (set-table spawn window) — push the X bounds out by the same
    margin. Baseline 4:3 headroom is only +19/+33 px past the visible edge, so
    the 53 px reveal had put activation 34 px INSIDE the view (the reported
    pop-in). Now +150/+326 px off-screen.

Verified with the mod OFF: 320x240, camera clamps to the stock 256, all
widescreen state 0, 0 dispatch misses — the emitted hooks are fully inert.

**Still open:** only the intro stage has been exercised — other stages' HUD
packets should be re-checked against this arena range, and no right-edge HUD
element (boss health) has been tested. The camera/spawn hooks read the stage's
own bounds so they should be stage-agnostic.

**Testing trap worth remembering:** widescreen cannot be verified headless. The
engage step sits after `if (g_headless) { ... return ep; }` in
`sdl_vblank_present_body()`, so a headless run always reports `mode=0`
regardless of configuration. Test windowed.

## #7 — Symbolization: 73 names of 7,292 functions — OPEN (ongoing)

`tools/analyze_symbols.py` derives names from evidence in the binary and now
annotates 232 functions (2,056 `[NOTE]` comments in the generated C). Coverage
is deliberately limited to what is provable: BIOS thunks, Psy-Q routines that
log their own name, and Capcom's shipped debug menu. The bulk of the engine —
including the hottest functions (`0x801049C0` with 241 callers, `0x8010488C`
with 230) — is still anonymous.

Best next thread: the debug menu's actor-field printers name the actor struct's
layout (speedx/speedy/gravity, dmg_id/str/muteki/life, scrptr/hitptr,
beflag/routn0..2, settbl/pos_x/pos_y). Reading those printers yields the field
offsets, which is the prerequisite for hitbox/practice tooling and for the
widescreen cull work. For gameplay functions the debug menu does not reach, use
the debug server's `wtrace_range`/`wtrace_dump` to find who writes a known RAM
address. See `docs/SYMBOLS.md`.

## #5 — Generated C size (183 MB, 131 shards) — OPEN (dev-only)

Shards 07/08/114/125/126/128 are 6–8 MB and 234–532 k lines: likely the same
alias-promotion bloat X4 tracks as its issue #4 (overlapping alias bodies over
data/pointer tables). Correctness unaffected; only slows source builds
(~5 min at -O2 on 12 cores). Recompiler-side fix in the framework, then regen.

## #15 — Video filters (Scale2x/3x, 2xSaI family, xBR 2x–4x, sharp, scanlines, CRT) — DONE

Framework feature (parked as `upstream/0004-…` + `upstream/recomp-ui-0001-…`,
doc `psxrecomp/docs/VIDEO_FILTERS.md`). Launcher: Settings → Display → **Video
filter**; ESC menu → VIDEO FILTER (live, persisted); `game.toml [video] filter`; `PSX_VIDEO_FILTER`; debug `video_filter`.
Default `none` is byte-identical. Verified in-game with
`tools/video_filter_check.py`: GL shader output == CPU reference to ≤1 LSB for
all eight upscalers (title, intro FMV, intro-stage gameplay); software
renderer path captured too. Vulkan is unfiltered by design.

## #16 — GL frame interpolation thread never swaps on this box — OPEN (pre-existing, framework)

Observed while testing #15: with `PSX_FRAME_INTERPOLATION=1` (OpenGL, Wayland,
Mesa 26.0.3) `gl_interp` reports `enabled=1 history=2 swaps=0`, the present
ring shows no `interp` presents and the window freezes after the first frames —
with **or without** a video filter, so it is not caused by #15. Not chased.
Repro: `PSX_FRAME_INTERPOLATION=1 bash tools/run_mm8.sh --debug --no-launcher`,
then `{"cmd":"gl_interp"}` / `{"cmd":"gl_present_ring","n":3}` on port 4545.

## #17 — Bug-report bundles (F9) — DONE

`psxrecomp/docs/BUG_REPORT.md`. F9 (or debug `bug_report`) writes
`saves/bugreports/<stamp>_<trigger>/` with frame.png / frame_hires.png /
screen.png (post-filter window) / state.pst (reloadable via
`savestate op=load_path`) / report.json (host settings + 13 debug queries:
frame, dispatch misses, GPU/overlay/autocompile/present-ring/pad state) /
README.txt. Patch: `upstream/0005-…` (+ hunks inside 0004 for main.cpp,
debug_server.c, gpu_gl_renderer.c).

## #18 — Headless script mode — DONE

`--headless --script '<debug-cmd>;wait:N;expect:..;quit'` (psxrecomp
`runtime/src/psx_script.c`, docs `psxrecomp/docs/HEADLESS.md`); wrapper
`tools/mm8_headless.sh` (defaults: load slot 3, screenshot + post-filter
present capture, optional `--bug-report`). Verified: slot load → screenshot →
xbr2x/scale3x present capture → bug-report bundle → clean exit 0 in seconds,
no window. Patch `upstream/0006-…`.
