#include "mod_plugins.h"

/*
 * Mega Man 8 — developer testing tools.
 *
 * Skip-intros. A cold boot spends ~2 minutes on the Capcom logo and the opening
 * FMV before the title screen is even reachable, and the Capcom reel does not
 * respond to START. That cost is paid on EVERY test run, which is the single
 * biggest drag on iterating against this title.
 *
 * The framework already knows how to drop FMVs (`[video] auto_skip_fmv`, and
 * the mod-facing psx_mod_set_auto_skip_fmv). This exposes it as a launcher
 * toggle rather than a config edit, so it can be turned on for a debugging
 * session and off for a faithful run without touching game.toml or rebuilding.
 *
 * Deliberately presentation-only: skipping a movie changes what is displayed,
 * never game state, so a run with this on reaches the same title screen the
 * faithful boot does. It stays default-off — a shipped build must play the
 * movies.
 */
static void mm8_skip_intros_activate(void) {
    (void)psx_mod_set_auto_skip_fmv(1);
}

PSX_MOD_CONSTRUCTOR(mm8_register_devtools_plugin) {
    (void)psx_mod_register_activation_plugin(
        "mm8.skip-intros", mm8_skip_intros_activate);
}
