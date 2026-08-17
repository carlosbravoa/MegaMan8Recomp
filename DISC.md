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
- `END1.DA` (40 MB, LBA 142246) — streamed audio data for the ending.
- `ZNULL.DAT` — 32 MB null-padding file (disc layout filler).
- Tracks 02/03 — Red Book CD-DA (the game plays these directly through the CD
  audio path; the runtime needs the multi-track cue to serve them).

Disc image and extracted EXE are local-only (gitignored); recreate from the
source dump if missing (`disc/SLUS_004.53` is re-extracted by
`psxrecomp_cli.py generate` / `probe_disc.py --write-boot-exe`).
