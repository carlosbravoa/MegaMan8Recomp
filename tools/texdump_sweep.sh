#!/usr/bin/env bash
# texdump_sweep.sh — whole-game texture coverage (ROADMAP B10).
#
# Builds ONE merged texture dump for the HD texture pack from:
#   1. the PAC files themselves (tools/pac_texpack.py --all --sprites): every
#      background tile of every stage / menu / demo / ending with its palettes
#      and map draw counts, plus Mega Man's strip cells (in-game + weapon
#      palettes) and the bosses' texel ids — deterministic, no play needed;
#      names.tsv (human names per texel id) rides along into the pack;
#   2. headless play-through dumps (texture_dump armed) of what a script can
#      reach: cold boot title/menus, the developer stage-select warp into stages
#      00–03 with a walk/jump/shoot loop, and every savestate slot given
#      (--slot N, repeatable; default: the slots present in saves/scph1001);
# then merges everything (texpack.py merge) and, unless --no-pack, regenerates
# the starter pack at game-assets/textures/pack (texpack.py starter, 2x by
# default: the identity skeleton to repaint) and prints coverage.
#
#   bash tools/texdump_sweep.sh [--slot N ...] [--frames 900] [--scale 2] [--no-pack]
#                               [--skip-pacs] [--skip-play] [--out build-debug/texdumps]
#
# Needs the debug build (script mode). Sprites of stages a script cannot reach
# only come from real play: run the game with PSX_TEXTURE_DUMP=<dir> while you
# play and drop that directory into the merge (`texpack.py merge` accepts any
# number of dumps).
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
out=$root/build-debug/texdumps; frames=900; scale=2; do_pack=1; do_pacs=1; do_play=1; slots=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --slot) slots+=("$2"); shift 2 ;;
        --frames) frames=$2; shift 2 ;;
        --scale) scale=$2; shift 2 ;;
        --no-pack) do_pack=0; shift ;;
        --skip-pacs) do_pacs=0; shift ;;
        --skip-play) do_play=0; shift ;;
        --out) out=$2; shift 2 ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
exe=$root/build-debug/MegaMan8_Recompiled
[ -x "$exe" ] || { echo "needs build-debug (see CLAUDE.md)" >&2; exit 1; }
mkdir -p "$out"
if [ "${#slots[@]}" -eq 0 ]; then
    for f in "$root"/saves/scph1001/state_800C0B3C_slot*.pst; do
        [ -f "$f" ] || continue
        s=${f##*slot}; s=${s%.pst}; slots+=("$((10#$s))")
    done
fi
bios=${MM8_BIOS:-$root/game-assets/psx-bios-SCPH1001/scph1001.bin}
disc=$root/game-assets/disc; [ -f "$disc/disc.toml" ] || disc="$root/game-assets/Mega Man 8 (USA)/Mega Man 8 (USA).cue"
START='{"cmd":"press","buttons":65527,"frames":4}'
RIGHT_JUMP_FIRE='{"cmd":"press","buttons":16351,"frames":36}'   # Right + Cross + Square, active-low
RIGHT='{"cmd":"press","buttons":65503,"frames":8}'
DOWN='{"cmd":"press","buttons":65471,"frames":8}'
CROSS='{"cmd":"press","buttons":49151,"frames":4}'
walk_loop() {   # $1 = iterations of (walk/jump/shoot 36 frames, wait 24)
    local s="" i
    for i in $(seq 1 "$1"); do s="$s;$RIGHT_JUMP_FIRE;wait:24"; done
    printf '%s' "$s"
}
menu_loop() {   # cursor around a menu: right/down/cross with waits
    local s="" i
    for i in $(seq 1 "$1"); do s="$s;$RIGHT;wait:20;$DOWN;wait:20"; done
    printf '%s' "$s"
}
run_dump() {    # $1 = name, $2 = script (without the arm/stats/quit), $3 = extra env (optional)
    local name=$1 script=$2
    local D=$out/$name
    rm -rf "$D"; mkdir -p "$D"
    local S
    S="{\"cmd\":\"texture_dump\",\"op\":\"arm\",\"dir\":\"$D\"};expect:\"ok\":true;$script;{\"cmd\":\"texture_dump\",\"op\":\"stats\"};quit"
    echo "== $name" >&2
    ( cd "$root" && env ${3:-} PSX_SCRIPT_LOG="$D/script.log" timeout 1500 "$exe" --game "$root/game.toml" --disc "$disc" --bios "$bios" \
        --renderer software --headless --script "$S" > "$D/run.log" 2>&1 ) || echo "   (run exited $?)" >&2
    grep -o '"unique_texels":[0-9]*' "$D/script.log" | tail -1 >&2 || true
}

dumps=()
if [ "$do_pacs" = 1 ]; then
    echo "== PAC tiles (offline)" >&2
    python3 "$root/tools/pac_texpack.py" "$out/pacs" --all --sprites | tail -1 >&2
    dumps+=("$out/pacs")
fi
if [ "$do_play" = 1 ]; then
    # cold boot: logo/intro movies (skipped), title, menu
    run_dump title "wait:240;$START;wait:240;$START;wait:240;$START;wait:240;$START;wait:240;$START;wait:400$(menu_loop 6);wait:60"
    dumps+=("$out/title")
    # developer stage-select warp (docs/STAGE_SELECT.md): stages 00-03 work
    mkdir -p "$root/build-debug/mods"
    for st in 0 1 2 3; do
        cat > "$root/build-debug/mods/state.toml" <<EOF
format_version = 2

[[feature]]
package_id = "mm8.developer.stage-select"
id = "stage-select"
enabled = true
[feature.values]
stage = "$st"
EOF
        run_dump "stage0$st" "wait:240;$START;wait:240;$START;wait:240;$START;wait:240;$START;wait:240;$START;wait:600;$START;wait:180;$START;wait:180;$CROSS;wait:180;$START;wait:180;$CROSS;wait:300$(walk_loop $((frames / 60)))$(walk_loop 20)"
        dumps+=("$out/stage0$st")
    done
    rm -f "$root/build-debug/mods/state.toml"
    # savestates
    for sl in "${slots[@]}"; do
        run_dump "slot$sl" "wait:30;{\"cmd\":\"savestate\",\"op\":\"load\",\"slot\":$sl};expect:\"ok\":true;wait:30$(walk_loop $((frames / 90)))$(menu_loop 4);wait:120"
        dumps+=("$out/slot$sl")
    done
fi
echo "== merge" >&2
python3 "$root/psxrecomp/tools/texpack.py" merge "$out/all" "${dumps[@]}" | tail -1 >&2
if [ "$do_pack" = 1 ]; then
    echo "== starter pack" >&2
    rm -rf "$root/game-assets/textures/pack"
    python3 "$root/psxrecomp/tools/texpack.py" starter "$out/all" "$root/game-assets/textures/pack" --scale "$scale" | tail -1 >&2
    python3 "$root/psxrecomp/tools/texpack.py" coverage "$root/game-assets/textures/pack" "$out"/*/textures.tsv | tail -2 >&2
fi
echo "done: dumps in $out (merged: $out/all)" >&2
