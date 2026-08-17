# Video filters (Mega Man 8)

The filters are a framework feature — see `psxrecomp/docs/VIDEO_FILTERS.md`.
Game-side pieces:

* `game.toml` `[video] filter = "none"` (title default; the launcher's
  Display → Video filter row persists the player's pick to `settings.toml`).
* `tools/video_filter_check.py` — in-game GL-vs-CPU parity check over the debug
  server (needs `bash tools/run_mm8.sh --debug --no-launcher`; slot 3 savestate
  = intro-stage gameplay is a good static-ish frame).
* Both framework and launcher changes are parked in `upstream/` until they land
  in mstan/psxrecomp and mstan/recomp-ui.

Recommendations for MM8's 2D art: **xBR 2x/3x** for smooth outlines,
**Scale2x** for a chunkier faithful look, **Sharp** when you only want a clean
non-integer fit, **CRT** at 4x+ windows (the aperture mask is 3 px wide).
