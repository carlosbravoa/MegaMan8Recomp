#include "mod_plugins.h"
#include "cpu_state.h"

#include <stdint.h>
#include <string.h>

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

/*
 * Tile-packet arena relocation (func_800F98D8 entry).
 *
 * The tile renderer bump-allocates its 16-byte GP0 packets from a pointer in
 * scratchpad (0x1F800010) that func_800F9BC8 resets every frame to one of two
 * 16 KB arenas: 0x801C73FC + (frame parity << 14). Natively 3 layers x 21
 * columns x 16 rows = 1008 packets fit the 1024 slots with nothing to spare;
 * with the 7 extra columns of the reveal a dense frame needs up to 1344, and
 * the second arena's overflow lands on 0x801CF848 — the MSET/CTRL actor array
 * — and beyond, i.e. memory corruption that surfaced as a fatal `GPU GP0
 * unknown command 0xF0` a few seconds into a scene (crash report
 * psx_last_run_report.json: packet pointer at 0x801CF52C, 0x31C below the
 * array). The centred build had the same 8-column overflow — the most likely
 * source of the black screens / lost returns of ISSUES #19 while widescreen
 * was on.
 *
 * Fix: when the pointer still holds a fresh game arena base at the FIRST tile
 * call of a frame (nothing allocated yet), point it at a 32 KB arena of our own
 * in the framework's GPU-DMA aperture (psx_mod_alloc_gpu_dma_memory: guest
 * memory whose addresses survive the 24-bit OT tags, one arena per parity so
 * the double buffering is preserved). Every packet of the frame then lives
 * there and the OT links to it as before; the game never reads the arena by
 * range. Savestates carry the aperture (BS_SEC_MODGPU). Identity at 4:3
 * (margins 0 -> no redirect), and nothing is mapped unless the mod is on.
 */
#define MM8_TILE_PKT_PTR     0x1F800010u
#define MM8_TILE_ARENA_A     0x801C73FCu
#define MM8_TILE_ARENA_B     0x801CB3FCu
#define MM8_TILE_ARENA_BYTES 0x8000u        /* 2048 packets; the reveal needs <= 1344 */

static uint32_t s_tile_arena = 0;            /* our A|B pair, 0 = not allocated */

static void mm8_widescreen_tile_arena(void) {
    if (psx_mod_widescreen_x_margin_left() <= 0 &&
        psx_mod_widescreen_x_margin_right() <= 0) return;
    if (!s_tile_arena) return;
    const uint32_t ptr = psx_mod_read_word(MM8_TILE_PKT_PTR);
    if (ptr == MM8_TILE_ARENA_A)
        psx_mod_write_word(MM8_TILE_PKT_PTR, s_tile_arena);
    else if (ptr == MM8_TILE_ARENA_B)
        psx_mod_write_word(MM8_TILE_PKT_PTR, s_tile_arena + MM8_TILE_ARENA_BYTES);
}

/*
 * Camera option ("camera": left / center / smart) — where the wide window sits
 * over the world, decided from the stage's authored camera bounds (camera
 * struct 0x801D2914: camX +6, Xmax +0x1A, Xmin +0x1C; the map exists for at
 * least [Xmin, Xmax+320]):
 *
 *   left    anchor 1: the wide frame's left edge is the 4:3 left edge, the
 *           whole reveal on the right; columns beyond Xmax+320 are bordered.
 *   center  anchor 0: half the reveal each side; columns beyond the map on
 *           either side (every stage start, every room end, vertical shafts)
 *           are bordered — the classic 4:3-game-on-a-wide-screen frame.
 *   smart   anchor 3 (dynamic): L = clamp(53, 106 - dr, dl) with dl = camX -
 *           Xmin, dr = Xmax - camX: left-anchored at a stage start, opening
 *           to centred as the camera moves right (the world's left edge stays
 *           put until the window is centred), sliding to right-anchored as the
 *           end of the room approaches; a room with no horizontal travel sits
 *           centred with borders both sides. The game logic uses the widest
 *           reveal each side can reach, so the window's position never changes
 *           what spawns, lives or is on-screen.
 *
 * Voids (border columns) for any L: left = max(0, L - dl), right =
 * max(0, (106 - L) - dr). Reported each world frame from the tile-renderer
 * hook; non-world frames (menus) are centred by the framework and unbordered.
 */
#define MM8_LAYER0_CAMX_ 0x801D291Au
#define MM8_CAM_X_MAX 0x801D292Eu   /* camera struct + 0x1A */
#define MM8_CAM_X_MIN 0x801D2930u   /* camera struct + 0x1C */

static int s_camera_mode = 3;        /* 1 left, 0 center, 3 smart */

static void mm8_widescreen_place_window(void) {
    const int32_t extra = psx_mod_widescreen_extra();
    if (extra <= 0) return;
    const int32_t camx = (int16_t)psx_mod_read_half(MM8_LAYER0_CAMX_);
    const int32_t xmin = (int16_t)psx_mod_read_half(MM8_CAM_X_MIN);
    const int32_t xmax = (int16_t)psx_mod_read_half(MM8_CAM_X_MAX);
    /* Transitional camera-struct states (menu open/close wipes, scroll-zone
     * handoffs) briefly hold inconsistent bounds; trusting such a frame
     * flashed a fully bordered centred frame mid-play. Rule: report NON-ZERO
     * border columns only once the bounds have been STABLE for a while — a
     * genuine no-travel room (a boss arena, xmin == xmax == camX) holds its
     * bounds for minutes and passes after the short delay (behind the door
     * wipe); a transition flaps them frame to frame and is held out
     * indefinitely. camX outside the bounds is never sane: hold. */
    static int32_t s_prev_xmin = 0x7FFFFFFF, s_prev_xmax = 0x7FFFFFFF;
    static int32_t s_prev_camx = 0x7FFFFFFF;
    static int32_t s_stable = 0;
    static int32_t s_camx_moved = 0;    /* camX changed while these bounds live */
    if (camx < xmin - 32 || camx > xmax + 32 || xmax < xmin) {
        s_stable = 0;                                   /* not sane: hold */
        s_camx_moved = 0;
        s_prev_xmin = s_prev_xmax = 0x7FFFFFFF;
        return;
    }
    if (xmin == s_prev_xmin && xmax == s_prev_xmax) {
        if (s_stable < 1000) s_stable++;
        if (camx != s_prev_camx) s_camx_moved = 1;
    } else {
        s_stable = 0;
        s_camx_moved = 0;
        s_prev_xmin = xmin; s_prev_xmax = xmax;
    }
    s_prev_camx = camx;
    int32_t dl = camx - xmin, dr = xmax - camx;
    if (dl < 0) dl = 0;
    if (dr < 0) dr = 0;
    /* Parallax layers run out of map sooner than the camera bounds say: every
     * layer's map starts at Xmin but a far layer scrolls at a fraction f of
     * the camera (intro: 1, 1/2, 1/4 — scroll_L = Xmin + f_L*(camX-Xmin)), so
     * it has only f_L*dl of map to the left of its own edge and f_L*dr to the
     * right. Take the tightest layer: the window opens at the slowest layer's
     * pace and no layer is ever asked for columns it does not have (the
     * 14 px black strip at the top-left of a centred frame near a stage start
     * was the sky layer's map edge). Layers off (+0 == 0) are skipped. */
    {
        int32_t dl_eff = dl, dr_eff = dr;
        for (int L = 1; L < 3; L++) {
            const uint32_t layer = 0x801D2914u + 0x30u * (uint32_t)L;
            if (psx_mod_read_byte(layer) == 0) continue;
            const int32_t sc = (int16_t)psx_mod_read_half(layer + 6u);
            int32_t dlL = sc - xmin;
            if (dlL < 0) dlL = 0;
            if (dlL > dl) dlL = dl;
            if (dlL < dl_eff) dl_eff = dlL;
            /* Right slack scales with the observed parallax ratio — which is
             * only estimable once the camera has moved a real distance. At
             * dl=1 a slow layer's scroll has not ticked yet and dlL/dl reads
             * 0, which collapsed dr to 0 and flashed a fully bordered frame
             * one step off a stage start. Below the threshold leave dr alone:
             * the window is pinned near the left edge there anyway. */
            if (dl >= 32) {
                int32_t drL = (int32_t)((int64_t)dr * dlL / dl);
                if (drL < dr_eff) dr_eff = drL;
            }
        }
        dl = dl_eff; dr = dr_eff;
    }
    int32_t L;
    if (s_camera_mode == 1) L = 0;
    else if (s_camera_mode == 0) L = extra / 2;
    else {
        const int32_t lo = extra - dr, hi = dl;        /* L must satisfy lo <= L <= hi */
        L = extra / 2;
        if (lo <= hi) { if (L < lo) L = lo; if (L > hi) L = hi; }
        /* else: not enough map either side — stay centred, border both */
    }
    int32_t vl = L - dl, vr = (extra - L) - dr;
    if (vl < 0) vl = 0;
    if (vr < 0) vr = 0;
    /* Borders need trusted bounds: either the camera has moved within them
     * (a live room) or they have outlasted any transition wipe (a no-travel
     * room — boss arena; menu-close wipes hold a look-alike zero-travel state
     * for ~40 frames with camX frozen, so 90 clears every wipe). */
    if ((vl > 0 || vr > 0) &&
        !(s_stable >= 10 && (s_camx_moved || s_stable >= 90))) return;
    psx_mod_widescreen_set_window(s_camera_mode == 3 ? L : -1, vl, vr);
}

static void mm8_widescreen_activate(void) {
    gpu_ws_mmx6_set_freshfix(0);
    (void)psx_mod_set_fixed_display_aspect(16u, 9u);
    if (!s_tile_arena)
        s_tile_arena = psx_mod_alloc_gpu_dma_memory(2u * MM8_TILE_ARENA_BYTES, 16u);
    {
        char v[32];
        s_camera_mode = 3;
        if (psx_mod_option_value("mm8.enhancement.widescreen", "widescreen", "camera", v, (uint32_t)sizeof v)) {
            if (!strcmp(v, "left")) s_camera_mode = 1;
            else if (!strcmp(v, "center")) s_camera_mode = 0;
            else if (!strcmp(v, "smart")) s_camera_mode = 3;
        }
        psx_mod_widescreen_set_anchor(s_camera_mode);
    }
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
    mm8_widescreen_tile_arena();
    mm8_widescreen_place_window();
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
