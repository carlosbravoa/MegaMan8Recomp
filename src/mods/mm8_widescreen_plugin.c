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
 * Camera option ("camera": left / center / smart) and the void (border) widths.
 *
 * Both are decided from the STAGE'S OWN TILE MAP, not from the camera's travel
 * bounds. The bounds only say where the camera may scroll in the current zone,
 * which is not where the map has content: at the intro's final boss (and in
 * every locked room / cutscene) the zone collapses to a point while the stage
 * continues both ways, and the old bounds-based estimate read that as "no map
 * either side" and framed a 4:3 picture with both borders. Layer scrolls were
 * an equally bad proxy: a parallax layer's map need not start where layer 0's
 * does (the intro's underground band starts at tile column 128).
 *
 * The renderer's own lookup, mirrored here (func_800F98D8 / func_800F99F8):
 *
 *   tile column   = (layer camX + screen x) >> 4        (camX at layer+6)
 *   tile row      = (layer camY >> 4) + 0..16           (camY at layer+8)
 *   block id      = byte  [blockmap_L + (tilecol>>4) + ((tilerow>>4)&31)*32]
 *   tile entry    = half  [0x80171C3C + blockid*512 + ((tilecol&15) + (tilerow&15)*16)*2]
 *   entry == 0    -> nothing is drawn there (the emitter skips it)
 *
 * A 16-px slab beyond the 4:3 view is EMPTY when every enabled layer's entries
 * are 0 over the visible rows; `cl` / `cr` are how many px of content adjoin
 * the view on each side (capped at the reveal). From those:
 *
 *   smart   L = clamp(extra/2, extra-cr, cl): left-anchored while only the
 *           right has map (stage start), centred once both sides do, right-
 *           anchored when the map runs out on the right (a stage's end, the
 *           boss room) — with no borders in any of those cases.
 *   center  L = extra/2, left  L = 0.
 *   voids   vl = max(0, L - cl), vr = max(0, (extra-L) - cr): only the part of
 *           the reveal that has no map is bordered, on the side it is missing,
 *           and a room with map on neither side (a closed 4:3 arena) gets the
 *           symmetric frame.
 *
 * Presentation only: the reveal budget the game logic sees never changes.
 */
#define MM8_LAYER_BASE      0x801D2914u   /* camera/layer structs, stride 0x30 */
#define MM8_LAYER_STRIDE    0x30u
#define MM8_LAYERS          3
#define MM8_BLOCKMAP_BASE   0x8016EF34u   /* layer 0 block map; +0x400 per layer */
#define MM8_BLOCKMAP_STRIDE 0x400u
#define MM8_TILE_TABLE      0x80171C3Cu   /* 16x16-tile blocks of 512 bytes */
#define MM8_VIEW_W          320

static int s_camera_mode = 3;        /* 1 left, 0 center, 3 smart */

/* Does layer L draw any tile in world tile column `tc`, over the rows the
 * view shows? (The renderer walks 16 rows from camY>>4; 17 covers the split.) */
static int mm8_tilecol_has_content(int L, int32_t tc, int32_t tr0) {
    if (tc < 0) return 0;
    const int32_t bc = tc >> 4;
    if (bc < 0 || bc > 31) return 0;
    const uint32_t bmap = MM8_BLOCKMAP_BASE + MM8_BLOCKMAP_STRIDE * (uint32_t)L;
    int32_t last_br = -1;
    uint32_t bid = 0;
    for (int r = 0; r <= 16; r++) {
        const int32_t tr = tr0 + r;
        const int32_t br = (tr >> 4) & 0x1f;
        if (br != last_br) {
            bid = psx_mod_read_byte(bmap + (uint32_t)(bc + br * 32));
            last_br = br;
        }
        const uint32_t ti = (uint32_t)((tc & 15) + (tr & 15) * 16);
        if (psx_mod_read_half(MM8_TILE_TABLE + bid * 512u + ti * 2u) != 0) return 1;
    }
    return 0;
}

/* Pixels of background adjoining the 4:3 view on one side (-1 left, +1 right),
 * capped at `extra`. Exact: a layer's content ends on a world tile boundary,
 * which the camera's sub-tile offset turns into an exact screen position. */
static int32_t mm8_content_px(int side, int32_t extra) {
    int32_t best = 0;
    for (int L = 0; L < MM8_LAYERS; L++) {
        const uint32_t layer = MM8_LAYER_BASE + MM8_LAYER_STRIDE * (uint32_t)L;
        if (psx_mod_read_byte(layer) == 0) continue;                /* layer off */
        const int32_t cx = (int16_t)psx_mod_read_half(layer + 6u);
        const int32_t tr0 = (int16_t)psx_mod_read_half(layer + 8u) >> 4;
        int32_t px = 0;
        if (side < 0) {
            for (int32_t tc = cx >> 4; px < extra; tc--) {
                if (!mm8_tilecol_has_content(L, tc, tr0)) break;
                px = cx - tc * 16;                       /* to this column's left edge */
            }
        } else {
            for (int32_t tc = (cx + MM8_VIEW_W) >> 4; px < extra; tc++) {
                if (!mm8_tilecol_has_content(L, tc, tr0)) break;
                px = (tc + 1) * 16 - (cx + MM8_VIEW_W);  /* to its right edge */
            }
        }
        if (px > best) best = px;                        /* any layer covering counts */
    }
    return best > extra ? extra : best;
}

/* Is this scene's background drawn from the tile map at all? A room built
 * only from sprites/quads (a cutscene stage, an all-black interior) would read
 * as "empty everywhere" and get framed on both sides, which is exactly the
 * failure the bounds-based estimate used to produce. Sampling three columns
 * INSIDE the 4:3 view answers it: if the view itself has no tiles, this scene
 * is not tile-backed and we make no claim about its edges. */
static int mm8_scene_is_tiled(void) {
    for (int L = 0; L < MM8_LAYERS; L++) {
        const uint32_t layer = MM8_LAYER_BASE + MM8_LAYER_STRIDE * (uint32_t)L;
        if (psx_mod_read_byte(layer) == 0) continue;
        const int32_t cx = (int16_t)psx_mod_read_half(layer + 6u);
        const int32_t tr0 = (int16_t)psx_mod_read_half(layer + 8u) >> 4;
        for (int32_t sx = 40; sx < MM8_VIEW_W; sx += 120)
            if (mm8_tilecol_has_content(L, (cx + sx) >> 4, tr0)) return 1;
    }
    return 0;
}

static void mm8_widescreen_place_window(void) {
    const int32_t extra = psx_mod_widescreen_extra();
    if (extra <= 0) return;
    if (!mm8_scene_is_tiled()) {          /* no evidence either way: no borders */
        psx_mod_widescreen_set_window(s_camera_mode == 3 ? extra / 2 : -1, 0, 0);
        return;
    }
    const int32_t cl = mm8_content_px(-1, extra);
    const int32_t cr = mm8_content_px(+1, extra);
    /* A map's edge tiles are usually partly transparent art (the intro fades
     * out over two columns), so the last column that HAS a tile is not painted
     * to its edge. SHOW two tiles less than measured — no black sliver ever
     * leads the window — but COVER only what is measured, so a border never
     * eats painted art. Deep inside a map both saturate and neither matters.
     *
     * Peak-hold with a slow decay: a column-wide hole in a map (a doorway, a
     * pit that reaches the top) must not yank the window for the frames the
     * camera passes it; a real approach to a map's end still moves it, just
     * over ~a second. The border widths stay instantaneous (the runtime's own
     * settle rule keeps them from flashing). */
    #define MM8_EDGE_FADE_PX 32
    static int32_t hl = 0, hr = 0;
    const int32_t nl = cl > MM8_EDGE_FADE_PX ? cl - MM8_EDGE_FADE_PX : 0;
    const int32_t nr = cr > MM8_EDGE_FADE_PX ? cr - MM8_EDGE_FADE_PX : 0;
    hl = nl > hl ? nl : (hl > 2 ? hl - 2 : 0);
    hr = nr > hr ? nr : (hr > 2 ? hr - 2 : 0);
    const int32_t sl = hl, sr = hr;

    int32_t L;
    if (s_camera_mode == 1) L = 0;
    else if (s_camera_mode == 0) L = extra / 2;
    else if (cl + cr >= extra) {
        /* The map can fill the whole wide frame: any L in [extra-cr, cl]
         * shows no void. Aim for centred (and, inside that freedom, for not
         * leading with a map's edge tile), then clamp into the interval —
         * which is what anchors the window left at a stage start (cl = 0) and
         * right where the map ends (cr = 0). */
        int32_t aim = extra / 2;
        if (aim > sl) aim = sl;
        L = aim;
        if (L < extra - cr) L = extra - cr;
        if (L > cl) L = cl;
        if (L < 0) L = 0;
        if (L > extra) L = extra;
    } else {
        /* Narrower than the wide frame (a closed room): show all the map there
         * is and split what is missing evenly, so the frame stays symmetric. */
        L = cl + (extra - cl - cr) / 2;
        (void)sr;
    }
    int32_t vl = L - cl, vr = (extra - L) - cr;
    if (vl < 0) vl = 0;
    if (vr < 0) vr = 0;
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
