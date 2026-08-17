#!/usr/bin/env bash
# mm8_headless.sh — run Mega Man 8 headless (no window, no audio, unpaced) under
# a built-in session script and exit. The script steps are debug-server command
# lines plus wait:N / expect:substr / quit (see psxrecomp/docs/HEADLESS.md).
#
# Usage:
#   bash tools/mm8_headless.sh [--build-dir build-release] [--slot N] [--out DIR]
#                              [--filter NAME] [--frames N] [--bug-report] [--keep-open]
#                              [--script 'step;step;...'] [--script-file FILE]
#
# Defaults: load save slot 3 (intro-stage gameplay), wait 60 frames, write
# frame.png + present.png (post-filter) into --out, quit. --bug-report adds a
# telemetry bundle (saves/bugreports/<stamp>_headless). Exit code: 0 ok,
# 3 = an expect: failed, anything else = runtime failure.
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=build-release; slot=3; out=$root/build-release/headless; filter=""; frames=60
bug=0; keep=0; script=""; script_file=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --build-dir) build_dir=$2; shift 2 ;;
        --slot) slot=$2; shift 2 ;;
        --out) out=$2; shift 2 ;;
        --filter) filter=$2; shift 2 ;;
        --frames) frames=$2; shift 2 ;;
        --bug-report) bug=1; shift ;;
        --keep-open) keep=1; shift ;;
        --script) script=$2; shift 2 ;;
        --script-file) script_file=$2; shift 2 ;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
mkdir -p "$out"
if [ -z "$script" ] && [ -z "$script_file" ]; then
    script="wait:30"
    [ "$slot" -ge 0 ] && script="$script;{\"cmd\":\"savestate\",\"op\":\"load\",\"slot\":$slot};expect:\"ok\":true"
    script="$script;wait:$frames"
    [ -n "$filter" ] && script="$script;{\"cmd\":\"video_filter\",\"name\":\"$filter\"};expect:\"ok\":true"
    script="$script;{\"cmd\":\"screenshot\",\"path\":\"$out/frame.png\"};expect:\"ok\":true"
    script="$script;{\"cmd\":\"present_capture\",\"path\":\"$out/present.png\",\"companions\":0};wait:2;{\"cmd\":\"present_capture\"};expect:written"
    [ "$bug" = 1 ] && script="$script;{\"cmd\":\"bug_report\",\"trigger\":\"headless\"};wait:30"
    script="$script;{\"cmd\":\"ping\"};expect:\"ok\":true"
    [ "$keep" = 0 ] && script="$script;quit"
fi
args=(--headless)
[ -n "$script" ] && args+=(--script "$script")
[ -n "$script_file" ] && args+=(--script-file "$script_file")
export PSX_SCRIPT_LOG="$out/script.log"
: > "$PSX_SCRIPT_LOG"
exec bash "$root/tools/run_mm8.sh" --build-dir "$build_dir" "${args[@]}"
