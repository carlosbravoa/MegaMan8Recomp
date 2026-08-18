#!/usr/bin/env bash
# run_mm8.sh — launcher for the MegaMan8Recomp dev build (Linux).
# Bakes the BIOS + disc paths so no interactive picker is needed and the
# space-containing .cue path is passed as ONE quoted argument.
#
# Usage:  bash tools/run_mm8.sh [--build-dir build-release] [--no-launcher]
#                              [--openbios] [--renderer software|opengl|vulkan]
#                              [--headless] [--debug] [--script 'steps'] [--script-file F]
#                              [-- extra runtime args]
#   --no-launcher  boot straight into the game (scripted / debug runs)
#   --openbios     do not pass --bios (run on the bundled OpenBIOS backend)
#   --debug        shorthand for --build-dir build-debug (RelWithDebInfo build,
#                  TCP debug server on port 4545)
#   --headless     no window/audio, unpaced; combine with --script (see
#                  psxrecomp/docs/HEADLESS.md, tools/mm8_headless.sh)
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=build-release
launcher_args=()
bios_args=()
extra=()
use_openbios=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --build-dir) build_dir=$2; shift 2 ;;
        --debug) build_dir=build-debug; shift ;;
        --no-launcher) launcher_args+=(--no-launcher); shift ;;
        --headless) launcher_args+=(--headless); shift ;;
        --renderer) launcher_args+=(--renderer "$2"); shift 2 ;;
        --openbios) use_openbios=1; shift ;;
        --) shift; extra=("$@"); break ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) extra+=("$1"); shift ;;
    esac
done

# Game-specific exe name: the framework derives OUTPUT_NAME from the window
# title ("MegaMan8 Recompiled" -> MegaMan8_Recompiled) so an MM8 run never
# collides with another PSX title's process.
exe=$root/$build_dir/MegaMan8_Recompiled
game=${MM8_GAME:-$root/game.toml}   # MM8_GAME: an alternate game.toml (test variants)
bios=${MM8_BIOS:-$root/game-assets/psx-bios-SCPH1001/scph1001.bin}
# Disc source, in order: MM8_DISC (explicit image or tree), the extracted disc
# tree game-assets/disc/ (tools/extract_disc.sh; psxrecomp/docs/DISC_TREE.md)
# unless MM8_USE_IMAGE=1, else the bin/cue dump.
image="$root/game-assets/Mega Man 8 (USA)/Mega Man 8 (USA).cue"
tree=$root/game-assets/disc
if [ -n "${MM8_DISC:-}" ]; then
    disc=$MM8_DISC
elif [ "${MM8_USE_IMAGE:-0}" != 1 ] && [ -f "$tree/disc.toml" ]; then
    disc=$tree
else
    disc=$image
fi

[ -x "$exe" ]  || { echo "exe not found: $exe (build first — see CLAUDE.md)" >&2; exit 1; }
[ -e "$disc" ] || { echo "disc not found: $disc" >&2; exit 1; }
echo "run_mm8: disc source: $disc" >&2
if [ "$use_openbios" = 0 ]; then
    if [ -f "$bios" ]; then
        bios_args=(--bios "$bios")
    else
        echo "run_mm8: BIOS not found at $bios — falling back to OpenBIOS" >&2
    fi
fi

# Only ever stop THIS title's process, never the generic psx-runtime. Match the
# full command line: the kernel comm name is truncated to 15 chars, so a plain
# `pkill -x MegaMan8_Recompiled` never matches.
pkill -f "MegaMan8_Recompiled( |\$)" 2>/dev/null || true

cd "$root"
exec "$exe" --game "$game" --disc "$disc" "${bios_args[@]}" "${launcher_args[@]}" "${extra[@]}"
