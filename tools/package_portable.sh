#!/usr/bin/env bash
# package_portable.sh — build a self-contained, portable Linux package.
#
# The result is a directory (optionally a .tar.zst) you can copy to any x86-64
# Linux PC and run: no toolchain, no python, no SDL/framework install, no disc
# in the drive. It carries the game data (extracted disc tree), the BIOS, the
# precompiled overlay shards, and — when the target's glibc is older than this
# machine's — a private copy of glibc to run against.
#
#   bash tools/package_portable.sh [--out DIR] [--tar]
#        [--with-textures] [--with-movies] [--no-bios]
#        [--skip-build] [--skip-shards]
#
# Contents (everything resolves relative to the package, nothing points back
# at this checkout):
#   MegaMan8.sh            launcher (start here)
#   MegaMan8_Recompiled    the game (static libstdc++/libgcc)
#   game.toml .gitignore   config + the marker that anchors data paths here
#   assets/ mods/ bios/    fonts, launcher art, mod packages, OpenBIOS (+ BIOS)
#   game-assets/disc/      the extracted disc tree (cdrom/, audio/, disc.toml)
#   cache/                 precompiled overlay shards for THIS binary
#   lib/                   glibc + libz fallback, used only if needed
#   saves/                 memory cards, savestates, bookmarks (writable)
#
# The package contains game data and a console BIOS: it is for YOUR machines,
# not for sharing.
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
out=$root/dist/MegaMan8-portable
build=build-portable
with_tex=0; with_mov=0; with_bios=1; do_tar=0; do_build=1; do_shards=1
while [ "$#" -gt 0 ]; do
    case "$1" in
        --out) out=$2; shift 2 ;;
        --tar) do_tar=1; shift ;;
        --with-textures) with_tex=1; shift ;;
        --with-movies) with_mov=1; shift ;;
        --no-bios) with_bios=0; shift ;;
        --skip-build) do_build=0; shift ;;
        --skip-shards) do_shards=0; shift ;;
        --build-dir) build=$2; shift 2 ;;
        -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done
say() { printf '\n== %s\n' "$*" >&2; }

# ---- 1. the binary -----------------------------------------------------------
# Static libstdc++/libgcc: two fewer shared libraries to match on the target,
# and no chance of clashing with the one the GPU driver pulls in.
if [ "$do_build" = 1 ]; then
    say "building $build (static libstdc++/libgcc)"
    cmake -S "$root" -B "$root/$build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
          -DCMAKE_EXE_LINKER_FLAGS="-static-libstdc++ -static-libgcc" >/dev/null
    cmake --build "$root/$build" --target psx-runtime -j"$(getconf _NPROCESSORS_ONLN)"
fi
cache_root=${cache_root:-$root/build-release/cache}
exe=$root/$build/MegaMan8_Recompiled
[ -x "$exe" ] || { echo "no binary at $exe (drop --skip-build?)" >&2; exit 1; }

# ---- 2. overlay shards for THIS binary ---------------------------------------
# The runtime streams OVL/*.BIN overlays; shards compiled from captures make
# them native. They are keyed by the emitter's codegen hash, so they must be
# built with the same recompiler this binary was generated from. Without gcc
# and python on the target, this cache IS the compile step — anything missing
# still runs, interpreted.
cache_root=$root/build-release/cache
if [ "$do_shards" = 1 ]; then
    say "compiling overlay shards"
    # The runtime appends every overlay it runs to <exe>/overlay_captures.json
    # AND to the .d/ history beside it; the compiler takes ONE list, so merge
    # the whole store first — otherwise only the last session's overlay gets a
    # shard. Already-built shards are detected and skipped, so this is
    # incremental.
    merged=$root/$build/overlay_captures.merged.json
    python3 - "$root" "$merged" <<'PY'
import json, glob, os, sys
root, out = sys.argv[1], sys.argv[2]
seen, merged = set(), []
for store in (f'{root}/build-release/overlay_captures.json',
              f'{root}/build-debug/overlay_captures.json'):
    files = ([store] if os.path.exists(store) else []) + sorted(glob.glob(store + '.d/*.json'))
    for f in files:
        try: caps = json.load(open(f))
        except Exception: continue
        for cap in (caps if isinstance(caps, list) else [caps]):
            key = (cap.get('load_addr'), cap.get('size'), len(cap.get('bytes_b64', '')))
            if key in seen: continue
            seen.add(key); merged.append(cap)
json.dump(merged, open(out, 'w'))
print(f'   {len(merged)} captured overlays', file=sys.stderr)
PY
    if [ -s "$merged" ]; then
        MM8_BUILD_DIR=$build bash "$root/tools/build_overlay_shards.sh" \
            --captures "$merged" --out "$cache_root" 2>&1 | tail -6 || \
            echo "   (shard build failed — packaging the cache as it stands)" >&2
    else
        echo "   (no overlay captures yet — play once, then repackage)" >&2
    fi
fi

# ---- 3. assemble -------------------------------------------------------------
say "assembling $out"
[ -d "$out" ] && chmod -R u+w "$out" 2>/dev/null || true   # the disc tree copies in read-only
rm -rf "$out"; mkdir -p "$out"/{assets,bios,lib,saves,game-assets}
cp "$exe" "$out/MegaMan8_Recompiled"
cp -r "$root/$build/assets/." "$out/assets/" 2>/dev/null || true
cp -r "$root/$build/mods" "$out/" 2>/dev/null || true
cp "$root/$build/game_options.toml" "$out/" 2>/dev/null || true
cp "$root/psxrecomp/bios/openbios.bin" "$out/bios/" 2>/dev/null || true
cp "$root/psxrecomp/bios/OpenBIOS.LICENSE" "$out/bios/" 2>/dev/null || true

# game.toml: same file, minus the two things that only exist in a dev checkout
# (the autocompile command needs python + the recompiler; the HD packs are
# optional and huge). Paths inside stay relative — see the .gitignore marker.
python3 - "$root/game.toml" "$out/game.toml" "$with_tex" "$with_mov" <<'PY'
import sys, re
src, dst, tex, mov = sys.argv[1], sys.argv[2], sys.argv[3] == '1', sys.argv[4] == '1'
s = open(src).read()
s = re.sub(r'(?m)^overlay_autocompile_cmd\s*=.*$',
           '# overlay_autocompile_cmd: removed for the portable package (no python /\n'
           '# recompiler on the target). The shipped cache/ holds the shards.',
           s)
if not tex:
    s = re.sub(r'(?m)^texture_pack\s*=.*$', 'texture_pack = ""', s)
if not mov:
    s = re.sub(r'(?m)^fmv_pack\s*=.*$', 'fmv_pack = ""', s)
open(dst, 'w').write(s)
PY

# The runtime anchors a relative data path in game.toml at the "project root",
# which it finds by walking up for a .gitignore/.git/CMakeLists.txt marker. A
# marker here makes that root THIS directory — and stops the search escaping
# into a git checkout if the package is unpacked inside one.
cat > "$out/.gitignore" <<'EOF'
# Marker file: it makes the game resolve game.toml's relative data paths
# (game-assets/, bios/, assets/) against THIS directory. Do not delete.
EOF

say "copying game data (disc tree)"
cp -r "$root/game-assets/disc" "$out/game-assets/disc"
if [ "$with_bios" = 1 ]; then
    for b in "$root"/game-assets/psx-bios-*/*.bin; do
        [ -f "$b" ] && cp "$b" "$out/bios/" && break
    done
fi
[ "$with_tex" = 1 ] && { say "copying HD textures"; mkdir -p "$out/game-assets/textures"; cp -r "$root/game-assets/textures/pack" "$out/game-assets/textures/pack"; }
[ "$with_mov" = 1 ] && { say "copying HD movies";   mkdir -p "$out/game-assets/movies";   cp -r "$root/game-assets/movies/pack"   "$out/game-assets/movies/pack"; }

say "copying overlay shards"
# Ship ONLY the generation this binary asks for: the cache is keyed by the
# emitter's codegen hash, and a dev tree accumulates one directory per emitter
# change (hundreds of MB of shards no build will ever load again).
cg=$(sed -n 's/.*PSX_OVERLAY_CODEGEN_HASH *0x\([0-9a-f]*\)u.*/\1/p' \
      "$root/psxrecomp/runtime/include/overlay_codegen_hash.h")
shards=0
for src in "$cache_root" "$root/$build/cache"; do
    [ -d "$src" ] || continue
    for gen in "$src"/SLUS-00453/*/*/cg9_${cg}_*/; do
        [ -d "$gen" ] || continue
        rel=${gen#"$src"/}
        mkdir -p "$out/cache/$(dirname "${rel%/}")"
        cp -r "${gen%/}" "$out/cache/${rel%/}"
        shards=$(( shards + $(find "$out/cache/${rel%/}" -name '*.so' | wc -l) ))
    done
done
echo "   codegen $cg: $shards shards" >&2
[ "$shards" = 0 ] && echo "   (none — overlays will run interpreted; play once and repackage)" >&2

# ---- 4. private glibc, used only when the target's is older -------------------
# Everything else the game needs at runtime is either inside the binary (SDL3,
# libchdr, zlib users, libstdc++) or must come from the target (the GPU driver:
# libGL/libEGL/X11/Wayland are dlopened and MUST be the system's).
say "bundling libc fallback"
for lib in $(ldd "$exe" | awk '/=>/ {print $3} /ld-linux/ {print $1}' | sort -u); do
    case "$lib" in
        *libGL*|*libOpenGL*|*libGLdispatch*|*libGLX*|*libEGL*|*libX11*|*libwayland*|*libdrm*) continue ;;
        "" ) continue ;;
    esac
    cp -L "$lib" "$out/lib/" 2>/dev/null || true
done
need=$(objdump -T "$exe" | grep -o 'GLIBC_[0-9.]*' | sed 's/GLIBC_//' | sort -uV | tail -1)
echo "$need" > "$out/lib/glibc-required"
echo "   needs glibc >= $need (bundled: $(ls "$out/lib" | tr '\n' ' '))" >&2

# ---- 5. launcher -------------------------------------------------------------
cat > "$out/MegaMan8.sh" <<'LAUNCH'
#!/usr/bin/env sh
# Mega Man 8 — portable launcher. Run this; everything it needs is beside it.
#
#   ./MegaMan8.sh                  launcher, then the game
#   ./MegaMan8.sh --no-launcher    straight into the game
#   ./MegaMan8.sh --renderer software   if OpenGL misbehaves on this machine
#
# Saves, memory cards and settings are written next to this file, so the whole
# folder is the installation: copy it, back it up, or move it to a USB stick.
set -eu
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DIR"

BIOS=""
for b in bios/scph1001.bin bios/SCPH1001.BIN bios/scph5500.bin bios/*.bin; do
    case "$b" in *openbios.bin) continue ;; esac
    [ -f "$b" ] && BIOS=$b && break
done
[ -n "$BIOS" ] && set -- --bios "$BIOS" "$@"

# glibc: use the system's when it is new enough, else the copy in lib/. The GPU
# driver keeps coming from the system either way (that is what must match your
# hardware); a newer glibc underneath it is fine, an older one is not.
NEED=$(cat lib/glibc-required 2>/dev/null || echo 0)
HAVE=$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')
older() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$1" ] && [ "$1" != "$2" ]; }
LOADER=lib/ld-linux-x86-64.so.2
if [ -n "${MM8_FORCE_BUNDLED_LIBC:-}" ] || { [ -x "$LOADER" ] && [ -n "$HAVE" ] && older "$HAVE" "$NEED"; }; then
    [ -z "${MM8_QUIET:-}" ] && echo "MegaMan8: using the bundled glibc (system $HAVE, needs $NEED)" >&2
    exec "$LOADER" --library-path "$DIR/lib" "$DIR/MegaMan8_Recompiled" \
         --game "$DIR/game.toml" --disc "$DIR/game-assets/disc" "$@"
fi
exec "$DIR/MegaMan8_Recompiled" --game "$DIR/game.toml" --disc "$DIR/game-assets/disc" "$@"
LAUNCH
chmod +x "$out/MegaMan8.sh"

cat > "$out/README.txt" <<EOF
Mega Man 8 — portable Linux build (x86-64)
==========================================

Run:  ./MegaMan8.sh

That is all. No installation, no toolchain, no disc: the game data, the BIOS
and the precompiled game code are all inside this folder, and saves/settings
are written back into it (saves/). Copy the whole folder anywhere.

Requirements on the target PC
  * x86-64 Linux with a desktop session (X11 or Wayland)
  * working OpenGL drivers — or run ./MegaMan8.sh --renderer software
  * glibc $need or newer; if yours is older the launcher automatically runs
    against the copy in lib/ (no action needed)

Options
  ./MegaMan8.sh --no-launcher          skip the launcher UI
  ./MegaMan8.sh --renderer software    no GPU path at all
  Widescreen, HD textures/movies, video filters: launcher -> Display / Mods

Contents
  MegaMan8_Recompiled   the recompiled game (SDL3 linked in)
  game-assets/disc/     the game's data, extracted from your disc
  bios/                 PlayStation BIOS (+ OpenBIOS as a fallback)
  cache/                precompiled overlay code for this exact binary
  lib/                  glibc fallback for older distributions
  saves/                memory cards, savestates, bookmarks

This folder contains game data and a console BIOS dumped from hardware you
own. Keep it to your own machines.
EOF

du -sh "$out" >&2
if [ "$do_tar" = 1 ]; then
    say "creating tarball"
    tarball=$out.tar
    if command -v zstd >/dev/null; then
        tar -C "$(dirname "$out")" -cf - "$(basename "$out")" | zstd -T0 -3 -o "$tarball.zst" -f
        ls -lh "$tarball.zst" >&2
    else
        tar -C "$(dirname "$out")" -czf "$tarball.gz" "$(basename "$out")"
        ls -lh "$tarball.gz" >&2
    fi
fi
say "done: $out  (run ./MegaMan8.sh there)"
