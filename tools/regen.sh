#!/usr/bin/env bash
# regen.sh — regenerate the recompiled C for Mega Man 8 (SLUS-00453).
#
# Config-driven: game.toml describes exe / seeds / out_dir. Wraps the framework
# CLI so BIOS backends (OpenBIOS + optional SCPH1001) and the game C are always
# regenerated together against the emitters in build-recompiler/.
#
# Usage:  bash tools/regen.sh [--game-only] [--force-bios] [extra psxrecomp_cli args]
#   --game-only   run psxrecomp-game directly (skip BIOS + disc prepare); use
#                 after seed / annotation edits when the framework did not move.
#
# Env: MM8_BIOS=/path/to/SCPH1001.BIN  (default: game-assets/psx-bios-SCPH1001/scph1001.bin)
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

game_only=0
force_bios=()
extra=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --game-only) game_only=1; shift ;;
        --force-bios) force_bios=(--force-bios); shift ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) extra+=("$1"); shift ;;
    esac
done

recompiler=build-recompiler/psxrecomp-game
if [ ! -x "$recompiler" ]; then
    echo "regen: emitters not built — running psxrecomp/tools/ci/build_emitters.sh" >&2
    bash psxrecomp/tools/ci/build_emitters.sh
fi

if [ "$game_only" = 1 ]; then
    exec "$recompiler" --config game.toml "${extra[@]}"
fi

disc=$(sed -n 's/^[[:space:]]*disc[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' game.toml | head -1)
[ -n "$disc" ] || { echo "regen: no [game] disc in game.toml" >&2; exit 1; }
[ -f "$disc" ]  || { echo "regen: disc not found: $disc (see DISC.md)" >&2; exit 1; }

bios=${MM8_BIOS:-game-assets/psx-bios-SCPH1001/scph1001.bin}
bios_args=()
if [ -f "$bios" ]; then
    bios_args=(--bios "$bios")
else
    echo "regen: no retail BIOS at $bios — generating OpenBIOS backend only" >&2
fi

python3 psxrecomp/psxrecomp_cli.py generate \
    --config game.toml --project-root . --disc "$disc" \
    "${bios_args[@]}" "${force_bios[@]}" --no-toolchain-download "${extra[@]}"

# psxrecomp_cli.py runs psxrecomp-bios directly and does not write the
# emitter fingerprint stamp that runtime.cmake's staleness check compares
# against (tools/regen_bios.sh does). Record it here so a fresh generate never
# configures with a spurious "BIOS generated/ is STALE" warning.
for profile in OpenBIOS SCPH1001; do
    if [ -f "psxrecomp/generated/${profile}_full.c" ]; then
        (cd psxrecomp && bash tools/bios_emitter_fingerprint.sh "bios/${profile}.toml" \
            > "generated/${profile}.emitter.sha")
    fi
done
echo "regen: done — generated/ + psxrecomp/generated/ refreshed"
