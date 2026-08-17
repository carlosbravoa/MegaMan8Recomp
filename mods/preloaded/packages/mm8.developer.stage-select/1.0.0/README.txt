Mega Man 8 Stage Select (Developer)
===================================

A testing tool, not a gameplay feature. Default: OFF.

Enable it and pick "Start in stage" to have the game load that stage first
instead of the intro stage. The override applies ONCE, to the first stage load
after boot; afterwards the game's own progression takes over, so boss doors,
stage-select returns and Wily transitions behave normally.

How it works: MM8 stores the current stage index in one byte (0x801C336E) which
its loader (func_801014E8) uses as index*4 into a stage table at 0x80137A5C -
14 entries mapping to OVL/STAGE00.BIN .. OVL/STAGE0D.BIN. The plugin writes the
selected index at the loader's entry.

Stage 00 is the intro stage. The remaining indices are labelled by their overlay
file; see docs/STAGES.md in the project repository for what each one contains.
