#!/usr/bin/env bash
# play.sh — launch Mega Man 8 (release build, with launcher).
#
#   ./play.sh                 launcher, then game
#   ./play.sh --no-launcher   straight into the game
#   ./play.sh --debug         dev build (build-debug, TCP debug server :4545)
#
# Thin wrapper over tools/run_mm8.sh (which picks the disc source, BIOS and
# per-title exe); all arguments are passed through.
exec bash "$(dirname -- "$0")/tools/run_mm8.sh" "$@"
