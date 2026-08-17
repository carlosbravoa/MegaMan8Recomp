#!/usr/bin/env bash
# demo_recolor_megaman.sh — the smallest end-to-end customisation you can SEE:
# recolour Mega Man's in-game palette (PLAYER.PAC section 2, CLUT 0) through
# the PNG round trip and serve it from the disc tree.
#
#   bash tools/demo_recolor_megaman.sh            # apply: blues become oranges (R<->B swap)
#   bash tools/demo_recolor_megaman.sh --restore  # put the pristine PLAYER.PAC back
#
# Then `bash tools/run_mm8.sh`, GAME START -> intro stage: Mega Man is orange.
# (Use a cold boot or a skip point taken at the TITLE screen: a skip point saved
# inside a stage already holds the old palette in RAM/VRAM.)
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tree=$root/game-assets/disc
pac=$tree/cdrom/STDATA/PLAYER.PAC
work=$root/build-release/demo_recolor
[ -f "$tree/disc.toml" ] || { echo "no disc tree at $tree — run: bash tools/extract_disc.sh" >&2; exit 1; }
if [ "${1:-}" = --restore ]; then
    if [ -f "$work/PLAYER.orig.PAC" ]; then
        cp "$work/PLAYER.orig.PAC" "$pac"; echo "restored pristine PLAYER.PAC"
    else
        echo "no saved original; re-extract with: bash tools/extract_disc.sh --force" >&2; exit 1
    fi
    python3 "$root/psxrecomp/tools/disc_tree.py" status "$tree" | tail -1
    exit 0
fi
mkdir -p "$work"
[ -f "$work/PLAYER.orig.PAC" ] || cp "$pac" "$work/PLAYER.orig.PAC"
rm -rf "$work/player"
python3 "$root/tools/pac_gfx.py" extract "$work/PLAYER.orig.PAC" "$work/player" --palette-type 2 >/dev/null 2>&1
python3 - "$work/player/palette_block.png" <<'EOF'
import sys
from PIL import Image
p = sys.argv[1]
im = Image.open(p).convert("RGB")
for i in range(1, 16):                       # CLUT 0 = entries 0..15 (0 stays transparent)
    r, g, b = im.getpixel((i, 0))
    im.putpixel((i, 0), (b, g, r))           # swap R<->B: Mega Man's blues -> oranges/reds
im.save(p)
EOF
python3 "$root/tools/pac_gfx.py" pack "$work/player" "$pac" --pac "$work/PLAYER.orig.PAC"
python3 "$root/psxrecomp/tools/disc_tree.py" status "$tree" | tail -1
echo "now: bash tools/run_mm8.sh   (GAME START -> intro stage; --restore undoes it)"
