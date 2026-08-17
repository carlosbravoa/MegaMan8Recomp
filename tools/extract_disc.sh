#!/usr/bin/env bash
# extract_disc.sh — unpack the Mega Man 8 dump into the extracted disc tree the
# runtime mounts instead of the bin/cue (psxrecomp/docs/DISC_TREE.md).
#
#   game-assets/disc/cdrom/...       the 140 ISO9660 files (OVL/*.BIN, STDATA/*.PAC,
#                                    SOUND/*.PAC, MOVIE/*.STR raw 2336 B/sector, ...)
#   game-assets/disc/audio/track02.wav / track03.wav   the two CD-DA tracks
#   game-assets/disc/meta/           licence area, PVD, one raw postgap sector
#   game-assets/disc/disc.toml       the layout manifest
#
# Everything under game-assets/ is gitignored (it is the copyrighted game data).
# With the tree present, `bash tools/run_mm8.sh` / the launcher mount it
# ([disc_tree] dir in game.toml); files edited/replaced/added under cdrom/ are
# served in place, and a grown file is relocated with the game's LBA table
# patched. `psx-disc-tree verify` proves an untouched tree is byte-identical to
# the dump; `psx-disc-tree build` writes a bin/cue of the current tree for
# emulators.
#
# Usage:
#   bash tools/extract_disc.sh [--cue PATH] [--out DIR] [--force] [--no-verify]
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cue="$root/game-assets/Mega Man 8 (USA)/Mega Man 8 (USA).cue"
out="$root/game-assets/disc"
force=(); verify=1
while [ "$#" -gt 0 ]; do
    case "$1" in
        --cue) cue=$2; shift 2 ;;
        --out) out=$2; shift 2 ;;
        --force) force=(--force); shift ;;
        --no-verify) verify=0; shift ;;
        -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
[ -f "$cue" ] || { echo "extract_disc: cue not found: $cue" >&2; exit 1; }
python3 "$root/psxrecomp/tools/disc_tree.py" extract "$cue" "$out" "${force[@]}"
tool=""
for b in build-release build-debug; do
    [ -x "$root/$b/psx-disc-tree" ] && { tool="$root/$b/psx-disc-tree"; break; }
done
if [ "$verify" = 1 ]; then
    if [ -n "$tool" ]; then
        "$tool" verify "$out" "$cue" --game-toml "$root/game.toml"
    else
        echo "extract_disc: psx-disc-tree not built (cmake --build build-release --target psx-disc-tree); skipping the byte-identity verify" >&2
    fi
fi
echo "extract_disc: tree ready at $out — run_mm8.sh / the launcher will mount it (MM8_USE_IMAGE=1 or PSX_DISC_TREE=0 to force the bin/cue)"
