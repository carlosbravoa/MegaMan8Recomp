# Portable Linux package

`bash tools/package_portable.sh` builds a folder you can copy to any x86-64
Linux PC and run with `./MegaMan8.sh`: no toolchain, no python, no SDL or
framework install, no disc in the drive, nothing to install at all. Saves and
settings are written back inside the folder, so it is the installation —
copy it, back it up, keep it on a USB stick.

```sh
bash tools/package_portable.sh                    # dist/MegaMan8-portable/  (~875 MB)
bash tools/package_portable.sh --tar              # + .tar.zst (~600 MB)
bash tools/package_portable.sh --with-textures --with-movies   # + HD packs (~2.4 GB)
bash tools/package_portable.sh --skip-build --skip-shards      # repack fast
```

`dist/` and `build-portable/` are gitignored: a package contains game data and
a console BIOS and must never be committed or shared.

## What makes it self-contained

| need | how |
|---|---|
| SDL3, libchdr, zlib users, ImGui | already linked into the binary (SDL3 is a static build) |
| libstdc++ / libgcc | linked statically (`-static-libstdc++ -static-libgcc`), so the target's C++ runtime version cannot matter — and cannot clash with the one the GPU driver loads |
| glibc | the target's is used when it is new enough; otherwise the launcher re-execs against the copy in `lib/` (`ld-linux-x86-64.so.2`, `libc`, `libm`, `libz`). The required version is recorded at package time in `lib/glibc-required` |
| OpenGL / X11 / Wayland | deliberately NOT bundled: these must be the target's own driver stack. SDL dlopens them at run time. `--renderer software` needs no GPU path at all |
| the game | `game-assets/disc/` — the extracted disc tree (`psxrecomp/docs/DISC_TREE.md`), so no bin/cue and no drive |
| BIOS | `bios/` (your dump, plus OpenBIOS as a fallback) |
| recompiled overlay code | `cache/` — the shards for OVL/*.BIN, precompiled for *this* binary. Without them the overlays still run, interpreted; with them nothing needs gcc or python on the target |
| where data lives | `game.toml` keeps relative paths; a `.gitignore` marker in the package root is what anchors them there (the runtime walks up for `.gitignore`/`.git`/`CMakeLists.txt` to find the "project root") and stops the search escaping if the folder is unpacked inside a git checkout |

## What the packaging script does

1. Builds `build-portable/` with the static C++ runtime flags.
2. Merges the overlay capture store (`overlay_captures.json` **plus** its `.d/`
   history — the compiler takes one list, and the plain json holds only the
   last session) and compiles any shard that is missing. Already-built shards
   are skipped, so it is incremental; a shard that fails to compile just means
   that overlay runs interpreted.
3. Copies only the cache generation whose codegen hash matches this binary — a
   dev tree accumulates one directory per emitter change.
4. Copies assets, mods, BIOS, the disc tree, and writes `game.toml` with the
   autocompile command removed (it needs python and the recompiler) and the HD
   packs disabled unless asked for.
5. Bundles the glibc fallback and writes `MegaMan8.sh` + `README.txt`.

## Verified

* Runs from a scrubbed environment (`env -i`, foreign working directory):
  boots to the Capcom logo and the intro FMV, **1435 shards loaded from the
  package's own cache**, `dispatch_interp_fallback = 0`, no autocompile
  attempts, saves written inside the package.
* Windowed OpenGL from the same scrubbed environment: context created on the
  system's Mesa, FMV presenting at 1280×960.
* `MM8_FORCE_BUNDLED_LIBC=1` (the old-distro path) boots identically against
  the bundled loader.
* `ldd` on the packaged binary: `libc`, `libm`, `libz`, `libOpenGL`,
  `libGLdispatch` only — no libstdc++, no libgcc_s, no SDL.

## Target requirements

x86-64 Linux with a desktop session (X11 or Wayland) and working OpenGL
drivers — or run `./MegaMan8.sh --renderer software`. glibc: whatever
`lib/glibc-required` says (2.43 for a package built here), older is handled by
the bundled copy.

## Notes

* The disc tree is copied exactly as it is in `game-assets/disc/`, including
  any modifications — right now that means the Japanese FMVs in `MOVIE/` and
  the original US ones kept in `MOVIE.old/` (280 MB). Delete the backup from
  the *source* tree first if you want a smaller package.
* Bookmarks (`saves/bookmarks/*.pst`) are not copied; drop them into the
  package's `saves/bookmarks/` to get the launcher's "Start at" row there.
* Re-run the script after any change to the game or the framework — the
  binary and its shard cache must come from the same build.
