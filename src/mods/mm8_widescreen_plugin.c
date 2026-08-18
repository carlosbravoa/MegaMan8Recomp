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
 * auto_screen_x, which widens MM8's screen-extent funnel at func_800FA050),
 * the background tile-loop widen ([widescreen.bg2d]) and the runtime's wide
 * compositor, LEFT-anchored for this title ([widescreen] nw_anchor = "left":
 * the wide frame's left edge is the 4:3 left edge, the whole reveal is on the
 * right). This entry point only declares the display aspect once the player
 * opts in, so with the mod disabled the build presents native 4:3 and is
 * byte-identical to faithful.
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

static void mm8_widescreen_activate(void) {
    gpu_ws_mmx6_set_freshfix(0);
    (void)psx_mod_set_fixed_display_aspect(16u, 9u);
}

/*
 * NOTE — there is deliberately NO camera hook any more.
 *
 * With the reveal centred, the camera had to be pre-clamped ("inset") away
 * from the stage's authored bounds at every map boundary so the left reveal
 * would not show map that was never authored — and at a stage start the
 * authored travel is a few pixels (stage 02: Xmin=256, Xmax=280 against a
 * 53 px reveal), so the inset was partial, the foreground moved left of the
 * walkable area and the parallax layer still left a black column. Anchoring
 * the reveal on the left removes the problem instead of hiding it: the wide
 * frame's left edge IS the 4:3 left edge, so background, foreground and the
 * playable area line up with 4:3 by construction, and the camera is never
 * moved off the positions the game itself chose. Do not re-add a camera
 * clamp, a scroll write at the background builders (they run once per layer,
 * ~5x a frame — moving the origin between layers rendered black wedges) or a
 * raised Xmax (that bound also feeds the tile fetch).
 */

/*
 * Spawn-window shift (func_80101C54).
 *
 * MM8 activates set-table objects by testing each entry's position against a
 * rectangular window passed in $a0..$a3 (Xmin, Xmax, Ymin, Ymax):
 *
 *     slt v0, Xmin, entryX     ; spawn requires Xmin < entryX
 *     slt v0, entryX, Xmax     ;           and entryX < Xmax
 *
 * The caller (func_80101ACC) builds the window from camX with the 4:3 width
 * baked in: while scrolling right a 32 px STRIP [camX+336, camX+368) sweeps
 * ahead of the screen (16..48 px past the 320 edge), scrolling left the strip
 * is [camX-48, camX-16), and the room-entry scan (func_80101BF0) covers
 * [camX-48, camX+368) — plus the same in Y for vertical scroll. Each X bound
 * therefore describes one screen edge: a bound right of the camera's screen
 * centre is a RIGHT-edge bound and moves out by the right reveal, a bound left
 * of it by the left reveal (0 when left-anchored). A strip is thereby
 * TRANSLATED, not widened — widening it (an earlier version) let entries the
 * player had already scrolled past re-spawn while visible once their re-arm
 * timer ran out, because the 32 px sweep had become a 138 px band.
 *
 * Together with the keep-alive / inscrn edge sites in game.toml this keeps
 * the whole activation pipeline at the same distance from the WIDE edge as it
 * was from the 4:3 edge: objects spawn 16..48 px past it and are kept alive
 * to 56 px past it, so nothing pops in or out inside the reveal and the
 * order in which things come alive along a route is unchanged.
 *
 * Identity at 4:3 (margins 0). Stateless — the caller recomputes the window
 * every frame, so there is nothing to accumulate or restore.
 */
#define MM8_LAYER0_CAMX 0x801D291Au   /* camera struct 0x801D2914 + 6, s16 */

static int32_t mm8_clamp_s16(int32_t v) {
    if (v < -32768) return -32768;
    if (v >  32767) return  32767;
    return v;
}

static void mm8_widescreen_spawn_window(struct CPUState* cpu, uint32_t address) {
    (void)address;
    const int32_t ml = psx_mod_widescreen_x_margin_left();
    const int32_t mr = psx_mod_widescreen_x_margin_right();
    if (ml <= 0 && mr <= 0) return;

    const int32_t x_min = (int16_t)(uint16_t)(cpu->gpr[4] & 0xFFFFu);
    const int32_t x_max = (int16_t)(uint16_t)(cpu->gpr[5] & 0xFFFFu);
    if (x_min >= x_max) return;                 /* degenerate / unexpected */

    const int32_t centre = (int16_t)psx_mod_read_half(MM8_LAYER0_CAMX) + 160;
    const int32_t dmin = x_min < centre ? -(ml > 0 ? ml : 0) : (mr > 0 ? mr : 0);
    const int32_t dmax = x_max < centre ? -(ml > 0 ? ml : 0) : (mr > 0 ? mr : 0);
    cpu->gpr[4] = (uint32_t)mm8_clamp_s16(x_min + dmin);
    cpu->gpr[5] = (uint32_t)mm8_clamp_s16(x_max + dmax);
}

/*
 * World gate for the left anchor (func_800F98D8, the tile renderer).
 *
 * The reveal is anchored left only while the STAGE WORLD is on screen; a
 * fixed 320-wide layout is centred instead. The framework already centres
 * frames the tile renderer did not build ([widescreen] nw_anchor_gate =
 * "bg2d": the pause menu, NOW LOADING), but MM8's title and stage select are
 * built by the same renderer from their own maps, so they need the game's
 * word: the player actor (0x8015E23C, beflag at +0) exists only in a stage —
 * measured 1 from the stage's very first drawn frame (under the iris wipe,
 * before READY) through the pause menu, 0 on the title and stage select.
 * Refreshed on every renderer call, i.e. every frame either kind of screen is
 * drawn. Presentation only; identity at 4:3.
 */
#define MM8_PLAYER_ACTOR 0x8015E23Cu

static void mm8_widescreen_world_gate(struct CPUState* cpu, uint32_t address) {
    (void)cpu; (void)address;
    psx_mod_widescreen_set_world(psx_mod_read_byte(MM8_PLAYER_ACTOR) != 0);
}

PSX_MOD_CONSTRUCTOR(mm8_register_widescreen_plugin) {
    (void)psx_mod_register_activation_plugin(
        "mm8.widescreen", mm8_widescreen_activate);
    /* Needs [recompiler] mod_function_entry_funcs to list 0x80101C54 and
     * 0x800F98D8 so the generated code calls psx_mod_function_entry there. */
    (void)psx_mod_register_function_entry_plugin(
        "mm8.widescreen", 0x80101C54u, mm8_widescreen_spawn_window);
    (void)psx_mod_register_function_entry_plugin(
        "mm8.widescreen", 0x800F98D8u, mm8_widescreen_world_gate);
}
