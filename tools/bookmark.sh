#!/usr/bin/env bash
# bookmark.sh — "Start at" bookmarks for the launcher (psxrecomp/docs/BOOKMARKS.md).
#
# A bookmark is a savestate file in saves/bookmarks/<label>.pst; the launcher's
# SYSTEM card lists them under "Start at" (Normal boot / <label> ...) and the
# game resumes there right after boot. Take a savestate where you want the
# bookmark (F5-style slot save in game), then:
#
#   bash tools/bookmark.sh add <slot> "<label>"     copy slot NN (0..15) to saves/bookmarks/<label>.pst
#   bash tools/bookmark.sh add <file.pst> "<label>" copy any .pst (e.g. an F9 bundle's state.pst)
#   bash tools/bookmark.sh list                     what the launcher will show
#   bash tools/bookmark.sh rm "<label>"
#   bash tools/bookmark.sh run "<label>"            headless smoke: boot, resume, screenshot
#
# Labels are file names: prefix them to order ("01 Tengu Man", "02 Clown Man").
# Bookmarks hold game memory: share them privately, never commit them.
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
bm=$root/saves/bookmarks
slots=$root/saves/scph1001
mkdir -p "$bm"
cmd=${1:-list}
case "$cmd" in
    add)
        src=${2:?slot number or .pst path}; label=${3:?label}
        if [[ "$src" =~ ^[0-9]+$ ]]; then
            f=$(printf '%s/state_800C0B3C_slot%02d.pst' "$slots" "$src")
        else f=$src; fi
        [ -f "$f" ] || { echo "no savestate at $f" >&2; exit 1; }
        cp "$f" "$bm/$label.pst" && echo "bookmark '$label' <- $f" ;;
    list)
        ls -1 "$bm"/*.pst 2>/dev/null | sed 's|.*/||;s|\.pst$||' | sed 's/^/  /' || true
        [ -n "$(ls -A "$bm" 2>/dev/null)" ] || echo "  (none — bash tools/bookmark.sh add <slot> \"<label>\")" ;;
    rm)
        rm -v "$bm/${2:?label}.pst" ;;
    run)
        label=${2:?label}; f="$bm/$label.pst"; [ -f "$f" ] || { echo "no bookmark '$label'" >&2; exit 1; }
        out=$root/build-debug/bookmark_run; mkdir -p "$out"
        exec bash "$root/tools/mm8_headless.sh" --build-dir build-debug --slot -1 --out "$out" \
            --script "wait:300;{\"cmd\":\"screenshot\",\"path\":\"$out/frame.png\"};expect:\"ok\":true;quit" -- --start-state "$f" ;;
    *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
