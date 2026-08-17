# Disc identity — Mega Man 8 (USA)

Format: **bin/cue, 3 tracks — Track 01 MODE2/2352 data + Track 02/03 CDDA
audio, NTSC-U**. Keep the full multi-track Redump cue. Do **not** convert to a
2048-byte "cooked" ISO — that discards the Mode-2 Form-2 XA sectors the game
streams its `MOVIE/*.STR` MDEC movies from, and drops the CD-DA tracks
entirely.

| Field | Value |
|-------|-------|
| Title | Mega Man 8 (USA) |
| Serial | SLUS-00453 (file `SLUS_004.53`) |
| Volume ID | MEGAMAN8 |
| Publisher | CAPCOM CO.,LTD. |
| Region string | Sony Computer Entertainment Inc. for North America area |
| Tracks | 01 MODE2/2352 data · 02 AUDIO · 03 AUDIO (each in its own `.bin`) |
| Track 01 size | 334,209,792 bytes |
| Track 01 MD5 | `4e9e6dcf27ea0e15c5f4d1f93c800378` |
| Track 01 SHA-1 | `21616c788d6bfc4a16c944a4cda1a1862b8bcda8` |
| Track 02 size / MD5 | 47,030,592 / `a75dcbb5c831a966c47563e7ea4150c9` |
| Track 03 size / MD5 | 37,396,800 / `2d7b5e8e94a91bf5423b2356f6a34863` |
| `.cue` MD5 | `0ee27bb92ce2cd8ccd69ca46e80234f7` |
| TOC fingerprint (`psxrecomp-toc-v1`) | `a5fbcb9c5df446f906aa6c37b6c0e793efe693f24a77daa4de00dc29f16684ad` |

Verified 2026-08-15: locally computed MD5 + SHA-1 + sizes + serial with
`psxrecomp/tools/new_project_layout/probe_disc.py` (the same digests are
recorded in `game.toml` `[prepare_disc]` and `catalog_identity.json`). Local
copy lives at `game-assets/Mega Man 8 (USA)/` (gitignored). Verify a future
dump is byte-identical before blaming a regression.

`SYSTEM.CNF`:

```
BOOT = cdrom:\SLUS_004.53;1
TCB = 4
EVENT = 16
STACK = 801FFF00
```

Boot EXE: `SLUS_004.53` (LBA 23) — PS-EXE header (little-endian):
- entry (pc0):   `0x800C0B3C`
- initial $gp:   `0x00000000` (not preset — the game sets $gp at runtime)
- load address:  `0x800C0000`
- text size:     `0x00113000` (1,126,400 bytes) → end of text `0x801D3000`
- data/bss:      addr 0, size 0 (all zero in header)
- initial $sp:   `0x801FFFF0` (PS-EXE header stack_base; SYSTEM.CNF STACK = 801FFF00)
- EXE file size: 1,128,448 = 2048-byte header + text

Note the unusually high load address: the EXE occupies `0x800C0000..0x801D3000`,
leaving `0x80010000..0x800BFFFF` for streamed data/overlays.

On-disc layout of note (data track):
- `SLUS_004.53` — boot EXE (the static recomp target)
- `OVL/DEMO.BIN`, `OVL/STAGE00.BIN` … `OVL/STAGE0D.BIN` (15 files, 15–136 KB)
  — streamed code overlays loaded into RAM and executed per stage. Out of scope
  for the static EXE recompile; captured by the runtime's overlay-cache
  pipeline (dirty-RAM capture → `compile_overlays.py` shards).
- `STDATA/*.PAC` (48 archives: `STAGE00..0D[B].PAC`, `BOSS*.PAC`, `PLAYER.PAC`,
  `SELECT.PAC`, `LABO.PAC`, `WILY.PAC`, `PDEMO00..04.PAC`, `ENDING.PAC`, …) —
  stage / character asset packs.
- `SOUND/PBGM00..45.PAC`, `SOUND/PCOMMON.PAC` — SPU sound banks / sequenced BGM.
- `MOVIE/CAPCOM15.STR`, `MOVIE/ROCK8_0..4.STR` — MDEC movies (Capcom logo +
  the five animated cutscenes; 2–76 MB each).
- `END1.DA` (LBA 142246) and `ZNULL.DAT` (LBA 162242) — **not data files**:
  ISO9660 records with the XA "CD-DA" attribute (0x4555) whose extents ARE
  tracks 02 and 03 (INDEX 01 of each; sizes = payload sectors × 2048). This is
  how the game addresses the Red Book audio — by the LBA in these records —
  so the multi-track cue (or the extracted tree) is required to serve them.
- Tracks 02/03 — Red Book CD-DA (19,996 / 15,900 sectors incl. 150-sector
  pregaps; both pregaps silent).
- The 149 sectors after `W_DEVIL.PAC` are empty (Mode 2, zero subheader, zero
  EDC/ECC); the very last sector of the track (LBA 142095) is an empty sector
  whose ECC was computed over the header — a burner artefact, kept raw in the
  tree as `meta/raw_142095_1.bin`.

## How the game finds files: the LBA table

`SLUS_004.53` contains **no filenames** (no `cdrom:\`, no `.PAC`/`.BIN`
strings). It reads by sector number from a table at **`0x80136F7C`**: 139
entries × 12 bytes `{u32 lba, u32 size, u32 first_word}`, one per file in ISO
directory order (SLUS, SYSTEM.CNF, 6× MOVIE/*.STR, 15× OVL/*.BIN, 71×
SOUND/*.PAC, 48× STDATA/*.PAC, END1.DA). `size` is the byte size for data
files and **sectors × 2336** for the STRs (raw DMA length); `first_word` is
the file's first 32-bit word (a load-time sanity check: `PS-X` for the EXE,
`BOOT` for SYSTEM.CNF, `5..19` for the overlays, `4` for the PBGM banks).
The disc-tree mounter patches this table when a file moves (`[disc_tree]
lba_table` in `game.toml`).

## Extracted disc tree

`bash tools/extract_disc.sh` unpacks the dump into `game-assets/disc/`
(cdrom/ = the 140 files, audio/track02-03.wav, meta/, disc.toml). The runtime
mounts the tree instead of the cue when it exists (`[disc_tree] dir`); an
untouched tree is byte-identical to the dump — `psx-disc-tree verify` compares
all 177,992 sectors — and edited/added files are served in place. See
`psxrecomp/docs/DISC_TREE.md`. The tree is copyrighted game data: gitignored
with the rest of `game-assets/`.

Disc image and extracted EXE are local-only (gitignored); recreate from the
source dump if missing (`disc/SLUS_004.53` is re-extracted by
`psxrecomp_cli.py generate` / `probe_disc.py --write-boot-exe`).
