# Spec — widescreen defect at stage start

Short handover note. Everything below is either **measured** or explicitly
flagged as **inferred**. Read the caveat first; it may invalidate part of the
diagnosis.

## Symptom

With the widescreen mod on, the beginning of a stage shows a **large black
region on the left**. Mid-stage is fine. Reported by the player; reproduced on
stage 02 (Clown Man) entered via the stage-select developer feature.

## ⚠ Caveat — the two observations do not agree

| observer | sees |
|---|---|
| player, on the actual display | a black **bar** down the left side |
| `screenshot` debug command, 426x240 capture | diagonal black **wedges** (bowtie) covering ~44% of the frame |

These are not the same artifact. `screenshot` captures native 15-bit VRAM and
composites the native-wide frame itself, so **the wedges may be an artifact of
the capture path rather than of what is presented**. `screenshot_hires` returns
`scale: 1` here and does not settle it.

**Resolve this before trusting any of the wedge-based reasoning below.** The
cheapest way is a photo/grab of the actual window at a stage start. If the
window shows a plain left bar and no wedges, then every "44% dark" measurement
in `ISSUES.md #16` is measuring the capture, and the real defect is only the
black margin described in "Mechanism" — a much smaller problem.

## Measured facts (independent of the caveat)

* Widescreen engages at **game entry**, not at boot: before the scene starts the
  frame is 320x240 and the mod looks inert. Engaged frame is **426x240**,
  `nw_extra=106`, `x_margin=53` (53 px revealed per side).
* **Mid-stage 16:9 has no black margins at all** (`black L=0 R=0` measured while
  scrolling). The defect is specific to the camera at a stage's left boundary.
* With widescreen **off**, the same stage entry is clean (0% dark).
* Stage 02's authored camera travel at the start is **`Xmin=256, Xmax=280`** —
  24 px, against a 53 px reveal.
* The camera scroll the background actually uses is read from **scratchpad
  `0x1F800000`**; the RAM global `0x8016EC0C` and the camera struct
  (`0x801D2914`, camX `+6`, Xmax `+0x1A`, Xmin `+0x1C`) are upstream copies.
* `func_80100E00` rewrites the scroll global every frame (`pc=0x80100E90`, 60/s),
  after the camera clamp `func_801023BC` runs.
* Two background layers exist. Tiles (`0x7C` prims, arena `0x1CB000`–`0x1CE000`)
  are widened by `[widescreen.bg2d]`. A second layer of `0x2C` textured quads
  (arena `0x80167000`, ~30/frame, built once at stage load by **`func_800F90D4`**)
  is **not** widened by anything.

## Mechanism (inferred, but well supported)

At a stage start the map simply ends at the camera's leftmost position. The
53 px reveal therefore asks for map that was never authored. The camera can be
inset to hide this, but only by as much as the authored travel allows — 24 px on
stage 02 — leaving ~29 px with nothing to draw.

## Tried and rejected (do not redo)

| attempt | result |
|---|---|
| Clamp camX in `func_801023BC` only | Overwritten every frame by `func_80100E00`; inset flickers on/off. |
| Clamp the scroll at the background builders' entry | **Corrupts rendering.** Those run ~5x per frame (once per layer), so the origin moves between layers. |
| Raise the authored `Xmax` to make room for the inset | **Corrupts rendering.** That bound also feeds the tile fetch; raising it walks the background off the end of the map. |
| Clamp a negative `startcol` in `psx_ws_bg2d_startcol` | No observable change; reverted rather than left in unproven. Still arguably correct for direct-index titles — an unmasked `startcol` has no ring to wrap into — so revisit as correctness, not as this fix. |

## Suggested next steps

1. **Settle the caveat** (photo of the real window). Everything else depends on it.
2. If the wedges are real: probe `[widescreen.cull] auto_screen_x` by forcing the
   cull margin to 0 live with `gpu_ws_set_margin_override(0)` while leaving the
   reveal engaged. If the wedges vanish, the widened screen-extent reject is
   admitting primitives the game meant to discard.
3. If the wedges are a capture artifact: the remaining work is only the
   un-widened quad layer — widen `func_800F90D4`, or accept a reduced reveal at
   map edges (shrink `x_margin` toward the boundary so the frame never asks for
   map that does not exist).

## Current state of the code

The camera inset is left **enabled and left-anchored** (`src/mods/mm8_widescreen_plugin.c`):
it records the stage bounds at `func_801023BC` and clamps camX there, preferring
the left edge when the reveal is wider than the authored travel. It is
identity at 4:3. No framework changes are outstanding for this issue — the
`gpu.c` experiment was reverted and upstream patch 0001 verified still applied.
