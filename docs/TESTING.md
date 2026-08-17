# Mega Man 8 — testing tools

Getting to the thing you want to look at used to cost ~2 minutes of unskippable
Capcom reel and opening FMV, every run. These exist so a test run reaches a
chosen stage in about **25 seconds**.

All of them are **off by default** and live in the launcher's **Mods** page, so a
faithful run is unaffected and nothing here needs a rebuild to toggle.

## Skip point — the fast way past the intro

**Use this instead of the FMV skip.** ESC → **SET SKIP POINT HERE** snapshots
wherever you are; ESC → **GO TO SKIP POINT** returns there instantly.

Take it once at the title screen (or at the **stage select** — even better) and
every later run is: launch → ESC → *Go to skip point*. ESC works during the
intro, so you never sit through it.

It lives in a **reserved 13th save slot**, outside the player's 12, so a
developer shortcut can never overwrite a real save. It is **never applied at
boot** — nothing about how the game starts changes silently.

Staleness is handled: the snapshot is checked with `savestate_slot_compatible()`
against this build's BIOS/entry/codegen key. After a rebuild that invalidates it
you get *"Skip point is from another build"* rather than a bad restore. Take a
new one.

Verified: player X 416 → walked to 505 → restored to 416.

## Skip Intro Videos mod — works, but looks bad

Launcher → Mods → *Mega Man 8 Developer Tools* → **Skip Intro Videos**, backed by
the framework's `psx_mod_set_auto_skip_fmv()`. Cold boot → player in a stage
drops from ~2 min to **~27 s**.

⚠ **It fast-forwards the movie visibly rather than hiding it.** The framework
runs the guest uncapped during a skip and presents 1-in-30 frames "so the window
never looks hung" — but uncapped that is still tens of movie frames a second, so
you watch the whole intro in turbo. Measured: a ~2 min intro compressed to ~4 s
of playback averaging 70% bright frames.

It is off by default and superseded by the skip point above. Fixing it properly
means either suppressing those presents entirely, or configuring MM8's own
end-of-movie path (`[video] fmv_skip_total_table` / `fmv_skip_movie_id`), which
ends a movie instantly through the game's own teardown — neither is done.

Note for anyone revisiting it: MM8 **does** stream XA during the movie
(`xa_stream_active = 1` measured), so the detector is not the problem and
`fmv_skip_no_xa` is not the fix.

## Start directly in a stage

Launcher → Mods → *Mega Man 8 Developer Tools* → **Stage Select (Developer)**,
then pick from the **Start in stage** dropdown.

Overrides the first stage the game loads, so instead of arriving in the intro
stage you arrive in the chosen one. It is **one-shot**: after that first load the
game's own progression takes over, so boss doors, stage-select returns and Wily
transitions behave normally.

Stage indices are the game's own table at `0x80137A5C` (14 entries, `0x73`–`0x87`
→ `OVL/STAGE00.BIN`–`OVL/STAGE0D.BIN`). Only identities confirmed by actually
seeing them render are labelled; the rest stay mechanical rather than guessed:

| index | identity |
|---|---|
| 00 | intro stage |
| 02 | Clown Man (confirmed visually) |

Note the in-game stage-select screen can also reach **Dr. Light's Lab** (index
14). That is past the end of the 14-entry stage table and is handled by a
different code path — it is not an out-of-bounds bug, despite looking like one.

## System menu (ESC)

**ESC** opens the system menu. Up/Down move, **Enter** confirms,
**Left/Right** adjust the rows that carry a value, ESC closes. While it is open
it swallows every key, so nothing leaks through to the game behind it.

| row | behaviour |
|---|---|
| `RESUME` | close the menu |
| `GO TO SKIP POINT` | restore the skip-point snapshot (shows `(NONE SET)` until you take one) |
| `SET SKIP POINT HERE` | snapshot the current state into the reserved slot |
| `SAVE STATES` | open the save-state browser (the F7 menu) |
| `REWIND` | open rewind (the F8 view) |
| `FULLSCREEN   ON/OFF` | Enter or Left/Right toggles |
| `VOLUME       NN%` | Left/Right in 5% steps |
| `FPS DISPLAY  ON/OFF` | Enter or Left/Right toggles |
| `FILTER       NEAREST/BILINEAR` | texture filtering, switches live |
| `RESTART GAME` | clean reboot |
| `QUIT` | exit |

Every row is something the runtime already exposed as a hotkey or a config
value. The menu exists so they are discoverable without knowing the hotkeys, and
so **FILTER** can be compared live instead of by restarting with a different
config.

* **Restart Game** puts the machine back to power-on **without exiting the
  process** — the window, audio device and launcher session are untouched, so it
  restarts the GAME rather than dropping you back at the launcher. It works by
  restoring a snapshot the runtime takes of the current session ~2 s after boot,
  in a second reserved slot. Before that capture point it reports
  *"Restart unavailable yet"* rather than doing something surprising.
* **Quit** takes the same shutdown path as closing the window.

### Save / load confirmation

`S` and `L` sit next to each other, and the two mistakes are symmetric — clobber
a save, or throw away your play. So **neither fires on a single keystroke**: both
raise a banner naming the action *and* the slot (`SAVE TO SLOT 3 ?`), with
**Enter** to confirm and **Esc** to cancel. While the prompt is up it owns the
keyboard, so you cannot change slot underneath your own confirmation. The pad
path goes through the same gate (**A** confirms, **X** cancels), since A and X
are just as easy to mix up. Loading an empty slot is rejected outright — there is
nothing to confirm, and the "Slot N is empty" toast is more useful.

It reuses the save-state overlay panel, so it needed no new compositing code in
the GL, Vulkan and software present paths. It does not open while the save-state
browser or rewind is up.

⚠ **Only partly verifiable from the debug server.** The overlay is composited in
the present path, not into VRAM, so `screenshot` shows the game without it, and
Wayland blocks synthetic key injection, so ESC cannot be pressed
programmatically here.

`{"cmd":"system_menu","open":1,"sel":0}` returns the rows the menu would draw,
including their live values — that much IS asserted:

```
RESUME | SAVE STATES | REWIND | FULLSCREEN   OFF | VOLUME       100% |
FPS DISPLAY  OFF | FILTER       NEAREST | RESTART GAME | QUIT
```

The key handling and the rendering itself have only been verified by
construction and still need a human pressing ESC.

## Save states

Already a first-class runtime feature — no mod needed.

| key | action |
|---|---|
| **F7** | open the save-state menu |
| digits `1`–`9`, `0`, `-`, `=` | pick slot 1–12 |
| `S` | save to the selected slot |
| `L` | load the selected slot |
| `Enter` | load (`Shift+Enter` saves) |
| `Esc` / `Backspace` | close |
| **F8** | rewind (~12.5 s of history, 15-frame interval) |

On a pad: **Select + R1** opens the menu, **A** loads, **X** saves.

Scripted, over the debug server (port 4545 on a `--debug` build):

```jsonc
{"cmd":"savestate","op":"save","slot":1}
{"cmd":"savestate","op":"load","slot":1}
```

Save/load is refused on an LLE run (`bios_hle = false`) — the message says so
explicitly.

## Scripted runs

`tools/run_mm8.sh --debug --no-launcher` starts a build with the TCP debug server
on **4545**. Mod state for a scripted run is `<build dir>/mods/state.toml`:

```toml
format_version = 2

[[package]]
id = "mm8.developer.stage-select"

[[feature]]
package_id = "mm8.developer.stage-select"
id = "skip-intros"
enabled = true

[[feature]]
package_id = "mm8.developer.stage-select"
id = "stage-select"
enabled = true
[feature.values]
stage = "2"
```

**The runtime rewrites this file on exit**, and an unclean kill can leave it
stripped down to `format_version = 2` with every feature dropped. Write it fresh
before each scripted run and verify the run actually got what you asked for —
`grep "aspect 16:9"` in the log, or check `gpu_state.width`.

## Measurement traps

Three that cost real time in this project — check against them before trusting a
number:

* **`screenshot` is native VRAM.** Widescreen only shows up once the frame is
  actually engaged; before that you get 320x240 and will conclude widescreen is
  broken when it simply has not started. Widescreen engages at *game entry*, not
  at boot.
* **Distinct-colour count is not a blackness test.** A visually black frame
  routinely reports ~150 distinct colours from dark noise. Use mean brightness,
  or the fraction of dark pixels.
* **Contiguous dark COLUMNS miss diagonal corruption.** The wedge artifact in
  ISSUES #16 leaves most columns partially bright, so a "black bar width" metric
  reports a small number while half the screen is black. Measure the dark-pixel
  fraction over the whole frame.
