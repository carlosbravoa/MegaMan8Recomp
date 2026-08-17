#!/usr/bin/env bash
# texpack_parity.sh — software vs OpenGL parity of the HD texture pack
# (psxrecomp/tools/texpack_parity.py, docs/TEXTURE_PACKS.md B11) with the MM8
# paths filled in. Needs the debug build and a display (the OpenGL half is a
# windowed run; the software half is headless).
#
#   bash tools/texpack_parity.sh [--slot N ...] [--pack DIR] [--scale 2] [--settle 200] [extra args]
#
# Default: slots 12 (title menu, ~400 pack images on screen), 1 (stage), 3.
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
slots=(); pack=$root/game-assets/textures/pack; extra=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --slot) slots+=(--slot "$2"); shift 2 ;;
        --pack) pack=$2; shift 2 ;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) extra+=("$1"); shift ;;
    esac
done
[ "${#slots[@]}" -gt 0 ] || slots=(--slot 12 --slot 1 --slot 3)
[ -x "$root/build-debug/MegaMan8_Recompiled" ] || { echo "needs build-debug (cmake -S . -B build-debug -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo && cmake --build build-debug --target psx-runtime)" >&2; exit 1; }
[ -d "$pack" ] || { echo "no pack at $pack (texpack.py starter ...)" >&2; exit 1; }
disc=$root/game-assets/disc; [ -f "$disc/disc.toml" ] || disc="$root/game-assets/Mega Man 8 (USA)/Mega Man 8 (USA).cue"
exec python3 "$root/psxrecomp/tools/texpack_parity.py" \
    --exe "$root/build-debug/MegaMan8_Recompiled" --game "$root/game.toml" \
    --bios "${MM8_BIOS:-$root/game-assets/psx-bios-SCPH1001/scph1001.bin}" --disc "$disc" \
    --pack "$pack" --cwd "$root" --settle 200 --out "$root/build-debug/texpack_parity" "${slots[@]}" "${extra[@]}"
