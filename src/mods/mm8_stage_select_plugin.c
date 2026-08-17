#include "mod_plugins.h"
#include "cpu_state.h"

#include <stdint.h>
#include <string.h>

/*
 * Mega Man 8 — developer stage select.
 *
 * Testing tool: start directly in a chosen stage instead of playing to it.
 *
 * MM8 keeps the current stage index in a single byte at 0x801C336E. Its stage
 * loader (func_801014E8, "StageModuleLoad") reads that byte and uses it as
 * `index * 4` into a table at 0x80137A5C which yields the stage's asset id —
 * 14 entries, 0x73..0x87, matching OVL/STAGE00.BIN .. OVL/STAGE0D.BIN.
 *
 * This plugin overrides the byte at the loader's entry, so the very first stage
 * the game loads is the selected one. It is deliberately ONE-SHOT: after the
 * first load the override retires and the game's own progression takes over, so
 * boss doors, stage-select returns and Wily transitions behave normally. That
 * gives "start here" semantics rather than "lock every load to this stage".
 *
 * Requires [recompiler] mod_function_entry_funcs to list 0x801014E8.
 * With the feature disabled nothing is registered and nothing is written.
 */
#define MM8_STAGE_INDEX_ADDR 0x801C336Eu
/*
 * NOTE for whoever continues this: stages 00..03 warp correctly with the index
 * alone; 04..0D load without crashing but never initialise into a playable
 * scene (player life stays 0, nothing draws). The loader's first branch
 * (`lbu v0,[0x801C3374]; beq v0,zero,...`) selects a fixed path over the
 * table-driven one, but forcing that flag to 1 was measured NOT to help: it
 * initialises the player (life 40) yet leaves the scene black AND regresses
 * stage 03, so it is deliberately not done here. Three routines zero the index
 * during boot (pc 0x800FF740, 0x80100A90, 0x80102A48 / ra 0x80100CC0) and at
 * least one runs after this hook, so the real entry state the stage-select menu
 * establishes is larger than this one byte. See docs/STAGE_SELECT.md.
 */
#define MM8_STAGE_LOAD_FUNC  0x801014E8u
#define MM8_STAGE_COUNT      14

#define PKG     "mm8.developer.stage-select"
#define FEATURE "stage-select"
#define OPTION  "stage"

static int s_applied = 0;

/* Selected stage index, or -1 when the option is absent/unset/out of range. */
static int mm8_selected_stage(void) {
    char value[32];
    if (!psx_mod_option_value(PKG, FEATURE, OPTION, value, (uint32_t)sizeof value))
        return -1;
    if (value[0] == '\0') return -1;

    int n = 0;
    for (const char* p = value; *p; ++p) {
        if (*p < '0' || *p > '9') return -1;      /* e.g. "off" */
        n = n * 10 + (*p - '0');
        if (n > 255) return -1;
    }
    if (n < 0 || n >= MM8_STAGE_COUNT) return -1;
    return n;
}

static void mm8_stage_select_on_load(struct CPUState* cpu, uint32_t address) {
    (void)cpu;
    (void)address;
    if (s_applied) return;
    const int stage = mm8_selected_stage();
    if (stage < 0) { s_applied = 1; return; }     /* nothing selected: retire */
    psx_mod_write_byte(MM8_STAGE_INDEX_ADDR, (uint8_t)stage);
    s_applied = 1;
}

/*
 * Activation callback. Registering one is REQUIRED, not decorative: a package's
 * [[plugin]] id must resolve through mod_plugin_registered(), which only counts
 * activation and vblank callbacks. A function-entry registration alone leaves
 * the id unresolved and the runtime refuses to launch with
 * "trusted plugin is unavailable: mm8.stage-select".
 *
 * It also does real work — clearing the one-shot latch, so enabling the feature
 * and starting a new run applies the override again.
 */
static void mm8_stage_select_activate(void) {
    s_applied = 0;
}

PSX_MOD_CONSTRUCTOR(mm8_register_stage_select_plugin) {
    (void)psx_mod_register_activation_plugin(
        "mm8.stage-select", mm8_stage_select_activate);
    (void)psx_mod_register_function_entry_plugin(
        "mm8.stage-select", MM8_STAGE_LOAD_FUNC, mm8_stage_select_on_load);
}
