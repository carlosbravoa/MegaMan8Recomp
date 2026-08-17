#include "mod_plugins.h"
#include "cpu_state.h"

#include <stdint.h>

/*
 * Mega Man 8 — widescreen activation plugin.
 *
 * On PSX the framework treats widescreen as MOD-OWNED: a plain
 * `[video] aspect_ratio` wider than 4:3 is clamped back
 * ("widescreen is mod-owned on PSX; clamping display aspect 16:9 -> 4:3").
 * The player-facing switch therefore lives in the launcher's Mods page, and
 * this plugin is what the enabled feature activates.
 *
 * The rendering work itself is not here — it is the recompiler's native-wide
 * cull widening (game.toml [widescreen] full_2d + [widescreen.cull]
 * auto_screen_x, which widens MM8's screen-extent funnel at func_800FA050)
 * plus the runtime's wide compositor. This entry point only declares the
 * display aspect once the player opts in, so with the mod disabled the build
 * presents native 4:3 and is byte-identical to faithful.
 */
/*
 * MM8's background renderer (func_800F98D8) indexes its tile map DIRECTLY —
 * `sra` the scroll value to a column, no power-of-two ring, no leading-edge
 * streamer. It therefore must NOT run the MMX6-style ring refill, which
 * defaults ON (g_mmx6_freshfix = 1) and would write through the framework's
 * default layer/ring addresses (Tomba's 0x800971F8 / 0x800A21B8) — arbitrary
 * RAM in this title. Widening the loop and the start column is sufficient here
 * because the map lookup naturally fetches the neighbouring columns.
 */
extern void gpu_ws_mmx6_set_freshfix(int on);

/*
 * Camera inset at stage boundaries (func_801023BC).
 *
 * MM8 clamps the camera to the stage's authored bounds: a min/max pair in the
 * camera struct ($a0), camX at +6, Xmax at +0x1A, Xmin at +0x1C. At a boundary
 * the camera stops exactly on the map edge, so the widescreen reveal has no map
 * to show and renders black.
 *
 * Fix: pre-clamp camX to the INSET range [Xmin+margin, Xmax-margin] at the
 * clamp routine's entry. Because the inset range is a strict subset of the
 * game's own [Xmin, Xmax], the game's clamp immediately afterwards is a no-op
 * on the value we wrote — so this is stateless and idempotent, and it never
 * mutates the stage's authored bounds. Identity at 4:3, where the margin is 0.
 */
#define MM8_CAM_X        0x06u
#define MM8_CAM_X_MAX    0x1Au
#define MM8_CAM_X_MIN    0x1Cu

/*
 * The stage's authored bounds, captured from the camera struct. Clamping at
 * THIS routine is not sufficient on its own: func_80100E00 rewrites the camera
 * scroll global every frame (measured: `pc=0x80100E90 -> 0x00000100`, 60x/s).
 * Biasing the struct here is still what reaches the screen, because the scroll
 * the renderer reads is re-derived from it; the bounds are also recorded so the
 * left-anchor rule below can use them.
 */
static int32_t s_cam_lo = 0, s_cam_hi = 0;
static int     s_cam_bounds_valid = 0;

static void mm8_widescreen_camera_inset(struct CPUState* cpu, uint32_t address) {
    (void)address;
    const uint32_t cam = cpu->gpr[4];           /* $a0 = camera struct */
    if (cam < 0x80010000u || cam >= 0x80200000u) return;

    s_cam_lo = (int16_t)psx_mod_read_half(cam + MM8_CAM_X_MIN);
    s_cam_hi = (int16_t)psx_mod_read_half(cam + MM8_CAM_X_MAX);
    s_cam_bounds_valid = 1;

    /* Clamp the STRUCT copy too, at the source. The scroll the renderer reads
     * is derived from this each frame, so biasing here is what can actually
     * reach the background. Left-anchored: when the reveal is wider than the
     * stage's authored camera travel the two insets collide, and the LEFT one
     * wins, so the wide frame's left edge lands where 4:3's did. */
    const int32_t margin = psx_mod_widescreen_x_margin();
    if (margin <= 0) return;
    const int32_t ilo = s_cam_lo + margin;

    /*
     * DO NOT raise the authored Xmax to make room for the inset. Tried and
     * reverted: at a stage start the travel really is a few pixels (stage 02:
     * Xmin=256, Xmax=280 against a 53 px reveal), and lifting the ceiling to
     * Xmin+margin let the camera hold 309 but rendered the frame as black
     * wedges — that bound feeds the tile fetch as well as the clamp, so raising
     * it walks the background off the end of the map. The residual black at a
     * stage's left edge is preferable to corrupt geometry.
     */
    int32_t ihi = s_cam_hi - margin;
    if (ihi < ilo) ihi = ilo;   /* left edge wins: see note above */

    const int32_t x = (int16_t)psx_mod_read_half(cam + MM8_CAM_X);
    int32_t nx = x;
    if (nx < ilo) nx = ilo;
    if (nx > ihi) nx = ihi;
    if (nx != x) psx_mod_write_half(cam + MM8_CAM_X, (uint16_t)(int16_t)nx);
}

/*
 * NOTE — do not re-add a render-time scroll write.
 *
 * An earlier version clamped the scroll at the entry of the two background
 * builders (func_800F90D4 / func_800F98D8) to force the inset through. Those
 * run once PER LAYER — ~5 calls a frame — so rewriting the scroll there moved
 * the origin between layers and the frame rendered as black wedges. The scroll
 * must be biased once, at its source, which is the clamp routine above.
 */

static void mm8_widescreen_activate(void) {
    gpu_ws_mmx6_set_freshfix(0);
    (void)psx_mod_set_fixed_display_aspect(16u, 9u);
}

/*
 * Spawn-window widen (func_80101C54).
 *
 * MM8 activates set-table objects by testing each entry's position against a
 * rectangular window passed in $a0..$a3 (Xmin, Xmax, Ymin, Ymax):
 *
 *     slt v0, Xmin, entryX     ; spawn requires Xmin < entryX
 *     slt v0, entryX, Xmax     ;           and entryX < Xmax
 *
 * That window is sized for the 320 px view, so with the widescreen reveal the
 * player can already see ground the game has not populated yet and enemies pop
 * in mid-screen. Push the X bounds out by the same per-side margin the renderer
 * reveals, so activation happens just off the WIDE edge exactly as it did just
 * off the 4:3 edge. Only the X axis moves: the reveal is horizontal.
 *
 * Identity at 4:3 (margin 0). Stateless — the arguments are recomputed by the
 * caller every frame, so there is nothing to accumulate or restore.
 */
static int32_t mm8_clamp_s16(int32_t v) {
    if (v < -32768) return -32768;
    if (v >  32767) return  32767;
    return v;
}

static void mm8_widescreen_spawn_window(struct CPUState* cpu, uint32_t address) {
    (void)address;
    const int32_t margin = psx_mod_widescreen_x_margin();
    if (margin <= 0) return;

    const int32_t x_min = (int16_t)(uint16_t)(cpu->gpr[4] & 0xFFFFu);
    const int32_t x_max = (int16_t)(uint16_t)(cpu->gpr[5] & 0xFFFFu);
    if (x_min >= x_max) return;                 /* degenerate / unexpected */

    cpu->gpr[4] = (uint32_t)mm8_clamp_s16(x_min - margin);
    cpu->gpr[5] = (uint32_t)mm8_clamp_s16(x_max + margin);
}

PSX_MOD_CONSTRUCTOR(mm8_register_widescreen_plugin) {
    (void)psx_mod_register_activation_plugin(
        "mm8.widescreen", mm8_widescreen_activate);
    /* Needs [recompiler] mod_function_entry_funcs = ["0x801023BC"] so the
     * generated code calls psx_mod_function_entry at that address. */
    (void)psx_mod_register_function_entry_plugin(
        "mm8.widescreen", 0x801023BCu, mm8_widescreen_camera_inset);
    (void)psx_mod_register_function_entry_plugin(
        "mm8.widescreen", 0x80101C54u, mm8_widescreen_spawn_window);
}
