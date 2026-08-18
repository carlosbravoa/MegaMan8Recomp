# Mega Man 8 — widescreen

Opt-in 16:9. **Off by default**, exposed as a launcher toggle on the Mods
page. With it off the build is byte-identical to faithful 4:3.

## How to turn it on

Launcher → **Mods** → *Mega Man 8 Widescreen* → enable **Widescreen
(Experimental)**, then launch. The setting persists in `<exe dir>/mods/state.toml`.

Headless / scripted (`tools/ws_headless.sh` does all of this for you):

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

Engaged state: `mode = 2`, `nw_extra = 106`, `nw_left = 0`, `nw_right = 106`,
`nw_anchor = 1` — a **426 × 240** frame (exactly 16:9 at 240 lines), and the
whole 106 px is revealed **on the right**.

### Left-anchored reveal — the design

The wide frame's left edge **is** the 4:3 left edge (`[widescreen]
nw_anchor = "left"`). MM8's gameplay is authored against that edge: the camera
clamps at the map's left boundary, the player is walled at the screen edge,
stages start with the camera at `Xmin`. With the earlier *centred* split (53 px
each side) the left reveal asked for map that was never authored at every
boundary, and the only way to hide it was to move the camera off its authored
positions (the retired "camera inset" hook) — which is exactly what the player
saw as *foreground shifted left of the walkable area with a black column
behind it* at every stage start (ISSUES #16). Left-anchored, background,
foreground and the playable area line up with 4:3 **by construction** — the
left 320 columns of the wide frame are pixel-identical to the 4:3 frame
(verified per pixel on the intro stage start) — and the player simply sees
106 px further ahead. Mega Man stands at x≈160 of 426.

The reveal is anchored only while the **stage world** is drawn
(`nw_anchor_gate = "bg2d"` + the plugin's world gate): the pause menu, NOW
LOADING, title and stage select draw their own fixed 320-wide layouts and take
the centred split, so they sit in the middle of the wide frame with the reveal
on both sides. The flip happens on the fully black frame of the pause wipe /
stage iris (measured with `present_capture` every frame in both directions).

### The mechanism

1. **`game.toml [widescreen] full_2d = true`** — native-wide, every game frame
   is gameplay for the classifier.
2. **`nw_anchor = "left"`, `nw_anchor_gate = "bg2d"`** — the split above.
3. **`[widescreen.cull] auto_screen_x = true` + `screen_h_imms = ["0x100"]`** —
   the recompiler widens MM8's screen-extent reject `func_800FA050`
   (`slti v0,v0,320` at `0x800FA11C` / `0x800FA1DC`, paired with a `0x100`
   height bound — not the framework's `0xE0`/`0xF1` default) by the right
   margin, so actors and tiles the game would discard at the 4:3 edge are drawn.
   Emitted into generated C: changing it requires a regen.
4. **`[widescreen.bg2d]`** — the tile renderer `func_800F98D8` (21 columns of
   16×16 tiles, no ring, direct map indexing) gets 7 extra columns on the
   right: `count_site 0x800F99CC` (`sltiu v0,s2,21` → 21 + right cols),
   `startcol_site 0x800F993C` (unmasked `sra`), `startx_site 0x800F994C`
   (both identity with a left margin of 0). The mod plugin calls
   `gpu_ws_mmx6_set_freshfix(0)`: the MMX6 ring refill defaults on and would
   write through the framework's default layer/ring addresses — arbitrary RAM
   here.
5. **`[[widescreen.cull.edge]]`** — the game's screen-edge bounds (next section).
6. **The mod plugin** (`src/mods/mm8_widescreen_plugin.c`):
   `psx_mod_set_fixed_display_aspect(16, 9)` on activation (widescreen is
   mod-owned on PSX — a bare `[video] aspect_ratio` is clamped back to 4:3);
   the spawn-window hook; the world gate.
7. **HUD** — MM8 builds the player HUD into a dedicated double-buffered packet
   arena (`nw_left_hud_packet_lo/hi = 0x80152900..0x80152E00`, both buffers
   observed at `0x80152974..0x80152AE4` / `0x80152D54..0x80152DD4`). Left-third
   pieces move by the left margin (0: they already sit at the wide left edge),
   right-third pieces by the right margin. `nw_hud_corners` (unfiltered) must
   stay off: the world itself is screen-space 2D primitives.

## Off-screen logic ("enemies appear out of nowhere")

MM8 activates, keeps alive and animates actors relative to `camX` (camera
struct `0x801D2914`, `camX` at +6) with the **4:3 width baked in**:

| routine | rule (4:3) | now |
|---|---|---|
| set-table spawn `func_80101C54` (caller `func_80101ACC`) | scrolling right: a 32 px strip `[camX+336, camX+368)` sweeps ahead of the screen; scrolling left `[camX-48, camX-16)`; room entry `[camX-48, camX+368)` | each X bound moves by the reveal on **its** side (right of the screen centre → +106): the strip is **translated** to `[442, 474)`, the full window widened to `[-48, 474)` — plugin hook |
| keep-alive `func_801047C8` (+ parametric `func_80104820`, `func_8012D274`) | alive iff `camX-56 < x < camX+376` | `< camX+482` — `edge` sites |
| on-screen flag `inscrn` `func_80104A68` (+ parametric `func_80104AEC`, `func_8012D1B0`) | `camX-32 < x < camX+352` | `< camX+458` |
| actors parked at the right edge (`0x8011C01C`, STAGE03/0B `+352`) | `camX+336` / `+352` | `+442` / `+458` |
| per-stage overlay copies of the same idiom | e.g. STAGE00 `camX+376 < x`, STAGE04 keep-alive, STAGE07 window | listed with their instruction word; applied only where that stage's code holds it |

Why it matters, measured on the intro stage with actor telemetry
(`tools/ws_headless.sh` + `read_ram` of the ENEMY array every 4 frames): with
only the spawn window widened — the previous state — every entry between
`camX+376` and the widened window was **spawned and killed on the same frame,
every frame** (`wtrace` on the actor `beflag`: `0x80101D34` sets it, the
keep-alive's `func_801058BC` clears it), i.e. a dead zone across the visible
right side where enemies popped in only once the camera brought them inside
376. That is also the *snail-shell* symptom: the shell (set entry id 7 at
1528, rolls down the slope to the right when shot) ran through Metools that
were not alive yet, so they "appeared after the shell had rolled by". With
every bound moved together the pipeline keeps the same distance from the wide
edge as it had from the 4:3 edge: objects spawn 16..48 px past it and live to
56 px past it — spawns measured at `dx_cam ≈ 462–469` (4:3: 355–367),
despawns at ≈ 448–460 (4:3: 331–343), the shell now kills the Metools it
rolls over.

What is *not* identical, and cannot be while the reveal exists: anything the
player can reach 106 px further — buster shots live 106 px longer (they die 56
px past the wide edge, as they died 56 px past the 4:3 edge), so an enemy such
as that shell can be shot, and start rolling, from further away; it then runs
ahead of a camera that is further back and may leave the keep-alive range
before the last Metool. Seeing further and acting on it is the point of the
reveal.

Left-side bounds are all listed with `side = "left"` and are identity with the
left anchor; a centred anchor would move them too. Register-computed left
bounds (`subu v1,a3,a1`) are `edge` sites as well.

**Not covered:** other overlay-local screen-edge idioms that use layer fields
other than camX (`+0x14`, `+0x2C`) or Y — the scan
(`tools`: disassemble the OVL files for `addiu … 320/336/352/368/376/384`
with a `camX` load in the four preceding instructions) listed them; add an
`edge` entry with the exact word once each is understood.

## Known cosmetics

* The pause / stage-start **wipes** (16 flat black quads in a 4×4 grid, the
  iris) cover the 4:3 area only: the reveal shows the world un-wiped for a few
  frames until the anchor flips on the black frame.
* In-stage screen-space text (**READY**, boss names, dialogue) is drawn from
  the general sprite arena at its 4:3 position, i.e. centred on x = 160 of the
  426 frame, not on the wide centre. It cannot be told apart from world
  sprites by source range, so it stays where the game put it.
* At a stage's **right** boundary (boss rooms) the reveal shows whatever the
  map holds beyond `Xmax + 320`; the intro/Tengu/Clown/Frost/Grenade starts
  and mid-stage all show authored map, boss rooms are unverified.
* The `1x` colour expansion differs by ≤ 7/255 between the wide compositor
  (`(c<<3)|(c>>2)`) and the plain 4:3 software present (`c<<3`) — compare
  captures quantised to 5 bits (`tools/ws_headless.sh` output vs `--off`).

## Verification (all headless, `bash tools/ws_headless.sh …`)

| check | result |
|---|---|
| intro stage start, left 320 columns vs 4:3 (`--off`) | 0 differing pixels (5-bit) |
| intro / Tengu / Clown / Frost / Grenade starts | 426 px of authored map, HUD at x≈18, Mega Man at x≈160 |
| pause menu open / close (capture every 3–5 frames) | menu centred with the circuit background both sides; flip lands on the black wipe frame |
| stage select, title | centred (`nw_anchor 0`, `nw_anchor_world 0`) |
| stage select → NOW LOADING → intro iris → READY | player `beflag` = 1 from the first stage frame: no mid-scene flip |
| enemy telemetry (spawn / despawn distances, shell vs Metools) | table above |
| mod OFF | 320×240, `ws.mode 0`, every margin 0, no widescreen line in the log |

`gpu_state.ws` now reports `nw_left`, `nw_right`, `nw_anchor` (effective),
`nw_anchor_cfg`, `nw_anchor_gate`, `nw_anchor_world`, `bg2d_last_frame`.

## Testing notes

* **Widescreen engages headless** since the framework moved the engage step
  ahead of the headless early-out; `present_capture` writes the wide frame.
  `tools/ws_headless.sh [--bookmark "…" | --slot N | --cold] [--frames N]
  [--script …] [--off]` writes `present.png` (426 px when engaged),
  `frame.png` (native VRAM), `ws.json`. Windowed runs are only needed for
  GL-specific questions.
* The runtime **rewrites `<exe>/mods/state.toml` on exit** — the script saves
  and restores it around a run.
* The user's bookmarks were taken with START latched (the old input-leak bug),
  so the intro/Frost/Grenade ones open the pause menu ~30 frames after resume:
  capture at `--frames 5` or press START at ~170 and wait for the wipe.
