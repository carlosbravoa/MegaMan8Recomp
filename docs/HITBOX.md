# Mega Man 8 — hitbox format

`actor+0x3C` (`hitptr`) points at a **4-byte** record. The format below is
decoded from the collision routine itself, `func_801076CC` at `0x801076CC`
(13 callers) — i.e. from the code that consumes it, which is the strongest
available evidence.

```c
struct HitBox {        /* 4 bytes */
    int8_t half_w;     /* +0x00  half-width,  sign-extended on use */
    int8_t half_h;     /* +0x01  half-height, sign-extended on use */
    int8_t off_x;      /* +0x02  X offset from the actor's origin  */
    int8_t off_y;      /* +0x03  Y offset from the actor's origin  */
};
```

Consecutive boxes are 4 bytes apart — two enemies sharing a type were seen with
`hitptr` `0x801E2564` and `0x801E2568`, i.e. adjacent records in a per-type
table.

## The overlap test

`func_801076CC(A /*$a0*/, B /*$a1*/)` returns whether two actors' boxes
intersect. Reconstructed from the disassembly:

```c
/* Positions are read as the HIGH halfword of the 16.16 fixed-point fields —
   lh 0x0E(actor) is the integer pixel part of pos_x (+0x0C), lh 0x12 of
   pos_y (+0x10). The whole test runs in integer pixels. */

int bx = (B->chrdir & 0x40) ? (B->x - 1) - B->hit->off_x
                            :  B->x     + B->hit->off_x;
int relX = bx - A->x;
relX -= (A->chrdir & 0x40) ? ~A->hit->off_x : A->hit->off_x;

int by = (B->chrdir & 0x80) ? (B->y - 1) - B->hit->off_y
                            :  B->y     + B->hit->off_y;
int relY = by - A->y;
relY -= (A->chrdir & 0x80) ? ~A->hit->off_y : A->hit->off_y;

int sumW = A->hit->half_w + B->hit->half_w;
int sumH = A->hit->half_h + B->hit->half_h;

if (abs(relX) > sumW) return 0;      /* slt: miss when sum < |rel| */
if (abs(relY) > sumH) return 0;
/* hit */
*(s16*)0x801C7384 = sumW - abs(relX);   /* X penetration depth */
*(s16*)0x801C7388 = sumH - abs(relY);   /* Y penetration depth */
```

Three things worth noting:

- **`chrdir` (+0x25) carries the flip flags.** Bit `0x40` mirrors horizontally,
  bit `0x80` vertically. Confirmed live: the player reads `chrdir = 0x40` while
  walking right (`speedx = +1.50`) and `0x00` while walking left — so `0x40` is
  the facing bit, and the boxes are authored for the unmirrored (left-facing)
  orientation. A mirrored actor's offset is applied as `(pos − 1) −
  off` for the far actor and as `~off` (= `−off − 1`) for the near one; the
  `−1` is the usual mirror-about-a-pixel-boundary correction.
- **`half_w`/`half_h` are half-extents**, not full sizes — the test is the
  standard AABB `|rel| < hwA + hwB`.
- **On a hit the routine writes penetration depths** to `0x801C7384` (X) and
  `0x801C7388` (Y). Those are the collision-response push-out values.

## Observed boxes

Read live from the intro stage (`tools/actor_watch.py`):

| Actor | `hitptr` | half_w | half_h | off_x | off_y | box |
|---|---|---|---|---|---|---|
| Player (Mega Man) | `0x801388E0` | 8 | 19 | 0 | 3 | 16 × 38 px, centred 3 px low |
| Enemy type A | `0x801E2568` | 8 | 57 | 0 | −46 | 16 × 114 px, centred 46 px high |
| Enemy type B | `0x801E2564` | 18 | 13 | 0 | 1 | 36 × 26 px |

Note the player's box lives in the main EXE (`0x801388E0`) while the enemies'
live at `0x801E2xxx` — inside the **streamed stage overlay** (`OVL/*.BIN` loads
at `0x801D8000`+). Hitbox tables ship with the actor definitions, so enemy boxes
are per-stage data, not part of the boot EXE.

## Camera / world→screen

`screen = world − camera`, with the camera a pair of plain `s32` world-pixel
values (upper halfwords are always 0 — this is an integer, not 16.16):

| Address | Meaning |
|---|---|
| `0x8016EC0C` | camera X |
| `0x8016EC10` | camera Y |

Behaviour is the classic side-scroller camera — it clamps at the stage boundary
and otherwise locks the player at screen centre:

| player world X | camera X | screen X |
|---|---|---|
| 272 | 256 | 16 (clamped at the stage's left edge) |
| 452 | 292 | **160** |
| 633 | 473 | **160** |
| 799 | 639 | **160** |

A packed `(camY, camX)` s16 copy also lives at `0x801D2918`/`0x801D291C`.

## Verification status

**Decoded from the consumer, and collision confirmed to fire.** Specifically:

- The field roles come from the disassembly and are unambiguous — signed vs
  unsigned loads, the sign-extensions, and the `|rel| < sum` comparison all
  read directly out of `func_801076CC`.
- Boxes read live for three different actors are plausible and mutually
  consistent (a 16-px-wide box for a ~24-px-wide sprite, etc.).
- Contact was forced by writing the player's `pos_x`/`pos_y` onto an enemy. The
  result was exactly what the model predicts: `life` 40 → 36 → 33 → 30,
  `muteki` cycling 1 → 0 between hits (invincibility frames), and knockback
  (x 965 → 939 → 913). The penetration globals were **non-zero during contact
  and 0 in the frames where `muteki` was 0**.
- `chrdir`'s role was confirmed independently by watching it track the walk
  direction (see above).
- Before that, standing against the wall at x=815 the model computed
  `relX = 18` against a threshold of `16` — two pixels short of touching the
  enemy at x=832, which matches the observed "walks up to it but never
  connects".

**Visually confirmed.** With the camera (above) the boxes were drawn onto a live
frame (`tools/actor_watch.py --overlay out.png`):

- the player's 16 × 38 box wraps Mega Man's sprite exactly, origin crosshair at
  his feet;
- the `half_h = 57, off_y = −46` box wraps a **palm tree trunk** precisely —
  ground to fronds. That also resolves an earlier puzzle: the "enemy" with
  `life = 12` that blocked the player at x=815 is a *destructible palm tree*,
  which is why shooting drained its HP and why he stopped two pixels short of
  its box.

That single image confirms the hitbox fields, the flip handling, the camera, and
the 16.16 position format simultaneously.

**Still not verified:** an exact numeric match of the penetration globals to one
specific actor pair. Those two globals are rewritten by *every* collision test in
a frame (the routine has 13 callers), so their value at any sample reflects
whichever pair was tested last. Attributing them pairwise needs a
breakpoint-style trap on the routine.
