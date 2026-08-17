# Symbolizing Mega Man 8

How the anonymous `func_800C0B3C` soup in `generated/` gets names, what the
evidence rules are, and how to add your own findings.

## The two artifacts (they are not interchangeable)

The framework has two symbol-ish pipelines that do completely different things.
Knowing which is which saves a lot of confusion:

| | `symbols.toml` | `annotations/SLUS_004.53_annotations.csv` |
|---|---|---|
| Consumed by | `tools/sync_symbols.py` (host-side) | `psxrecomp-game` itself |
| Produces | `psx_symbols.h` — `PSX_FN_*` macros | `/* [NOTE] … */` in `generated/*.c` |
| Reaches the recompiler | **no** | **yes** |
| Renames the generated C | **no** — always `func_%08X` | no, but labels it |

So **the annotations CSV is what makes the generated source readable**;
`symbols.toml` is the machine-readable handle list for future host hooks and
mods. `tools/analyze_symbols.py --write` maintains both.

## Running it

```sh
python3 tools/analyze_symbols.py                  # report: what it found
python3 tools/analyze_symbols.py --write          # update both artifacts
python3 tools/sync_symbols.py --game MegaMan8     # symbols.toml -> psx_symbols.h
bash tools/regen.sh --game-only                   # bake notes into generated C
```

Useful for digging:

```sh
python3 tools/analyze_symbols.py --func 801014E8  # disassemble + explain one function
python3 tools/analyze_symbols.py --strings        # the whole string table w/ addresses
```

The analyzer needs `ghidra/SLUS_004.53_no_header.bin` (headerless dump; see
`ghidra/instructions.txt`) and `generated/SLUS_004.53_full.ranges` (the
recompiler's own function-boundary manifest — so run a `regen` first).

## Evidence rules

The project rule is *no guessing* (`CLAUDE.md`), so every name traces to
something in the binary. `status` uses the vocabulary from
`psxrecomp/docs/SYMBOLS.md` (`guessed | confirmed | hot`):

**`confirmed` — the binary says so.**

1. **BIOS call thunks.** Psy-Q's libapi wrappers are three instructions:
   `li $t2,0xA0|0xB0|0xC0` / `jr $t2` / `li $t1,<funcnum>`. The function number
   resolves through the documented A0/B0/C0 kernel tables (psx-spx), giving an
   exact name — `bios_memcpy`, `bios_OpenEvent`, `bios_OutdatedPadGetButtons`.
   42 found.
2. **Routines that log their own name.** The Psy-Q libraries were shipped with
   their debug output intact: `"ResetGraph:jtb=%08x,env=%08x"`,
   `"CdInit: Init failed"`, `"DrawSync(%d)..."`. The analyzer takes the leading
   identifier of any literal a routine hands to a printf-like callee. It
   requires CamelCase (at least one lowercase letter) so ALL-CAPS component
   prefixes — `"CDROM:"`, `"SPU:"`, `"DMA STATUS ERROR"` — name a subsystem, not
   a function, and are rejected.
3. **`printf` itself.** It is neither a thunk nor self-naming, so it is
   established from call sites: of 133 calls to `0x800D2B34`, 105 stage a
   format-string address in `$a0`. Cross-checks cleanly against the two
   independently-identified BIOS thunks (`bios_printf`, `bios_std_out_puts`),
   which show the same signature at lower volume.

**`guessed` — inference from what a routine prints.** Capcom left their debug
menu in the retail build, and its output is remarkably descriptive. A function
printing `"dmg_id:%4x"`, `"muteki:%4x"`, `"life:%4x"` is displaying an actor's
damage fields — solid, but it is evidence of what the routine *prints*, not a
self-declaration, so it stays `guessed`. The name is a label; the note carries
the evidence.

### The false positive worth knowing about

An address constant is **not** a string reference. `BootEntry`'s BSS clear loop
bounds its zero-fill with `0x800F75B0`, which happens to be where the literal
`"VB Trans Error!!"` lives — a looser rule confidently named the entry point
`VabTransfer`. A string now only counts when it is in an argument register
(`$a0`–`$a3`) **at a call**, which is what actually consuming a string looks
like. If you extend the analyzer, keep that discipline.

## What it found

Roughly 73 auto-derived names over 7,292 functions — deliberately the subset
that is *provable*, not a best-effort labelling of everything:

- 42 BIOS/libc thunks (`bios_*`)
- ~14 Psy-Q library routines (`ResetGraph`, `DrawSync`, `PutDispEnv`, `VSync`,
  `CdInit`, `CdRead`, `DiskError`, `CD_init`, `MDEC_rest`, `printf_lib`, …)
- ~17 game routines (`StageModuleLoad`, `GameOverLoad`, `VabTransfer`,
  `MemcardSaveFile`, and the `Debug*` family)

Plus 232 annotated functions in total — the extra ~160 carry classification
rather than a name (hardware touched, GTE usage, string vocabulary, or
"this is data, not code").

### The debug menu is the map

The single most valuable find. `0x80134FA0` (`DebugMainMenu`) roots a whole
tree — `MAINMENU` / `FLAGCHANGE` / `WORKVIEW` / `VABVIEW` — and its leaves name
**the actor struct's fields** while printing them:

| Debug field | Meaning | Printer |
|---|---|---|
| `speedx` / `speedy` / `spedgx` / `spedgy` | velocity + gravity | `DebugActorVelocity` (`0x801365D8`) |
| `dmg_id` / `str` / `muteki` / `life` | damage id, strength, invincibility (無敵), HP | `DebugActorDamage` (`0x801367C4`) |
| `scrptr` / `hitptr` / `norifg` / `htcdex` | script ptr, hitbox ptr, ride flag, hit-code index | `DebugActorPointers` (`0x80136728`) |
| `beflag` / `routn0..2` | behaviour flag, routine indices | `DebugActorRoutines` (`0x801364D8`) |
| `settbl` / `pos_x` / `pos_y` | set-table, position | `DebugActorPosition` (`0x8013658C`) |

Reading those printers gives the field offsets of Mega Man 8's actor
structure. That decode is done — 36 fields, `python3 tools/analyze_symbols.py
--actor-struct`, written up in **`docs/ACTOR_STRUCT.md`** (including what is
still unconfirmed).

Note the menu itself is **unreachable** in the retail build — its driver has no
callers and no data references (ISSUES #9). It is documentation, not a feature.

## Adding your own

Hand-written entries go **above** the `# --- BEGIN auto-derived` marker in
either file and are preserved across re-runs. The analyzer also refuses to
auto-name a `pc` that already has a hand-written `symbols.toml` entry, because
`sync_symbols.py` has no duplicate detection and two `#define func_XXXXXXXX`
aliases would collide.

Watch the CSV parser's sharp edges (`psxrecomp/recompiler/src/annotations.cpp`):

- the comma must follow the address **immediately** — `0xADDR , note` is
  silently dropped;
- `#` must be the first non-space character to start a comment;
- notes are pasted **raw** into a C block comment, so a literal `*/` inside one
  will truncate the comment and break the generated shard (the writer defangs
  it; a hand-written row is on its own);
- the line buffer is 1024 bytes;
- an address landing on a branch, a delay slot, or outside an emitted function
  is dropped without warning.

For runtime-derived discoveries — "which function writes Mega Man's health?" —
use the debug server rather than static analysis: `wtrace_range` /
`wtrace_dump` report the writing PC and `$ra`. That is how to name gameplay
code the debug menu does not cover.
