# Mega Man 8 — widescreen

Experimental opt-in 16:9. **Off by default**, exposed as a launcher toggle on
the Mods page. With it off the build is byte-identical to faithful 4:3.

## How to turn it on

Launcher → **Mods** → *Mega Man 8 Widescreen* → enable **Widescreen
(Experimental)**, then launch. The setting persists in `<exe dir>/mods/state.toml`.

Headless / scripted:

```toml
# <build dir>/mods/state.toml
format_version = 2

[[feature]]
package_id = "mm8.enhancement.widescreen"
id = "widescreen"
enabled = true
```

## What it does

MM8 is a pure-2D title, so this uses the framework's **native-wide** path, not
the GTE squash hack: the game renders a genuinely wider field of view into a
wider framebuffer and presents 1:1. Nothing is stretched or cropped.

Measured engaged state: `mode = 2`, `nw_extra = 106`, `x_margin = 53` — a
**426 × 240** frame (exactly 16:9 at 240 lines) with 53 px revealed per side.

The mechanism has three parts:

1. **`game.toml [widescreen] full_2d = true`** — selects native-wide.
2. **`[widescreen.cull] auto_screen_x = true`** — the recompiler finds the
   game's own screen-extent reject and widens it, so actors and tiles the game
   would normally discard at the screen edge are produced and drawn. This emits
   into generated C, so **changing it requires a regen**.
3. **The mod plugin** (`src/mods/mm8_widescreen_plugin.c`) calls
   `psx_mod_set_fixed_display_aspect(16, 9)` when the player enables the
   feature. This is required: on PSX the framework treats widescreen as
   mod-owned and clamps a bare `[video] aspect_ratio` back to 4:3
   (*"widescreen is mod-owned on PSX; clamping display aspect 16:9 -> 4:3"*).

### The cull site

MM8's screen-extent funnel is **`func_800FA050`**:

```mips
800FA0F4: slti $v1, $v1, 256    ; Y bound (0x100)
800FA100: beq  $v1, $zero, ...  ; reject
800FA11C: slti $v0, $v0, 320    ; X bound (0x140)
800FA120: beq  $v0, $zero, ...  ; reject
```

The auto-detector requires a width immediate paired with a height immediate in
the same function. MM8's height bound is **`0x100` (256)** — not the framework
default (`0xE0`/`0xF1`) and not X4's `0xF0`, hence:

```toml
[widescreen.cull]
auto_screen_x = true
screen_h_imms = ["0x100"]
```

Without that override the detector does not qualify the function and the
widening silently does nothing. Verified in the output: two
`psx_ws_cull_slti(..., 320)` calls emitted, at `0x800FA11C` and `0x800FA1DC`,
both inside `func_800FA050`.

## The background tile renderer

Found from the GPU stream rather than by pattern-matching: a frame dump showed
577 GP0 `0x7C` primitives (textured 16x16 rectangles) at the back ordering-table
ranks, on a 21-column x 16-row grid, built into a 16-byte-stride packet arena at
`0x801CB400`. Write-tracing that arena named the builder directly.

* **`func_800F98D8`** — the column loop. 21 columns, X += 16 each, two
  `jal`s per column for the vertical ring split.
* **`func_800F99F8(layer, count)`** — the column emitter. Steps Y by 16 and
  advances the map pointer 32 bytes (one 16-entry row) per tile.
* Tile definitions live at **`0x80171C3C`** in 16x16 blocks of 512 bytes; the
  map base is at `layer+12`. Working state is in scratchpad `0x1F800000`.

Unlike X4/X5/X6, MM8 has **no tile ring and no leading-edge streamer** — it
indexes the map directly. So only three sites are hooked and the
`stream_left`/`stream_right` sites simply do not exist here:

```toml
[widescreen.bg2d]
count_site    = "0x800F99CC"   # sltiu v0,s2,21   -> 21 + 2*LEFT columns
startcol_site = "0x800F993C"   # sra   v0,v0,20   -> start column - LEFT
startx_site   = "0x800F994C"   # subu  v1,zero,v1 -> start X - LEFT*16
```

`startcol_site` required a **framework change**: it previously accepted only
`andi` (the ring-mask form), and MM8's unmasked `sra` hard-failed the emitter.
The fix accepts both, mirroring how `startx_site` already takes two forms. It is
parked as `upstream/0002-bg2d-startcol-accept-unmasked-sra.patch`.

The mod plugin must also call **`gpu_ws_mmx6_set_freshfix(0)`**. The
`psx_ws_bg2d_*` helpers all call an MMX6-style ring refill that defaults **on**,
and with no ring in this title it would write through the framework's default
layer/ring addresses — arbitrary RAM in MM8.

### Result

| position | before | after |
|---|---|---|
| mid-stage | 53 px black left, 37 right | **0 / 0 — full 426 px of background** |
| at a stage's left boundary | 53 / 37 | 53 / 0 |

The residual margin at a stage boundary is **correct behaviour, not a defect**:
the camera clamps at the map edge, so no tiles exist further left. Any
widescreen hack hits this; tiles that were never authored cannot be invented.

## HUD anchoring

MM8 builds the player HUD into a **dedicated double-buffered GP0 packet arena**,
separate from the background tile arena (`0x801C7000`+). Commands sourced from
it are re-anchored to the true 16:9 edges; everything else is untouched.

Found by dumping a gameplay frame and isolating ordering-table **rank 8**: one
`0x2C` textured quad plus nine `0x7C` sprites at native x 10..30, y 24..88 — the
health bar, the weapon icon and the life counter. Sampling eight frames exposed
both buffers, `0x80152974..0x80152AE4` and `0x80152D54..0x80152DD4`:

```toml
[widescreen]
nw_left_hud_packet_lo = "0x80152900"
nw_left_hud_packet_hi = "0x80152E00"
```

The range brackets both buffers with margin, and nothing else draws from it —
which matters, because the unfiltered `nw_hud_corners` mode must stay **off**
for this title: MM8's world is itself built from screen-space 2D primitives, so
an unfiltered rule would drag scenery to the edges along with the HUD.

Runtime-only — changing the range needs a relaunch, not a regen.

Result: the HUD sits at **x ≈ 20** in the 426 px frame instead of floating at
x ≈ 54 (its centred 4:3 position). Verified stable at x = 20 across walking,
jumping and firing.

## Stage boundaries and object spawning

Two problems the reveal creates on its own, both fixed through trusted mod-plugin
hooks on `[recompiler] mod_function_entry_funcs` (identity at 4:3, stateless):

### Camera inset — `func_801023BC`

MM8 clamps the camera to the stage's authored bounds (camera struct `$a0`:
camX `+6`, Xmax `+0x1A`, Xmin `+0x1C`). At a boundary the camera stops exactly
on the map edge, so the reveal had no map to show and rendered black.

The plugin pre-clamps camX to the **inset** range `[Xmin+margin, Xmax-margin]`
at that routine's entry. Because the inset range is a strict subset of the
game's own, the game's clamp immediately afterwards is a no-op on the value we
wrote — nothing accumulates and the stage's authored bounds are never mutated.

Verified: at the intro stage's left boundary camX is now **309** (= 256 + 53)
instead of 256, and the frame measures **black L=0 R=0**.

### Spawn window — `func_80101C54`

MM8 activates set-table objects by testing each entry against a rectangular
window passed in `$a0..$a3`:

```mips
slt v0, Xmin, entryX     ; spawn requires Xmin < entryX
slt v0, entryX, Xmax     ;           and entryX < Xmax
```

That window is sized for the 320 px view. Measured baseline headroom in 4:3 is
only **+19 / +33 px** past the visible edge — so moving the edge out by 53 px
put activation **34 px inside the view**, which is the "enemies appear out of
nowhere" symptom. The plugin pushes the X bounds out by the same per-side
margin the renderer reveals.

Verified by walking the same route and recording each object's native screen X
at first sighting:

| | baseline 4:3 | widescreen, no fix (derived) | widescreen + fix |
|---|---|---|---|
| headroom past visible edge | +19 / +33 px | **−34 px (visible pop-in)** | +150 / +326 px |

Note the visible window in native-wide is `[-margin, 320+margin]`, **not**
`[0, 426]`: the renderer works in native coordinates and the compositor applies
the margin offset. Comparing against `0..426` makes correct spawns look like
pop-ins.

## Still not done

* Only the intro stage has been exercised. Other stages load different
  `OVL/STAGEnn.BIN` overlays and may reveal layer/parallax cases this does not
  cover — and their HUD packets should be re-checked against the configured
  arena range. The camera-inset and spawn-window hooks are stage-agnostic (they
  read the stage's own bounds), so those should carry over.
* No right-edge HUD element exists in the intro stage (boss-health bars appear
  in boss rooms); the framework would push those to the right edge
  automatically, but that is untested here.

## Verification

| | mod OFF | mod ON |
|---|---|---|
| framebuffer | 320 × 240 | 426 × 240 (background fills it fully) |
| `ws.mode` | 0 | 2 (native-wide) |
| `ws.nw_extra` | 0 | 106 |
| `ws.x_margin` | 0 | 53 |
| HUD left edge | x 18 (of 320) | x 20 (of 426) — true wide edge |
| widescreen line in log | absent | `widescreen 16:9 (native-wide, present 1:1)` |

The OFF column is the important one: every widescreen value is zero and the
runtime prints no widescreen line at all, so the default path is untouched.

**Testing note 2:** the runtime **rewrites `<exe>/mods/state.toml` on exit**, so
a hand-edited enable flag is discarded when the game next quits. Re-write it
before each scripted run (or set it in the launcher).

**Testing note:** widescreen **cannot be verified headless**. The engage step
lives in `sdl_vblank_present_body()` *after* the
`if (g_headless) { ep.skip_pace = 1; return ep; }` early-out, so a headless run
always reports `mode = 0` no matter what is configured. Use
`bash tools/run_mm8.sh --debug` (windowed) and query `gpu_state.ws` over the
debug server. This cost real time to discover — it presents exactly like a
broken config.
