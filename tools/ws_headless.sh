#!/usr/bin/env bash
# ws_headless.sh — widescreen check without a window (docs/WIDESCREEN.md).
#
# Enables the widescreen mod in <build>/mods/state.toml, runs the debug build
# headless (software renderer) from a bookmark / save slot / cold boot, plays an
# optional script, then captures the WIDE present (present.png = what the
# window would show, 426 px wide when engaged), the native VRAM screenshot
# (frame.png) and gpu_state's ws block (ws.json). Native-wide engages headless
# since the framework's engage step moved ahead of the headless early-out.
#
#   bash tools/ws_headless.sh [--build-dir build-debug] [--out DIR]
#        [--bookmark "Intro stage" | --slot N | --cold] [--frames N] [--off] [--camera smart|center|left]
#        [--script 'steps'] [-- runtime args]
#
# --off runs the same thing with the mod disabled (4:3 reference). Exit 3 = an
# expect: failed. The previous mods/state.toml is restored afterwards.
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=build-debug; out=""; bookmark="Intro stage"; slot=""; cold=0; frames=120; on=1; script=""; camera="smart"; extra=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --) shift; extra=("$@"); break ;;
        --build-dir) build_dir=$2; shift 2 ;;
        --out) out=$2; shift 2 ;;
        --bookmark) bookmark=$2; shift 2 ;;
        --slot) slot=$2; shift 2 ;;
        --cold) cold=1; shift ;;
        --frames) frames=$2; shift 2 ;;
        --off) on=0; shift ;;
        --camera) camera=$2; shift 2 ;;   # widescreen mod option: smart | center | left
        --script) script=$2; shift 2 ;;
        -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
[ -n "$out" ] || out=$root/$build_dir/ws_headless
mkdir -p "$out" "$root/$build_dir/mods"
state=$root/$build_dir/mods/state.toml
bak=$out/state.toml.bak
[ -f "$state" ] && cp "$state" "$bak" || rm -f "$bak"
restore() { if [ -f "$bak" ]; then cp "$bak" "$state"; else rm -f "$state"; fi; }
trap restore EXIT
cat > "$state" <<EOT
format_version = 2

[[feature]]
package_id = "mm8.enhancement.widescreen"
id = "widescreen"
enabled = $([ "$on" = 1 ] && echo true || echo false)
[feature.values]
camera = "$camera"
EOT
S="wait:$frames"
[ -n "$slot" ] && S="wait:30;{\"cmd\":\"savestate\",\"op\":\"load\",\"slot\":$slot};expect:\"ok\":true;wait:$frames"
[ -n "$script" ] && S="$S;$script"
S="$S;{\"cmd\":\"gpu_state\"};{\"cmd\":\"screenshot\",\"path\":\"$out/frame.png\"};expect:\"ok\":true"
S="$S;{\"cmd\":\"present_capture\",\"path\":\"$out/present.png\",\"companions\":0};wait:2;{\"cmd\":\"present_capture\"};expect:written;quit"
args=(--build-dir "$build_dir" --no-launcher --headless --renderer software --script "$S")
if [ "$cold" = 0 ] && [ -z "$slot" ]; then
    f=$root/saves/bookmarks/$bookmark.pst
    [ -f "$f" ] || { echo "no bookmark: $f" >&2; exit 1; }
    extra=(--start-state "$f" "${extra[@]}")
fi
export PSX_SCRIPT_LOG="$out/script.log"
: > "$PSX_SCRIPT_LOG"
set +e
bash "$root/tools/run_mm8.sh" "${args[@]}" "${extra[@]}" > "$out/run.log" 2>&1
rc=$?
set -e
grep -o '"ws":{[^}]*}' "$out/script.log" | tail -1 > "$out/ws.json" || true
grep -h "widescreen\|display aspect" "$out/run.log" | head -5 >&2
cat "$out/ws.json" >&2; echo >&2
python3 - "$out/present.png" <<'PY' >&2 || true
import sys, struct, zlib
p=sys.argv[1]
d=open(p,'rb').read()
w,h=struct.unpack('>II',d[16:24]); print(f"present.png {w}x{h}")
PY
echo "out: $out (rc=$rc)" >&2
exit $rc
