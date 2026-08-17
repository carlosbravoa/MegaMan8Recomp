# Mega Man 8 — actor structure

Decoded from Capcom's own debug-menu field printers, which are still linked
into the retail build. Regenerate at any time:

```sh
python3 tools/analyze_symbols.py --actor-struct
```

## Why this is trustworthy

Each printer walks one actor and emits its fields one at a time, in a rigidly
regular shape:

```mips
lbu $a1, 0x46($s0)          ; load the field
lui/addiu $a0, "muteki:%4x" ; its name, as a format string
jal printf_lib
```

The **load offset is the field offset** and the **format string is the field
name**, both straight out of the binary — no inference. The one convention
assumed is that the actor pointer arrives in `$a0` and is kept in `$s0`, which
holds across all five printers (some are fall-through continuations that reuse
`$s0` without re-establishing it).

Names are Capcom's, mostly romaji abbreviations. Types come from the load width
(`lbu` → `u8`, `lh` → `s16`, `lw` → `u32`); *signedness of `lw` fields is the
load's, not necessarily the field's* — `pos_x`/`speedx` are near-certainly
signed fixed-point, but the printers use `%8x`, so treat the type column as
"how the debug menu read it".

## Layout

| Offset | Size | Type | Field | Reading |
|---|---|---|---|---|
| `+0x00` | 1 | u8 | `beflag` | behaviour flag |
| `+0x01` | 1 | u8 | `routn0` | routine index 0 — the state machine |
| `+0x02` | 1 | u8 | `routn1` | routine index 1 (sub-state) |
| `+0x03` | 1 | u8 | `routn2` | routine index 2 |
| `+0x04` | 1 | u8 | `routn3` | routine index 3 |
| `+0x05` | 1 | u8 | `inscrn` | on-screen flag |
| `+0x06` | 1 | u8 | `id` | actor id |
| `+0x07` | 1 | u8 | `tye` | type |
| `+0x08` | 4 | — | *(unknown)* | not printed by any printer |
| `+0x0C` | 4 | u32 | `pos_x` | X position (likely 16.16 fixed) |
| `+0x10` | 4 | u32 | `pos_y` | Y position |
| `+0x14` | 4 | u32 | `speedx` | X velocity |
| `+0x18` | 4 | u32 | `speedy` | Y velocity |
| `+0x1C` | 4 | u32 | `spedgx` | X acceleration / gravity |
| `+0x20` | 4 | u32 | `spedgy` | Y acceleration / gravity |
| `+0x24` | 1 | u8 | `objcol` | object collision |
| `+0x25` | 1 | u8 | `chrdir` | facing direction |
| `+0x26` | 1 | u8 | `winflg` | window flag |
| `+0x27` | 1 | u8 | `objnum` | object number |
| `+0x28` | 4 | u32 | `seqptr` | animation-sequence pointer |
| `+0x2C` | 4 | — | *(unknown)* | not printed |
| `+0x30` | 1 | u8 | `seqnum` | sequence number |
| `+0x31` | 1 | u8 | `chrcnt` | frame counter |
| `+0x32` | 1 | u8 | `chrtyp` | character/sprite type |
| `+0x33` | 1 | u8 | `kabeat` | 壁当たり — wall collision |
| `+0x34` | 2 | s16 | `psxold` | previous X |
| `+0x36` | 2 | s16 | `psyold` | previous Y |
| `+0x38` | 4 | u32 | `scrptr` | script pointer |
| `+0x3C` | 4 | u32 | `hitptr` | **hitbox pointer** |
| `+0x40` | 1 | u8 | `norifg` | 乗り — riding/standing-on flag |
| `+0x41` | 1 | u8 | `htcdex` | hit-code X |
| `+0x42` | 1 | u8 | `htcdey` | hit-code Y |
| `+0x43` | 1 | u8 | `jmpflg` | jump flag |
| `+0x44` | 1 | u8 | `dmg_id` | damage id |
| `+0x45` | 1 | u8 | `str` | strength (damage dealt) |
| `+0x46` | 1 | u8 | `muteki` | 無敵 — invincibility timer |
| `+0x47` | 1 | u8 | `life` | **HP** |
| `+0x48` | 1 | u8 | `lockon` | lock-on |

Known extent **0x49 bytes**; the real stride is at least that and is probably
rounded up — confirm it from the actor-array walk before relying on it.

The printers are `DebugActorRoutines` (`0x801364D8`), `DebugActorPosition`
(`0x8013658C`), `DebugActorVelocity` (`0x801365D8`), `DebugActorPointers`
(`0x80136728`) and `DebugActorDamage` (`0x801367C4`).

## What this unlocks

- **`life` (+0x47) and `muteki` (+0x46)** are the practice-tool primitives —
  and the fastest route to naming gameplay code: set a `wtrace_range` over a
  live actor's `+0x47` and the debug server reports the PC that damages it.
- **`hitptr` (+0x3C)** is the entry point for a hitbox viewer; follow it to the
  hitbox format.
- **`pos_x`/`pos_y` + `inscrn`** are what a widescreen cull-widening pass has to
  reason about — the X4 template widens exactly this kind of on-screen test.
- **`routn0..3`** is the actor state machine; dumping it live while playing
  identifies behaviours far faster than reading the disassembly.

## The player actor: `0x8015E23C` — CONFIRMED at runtime

Found empirically, then matched the static lead. Snapshot RAM, hold Right,
snapshot, hold Left, snapshot; keep records whose `+0x0C` rises then falls AND
whose `seqptr`/`scrptr`/`hitptr` are all plausible RAM pointers. Across the full
2 MB of main RAM that leaves **exactly one** address — `0x8015E23C`, which is
the same global `DebugActorPointers` is handed statically.

(It reads as zeroed outside gameplay, which is why an earlier attract-mode peek
found nothing there.)

### Runtime-verified fields

| Offset | Field | Evidence observed |
|---|---|---|
| `+0x0C` | `pos_x` | 775.5 → 815.5 holding Right, → 527.0 holding Left. **16.16 fixed point.** |
| `+0x10` | `pos_y` | 441.00 → 377.41 → 441.16 across a jump arc (smaller = higher) |
| `+0x14` | `speedx` | constant **1.50 px/frame** while walking |
| `+0x18` | `speedy` | **−0.250** during ascent (negative = upward) |
| `+0x20` | `spedgy` | constant **0.250** — the gravity term |
| `+0x33` | `kabeat` | flips to **128** the instant he stops against a wall (壁当たり) |
| `+0x40` | `norifg` | **16** while standing on ground |
| `+0x43` | `jmpflg` | **1** for exactly the airborne frames, 0 otherwise |
| `+0x47` | `life` | **wrote 12 over 40 → the on-screen health bar dropped to ~30%.** Full HP = 40. |
| `+0x05` | `inscrn` | 1 while on screen |
| `+0x01`/`+0x02` | `routn0`/`routn1` | `routn1` cycles 3→4→5→0 through a jump; `routn0` stays 2 while walking |

The `life` test is causal, not correlational: the byte was *written* and the HUD
followed proportionally. That pins both the record base and the field.

### Still only decoded, not runtime-verified

Everything else in the table above — `beflag`, `routn2/3`, `id`, `tye`,
`spedgx`, `objcol`, `chrdir`, `winflg`, `objnum`, `seqptr`, `seqnum`, `chrcnt`,
`chrtyp`, `psxold`, `psyold`, `scrptr`, `hitptr`, `htcdex/y`, `dmg_id`, `str`,
`lockon`. The decode is from the debug printers and the surrounding fields all
check out, so confidence is high — but they have not been watched changing.

(`muteki` at `+0x46` **is** now confirmed — see the enemy array below: it
latches to 1 when an actor's `life` reaches 0.)

Fields at `+0x08` and `+0x2C` remain unnamed; the debug menu never printed them.

### The object arrays — CONFIRMED

The debug object viewer (`0x80135368`) indexes each category with explicit
inline arithmetic, so the bases and strides come straight out of the code
rather than from pattern-matching RAM:

| Category | Base | Stride | Index math in the binary | Status |
|---|---|---|---|---|
| **PLAYER** | `0x8015E23C` | — (single record) | `lui 0x8016; addiu -7620` | **confirmed live** |
| **ENEMY** | `0x8015B174` | **0x60** (96) | `sll v0,1; addu v0; sll 5` (×3<<5) | **confirmed live** |
| SET | `0x801B1EEC` | 0x50 (80) | `sll v0,2; addu v0; sll 4` (×5<<4) | from code; array was empty here |
| MSET / CTRL | `0x801CF848` | 0x40 (64) | `sll a0,6` | from code; see note |

**ENEMY is confirmed causally.** Walking the player from x=416 to x=815 spawned
three records at slots 0–2 with `x` = 832 / 1008 / 1008 and `y` ≈ 454 — directly
ahead of the player and in the same ground band. Firing the buster then drove
slot 0's `life` 10 → 7 → 5 → 2 → 0 (whereupon `muteki` flipped to 1), and only
*then* began draining slot 1: 12 → 9 → 7 → 4 → 2 → 0. Shots consuming the
nearest enemy first is exactly the expected behaviour, and it lands on these
precise bytes.

That also closes the last open field: **`muteki` (+0x46) is confirmed** — it
latches to 1 the moment an actor reaches 0 HP.

MSET's stride is **0x40**, which is smaller than the 0x49-byte extent the debug
printers describe — so those records genuinely do not have `muteki`/`life`/
`lockon`; anything read there belongs to the next element. `tools/actor_watch.py`
prints `-` for them rather than a neighbour's bytes.

Observationally, right after killing two enemies all 24 MSET slots held records
with `spedgy` = **0.25** — the player's exact gravity constant — and upward
velocities near −7.6, drifting sideways. That is what explosion debris looks
like, and it suggests MSET is an effects/particle pool sharing the physics
fields. Stated as an observation, not a decode: nothing has confirmed it.

Note `0x80160000` is **not** an array base, despite appearing to be one in a
first pass: it is the `lui 0x8016` half of the player's address
(`0x80160000 − 7620 = 0x8015E23C`). Any tool that tracks `lui` without its
paired `addiu` will report it wrongly.

### `hitptr` — located, format NOT decoded

`+0x3C` resolves to a live record adjacent to `scrptr` (player: `scrptr`
`0x801388D8`, `hitptr` `0x801388E0`; enemy: `hitptr` `0x801E2564`, 12 bytes
below its `scrptr`). Raw bytes, player then enemy:

```
08 13 00 03  10 0C 04 0A  0A 00 00 00  10 0C FC 0A  0A 0D EE 0C  78 00 00 00
12 0D 00 01  08 39 00 D2  06 06 00 00  08 10 00 FF  00 06 35 00  D4 00 06 06
```

It is clearly structured (small byte fields, plausible half-extents), but two
samples do not determine a layout. Decoding it properly means watching the
record change across animation frames and correlating with on-screen sprite
extents — a task in its own right, not an inference to make from a hex dump.

## Using it

```sh
# read the player live (debug build, port 4545)
python3 - <<'PY'
import json,socket,struct
s=socket.create_connection(("127.0.0.1",4545)); s.sendall(b'{"id":1,"cmd":"read_ram","addr":2148917820,"len":80}\n')
m=bytes.fromhex(json.loads(s.makefile().readline())["hex"])
print("HP", m[0x47], "x", struct.unpack_from("<i",m,0x0C)[0]/65536.0)
PY
```

`0x8015E23C` = 2148917820 decimal. Writing `+0x47` is a working god-mode /
damage primitive; `+0x0C`/`+0x10` are a teleport.
