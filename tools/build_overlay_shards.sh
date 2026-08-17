#!/usr/bin/env bash
# build_overlay_shards.sh — compile MM8's captured OVL/*.BIN overlays into
# native Linux .so shards, offline.
#
# The runtime records every streamed overlay it executes into
# <exe dir>/overlay_captures.json (private — verbatim game code, never share
# it) and loads shards back from <exe dir>/cache/SLUS-00453/. The in-session
# autocompile spawner is Windows-only in the framework today, so on Linux this
# script IS the compile step: run it after a play session, then relaunch.
#
# Usage: bash tools/build_overlay_shards.sh [--captures FILE] [--out CACHE_DIR]
#                                           [--jobs N] [--force] [--check]
#   defaults: captures = build-release/overlay_captures.json
#             out      = build-release/cache
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=${MM8_BUILD_DIR:-build-release}
captures=${OVERLAY_CAPTURES:-"$root/$build_dir/overlay_captures.json"}
out_dir=${OVERLAY_CACHE_DIR:-"$root/$build_dir/cache"}
cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)
jobs=${BUILD_JOBS:-$(( cores > 4 ? cores - 2 : 2 ))}
force=0
check=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --captures) captures=$2; shift 2 ;;
        --out) out_dir=$2; shift 2 ;;
        --jobs) jobs=$2; shift 2 ;;
        --force) force=1; shift ;;
        --check) check=1; shift ;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ -f "$captures" ] || { echo "overlay captures not found: $captures" >&2; exit 1; }

fw=$root/psxrecomp
recompiler=$root/build-recompiler/psxrecomp-game
if [ ! -x "$recompiler" ]; then
    echo "emitters not built — running psxrecomp/tools/ci/build_emitters.sh" >&2
    (cd "$root" && bash psxrecomp/tools/ci/build_emitters.sh)
fi

args=(
    --captures "$captures"
    --game-toml "$root/game.toml"
    --recompiler "$recompiler"
    --runtime-include "$fw/runtime/include"
    --project-root "$root"
    --out-dir "$out_dir"
    --compiler gcc
    --gcc "$(command -v gcc)"
    --cps
    --jobs "$jobs"
)
[ "$force" = 0 ] || args+=(--force)
[ "$check" = 0 ] || args+=(--check)
python3 "$fw/tools/compile_overlays.py" "${args[@]}"
[ "$check" = 0 ] || exit 0

game_id=$(sed -n 's/^[[:space:]]*id[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$root/game.toml" | head -1)
shard_root=$out_dir/$game_id/gcc/linux-x64
so_count=$(find "$shard_root" -name '*.so' 2>/dev/null | wc -l)
range_count=$(find "$shard_root" -name '*.ranges' 2>/dev/null | wc -l)
[ "$so_count" -gt 0 ] || { echo "overlay build produced no Linux .so shards" >&2; exit 1; }
[ "$range_count" -ge "$so_count" ] ||
    { echo "overlay build produced $so_count .so but only $range_count .ranges files" >&2; exit 1; }
echo "Linux overlay cache ready under $shard_root: $so_count .so shard(s), $range_count range manifest(s)"
