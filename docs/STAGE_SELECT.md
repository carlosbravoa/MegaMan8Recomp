# Mega Man 8 — developer stage select

A **testing tool**, not an enhancement: start the game directly in a chosen
stage instead of playing to it. Off by default; enabling it changes behaviour,
so it ships as a `mm8.developer.*` package rather than a `mm8.enhancement.*`
one.

> **Status: partial.** Stages **00–03 work**. Stages **04–0D do not** — they
> load without crashing but never initialise into a playable scene. See
> [Limitation](#limitation-stages-040d) for exactly how far the investigation
> got, so the next session does not repeat it.

## How to turn it on

Launcher → **Mods** → *Mega Man 8 Developer Stage Select* → enable, then pick a
stage from the dropdown. Headless / scripted:

```toml
# <build dir>/mods/state.toml
format_version = 2

[[feature]]
package_id = "mm8.developer.stage-select"
id = "stage-select"
enabled = true
[feature.values]
stage = "2"
```

The runtime **rewrites this file on exit**, so a hand-edited value is discarded
when the game next quits — rewrite it before each scripted run.

## How it works

MM8 keeps the current stage index in a single byte at **`0x801C336E`**. The
stage loader **`func_801014E8`** ("StageModuleLoad") reads that byte and uses it
as `index * 4` into a table at **`0x80137A5C`**:

```
0x80137A5C: 14 entries, asset ids 0x73 .. 0x87
            ↔ OVL/STAGE00.BIN .. OVL/STAGE0D.BIN
```

The plugin (`src/mods/mm8_stage_select_plugin.c`) overrides that byte at the
loader's entry, via a function-entry hook:

```toml
[recompiler]
mod_function_entry_funcs = [..., "0x801014E8"]
```

It is deliberately **one-shot**: after the first load the override retires and
the game's own progression takes over, so boss doors, stage-select returns and
Wily transitions behave normally afterwards. That gives "start here" semantics
rather than "lock every load to this stage".

Because the hook site is emitted into generated C, adding it required a
**regen**; changing only the selected stage does not.

## Verification

All four working stages, cold boot, widescreen on:

| stage | index read back | frame | camera | dispatch misses | content |
|---|---|---|---|---|---|
| 00 | 0 | 426×240 | 309 | 0 | 6226/4800 |
| 01 | 1 | 426×240 | 309 | 0 | 5894/4800 |
| 02 | 2 | 426×240 | 309 | 0 | 5884/4800 |
| 03 | 3 | 426×240 | 309 | 0 | 5884/4800 |

("content" = sampled non-black points; the sample grid is finer than 4800 in the
horizontal direction, so values above it just mean "a full scene".)

Separately worth recording: a 14-stage tour confirmed **every** stage's overlay
loads and runs with **0 dispatch misses** and no crash. Whatever is wrong with
04–0D is game-state initialisation, **not** recompilation coverage.

## Limitation: stages 04–0D

Symptom: HUD over black, `life = 0` (player never initialised), `playerX` frozen
at 416, camera frozen at 309, no CD activity. Sampled content ~68/4800 (the HUD
alone) versus ~5900 for a real scene.

What was tried and **ruled out**:

1. **The loader's path flag.** `func_801014E8` opens with
   `lbu v0,[0x801C3374]; beq v0,zero,0x80101584` — with the flag clear the
   loader takes a fixed path (through pointer `0x80137840`) that never consults
   the stage table. Forcing the flag to 1 *does* initialise the player
   (`life` 0 → 40), which looked promising, but measured across all 14 stages it
   **does not make 04–0D render** and it **regresses stage 03** (content
   5884 → 1393). It is therefore deliberately not done.

2. **Where the index goes.** With the flag set, `0x801C336E` reads back as **0**
   rather than the requested value — so the byte is a *derived copy*, not the
   source of truth. Write-tracing it during boot found three writers, all
   storing 0:

   | pc | ra |
   |---|---|
   | `0x800FF740` | `0x800FF734` |
   | `0x80100A90` | `0x80100928` |
   | `0x80102A48` | `0x80100CC0` |

   At least one runs *after* the loader-entry hook.

Conclusion: the entry state the real stage-select menu establishes is **larger
than this one byte** — most likely a small block of progression state. Nearby
RAM at boot reads `0x801C3360..0x801C3380` =
`0000000000680200006802000000060002000101...`, which is the obvious next thing
to diff between a working stage 00 boot and a natural in-game arrival at a later
stage.

**Suggested next step:** reach a later stage by playing (or by save/load, which
is confirmed working), snapshot `0x801C3300..0x801C3400`, then diff against the
same range at a cold boot. Replaying that delta at the loader entry is far more
likely to succeed than continuing to guess at individual bytes.

## Stage labels

The dropdown currently labels choices by overlay file (`Stage 04
(OVL/STAGE04.BIN)`) rather than by robot master, because the overlay-index →
identity mapping has not been confirmed from the binary. Naming them from
memory of the game would violate the project's evidence rule, so they stay
mechanical until the stage-name strings or the stage-select menu's own table is
located.
