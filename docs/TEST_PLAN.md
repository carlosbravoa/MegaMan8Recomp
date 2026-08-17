# Mega Man 8 — manual test plan

A pass you can actually execute in one sitting. The core trick is **one save
state at the stage-select screen**: from there every stage is ~20 seconds away
instead of a full replay, so all 14 destinations can be covered twice (4:3 and
16:9) without replaying the intro.

**Run 4:3 first, all the way through.** It is the reference. A defect that shows
up in both modes is a game/recomp bug; one that only shows in 16:9 is a
widescreen bug. Without the 4:3 column you cannot tell them apart, and that
distinction is the whole point of the exercise.

---

## 0. Setup

Launcher → **Mods**:

| mod | Phase A (4:3) | Phase B (16:9) |
|---|---|---|
| Developer Tools → **Skip Intro Videos** | ON | ON |
| Developer Tools → **Stage Select** | OFF | OFF |
| **Widescreen (Experimental)** | **OFF** | **ON** |

Stage Select stays OFF for the main pass — you want the game's own stage-select
screen, because that is the path a player takes. It is only used in §4.

Keys you will need:

| key | action |
|---|---|
| **F7** | save-state menu — digits `1`–`9`/`0`/`-`/`=` pick slot, `S` saves, `L` loads, `Esc` closes |
| **F8** | rewind (~12.5 s) |
| **ESC** | system menu — resume, save states, rewind, fullscreen, volume, FPS, filter, restart, quit |

Slot plan — keep these fixed so the two phases stay comparable:

* **Slot 1** — stage-select screen, 4:3 pass
* **Slot 2** — stage-select screen, 16:9 pass
* **Slots 3+** — anything you want to come back to (a boss room, a bad spot)

> Save states are tied to the machine state, not to the mod set. **Do not load a
> 4:3 state while widescreen is on** — take a fresh one (slot 2) after switching.
> If something behaves oddly right after a mode switch, suspect this first.

---

## 1. Phase A — 4:3 reference pass

### 1.1 Boot

1. Launch. Confirm the Capcom reel and opening FMV are skipped.
2. Reach the title screen. **Record boot → title time.**
3. `GAME START` → play the intro stage to its end.

- [ ] Intro FMV skipped
- [ ] Title screen reachable
- [ ] Intro stage completes

### 1.2 Anchor the save

4. At the **stage-select screen** (globe with portraits): **F7 → `1` → `S`**.
5. Close the menu, then immediately **F7 → `1` → `L`** to prove the state
   restores cleanly.

- [ ] Slot 1 saved
- [ ] Slot 1 loads back to the stage-select screen

### 1.3 Sweep every destination

For **each** stage, and for **Dr. Light's Lab**:

1. Move the cursor to the destination (the right-hand panel previews it).
2. Confirm. Wait for the stage to come up.
3. Check the list below.
4. **F7 → `1` → `L`** to return to the stage select. Next destination.

Per destination, check:

- [ ] Stage renders (ground present, not black)
- [ ] Mega Man spawns and can move/jump/shoot
- [ ] Correct music starts (not the previous screen's music)
- [ ] Scroll left and right to the level's edges — no black margins, no tearing
- [ ] No visual corruption anywhere on screen
- [ ] Audio clean (no crackle/stutter)

Fill in as you go:

| # | destination (from the preview) | renders | plays | music | edges | notes |
|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |
| 6 |  |  |  |  |  |  |
| 7 |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |
| — | Dr. Light's Lab |  |  |  |  |  |

> The known-bad case to watch for: stage comes up **black with only the health
> bar**, Mega Man unable to move, **intro music still playing**. If it happens,
> stop and follow §5 before doing anything else — that state is the evidence.

### 1.4 Depth check

Pick **one** stage and play it properly for a few minutes: mid-stage, a
mini-boss if there is one, a death and respawn, a checkpoint.

- [ ] Death → respawn works
- [ ] Checkpoint restores correctly
- [ ] No slowdown or audio drift over several minutes

---

## 2. Phase B — 16:9 pass

Enable **Widescreen**, relaunch, and repeat §1 exactly — same route, same
checks — saving the stage-select state to **slot 2**.

Widescreen **engages at game entry**, not at boot: the title screen and menus may
present 4:3 and that is expected. Judge it from inside a stage.

Extra checks per destination, on top of the §1.3 list:

- [ ] **At the moment the stage starts** — any black bar or corruption on the left?
- [ ] Scroll to the level's **left edge** — black margin? how wide, roughly?
- [ ] Scroll to the level's **right edge** — same question
- [ ] HUD (health bar, weapon icon) sits at the screen edge, not floating inward
- [ ] Enemies appear *off* screen, not popping in mid-view
- [ ] Vertical scrolling sections look right

| # | destination | start-of-stage | left edge | right edge | HUD | pop-in | notes |
|---|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |  |
| 6 |  |  |  |  |  |  |  |
| 7 |  |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |  |
| — | Dr. Light's Lab |  |  |  |  |  |  |

### 2.1 The open question — please answer this one

At a stage start with widescreen on, **photograph or screen-grab the actual
window** and answer:

- [ ] Is it a plain **black bar down the left side**, or **diagonal black wedges**
      (a bowtie shape) across the frame?

This decides the diagnosis in `docs/WIDESCREEN_STAGE_START.md`. My captures show
wedges, you described a bar, and the two imply completely different causes — the
capture path composites the wide frame itself, so it may be lying to me.

Also worth knowing:

- [ ] Does the black region appear at **every** stage start, or only some?
- [ ] Does it persist once you walk right, or clear as soon as the camera moves?

---

## 3. Tools verification

Quick, independent of the game passes.

### ESC menu — *never verified, please test*

- [ ] ESC opens the menu, 11 rows, `RESUME` highlighted
- [ ] Up/Down move the highlight; ESC closes
- [ ] Game input does not leak through while the menu is open
- [ ] `RESUME` returns to the game
- [ ] `SET SKIP POINT HERE` reports "Skip point set"
- [ ] `GO TO SKIP POINT` returns there exactly (and reads `(NONE SET)` before one is taken)
- [ ] The skip point does **not** consume any of the 12 user slots
- [ ] `SAVE STATES` opens the save-state browser
- [ ] `REWIND` opens rewind
- [ ] `FULLSCREEN` toggles, and the label follows the real window state
- [ ] `VOLUME` Left/Right changes volume audibly in 5% steps
- [ ] `FPS DISPLAY` toggles the counter
- [ ] `FILTER` switches NEAREST/BILINEAR **and the change is visible immediately**
- [ ] `RESTART GAME` reboots the game **without returning to the launcher** and without the window closing
- [ ] After a restart the game is playable again from the title
- [ ] `QUIT` exits cleanly

Worth a moment on **FILTER**: switch it back and forth inside a stage and say
whether bilinear is an improvement on this title or just blurry — it is the one
row meant to be judged by eye rather than ticked.

### Save states

- [ ] F7 opens the menu; digits select slots
- [ ] `S` raises `SAVE TO SLOT N ?`; Enter confirms, Esc cancels
- [ ] `L` raises `LOAD FROM SLOT N ?`; Enter confirms, Esc cancels
- [ ] Pressing a digit while a prompt is up does **not** change the slot
- [ ] Pad: **A** confirms, **X** cancels
- [ ] Loading an empty slot says "Slot N is empty" instead of prompting
- [ ] After confirming, the slot shows a timestamp/thumbnail
- [ ] A confirmed load lands exactly where you saved
- [ ] Loading a slot from a *previous session* works
- [ ] F8 rewind works and does not corrupt the run

### Stage select mod

Enable **Stage Select**, set a stage, relaunch.

- [ ] Arrives directly in the chosen stage, not the intro stage
- [ ] Works for **all 14** indices (00–0D) — note any that fail
- [ ] After that first stage, normal progression resumes

### Skip intros

- [ ] ON → Capcom reel and FMV skipped
- [ ] OFF → both play in full (faithful behaviour intact)

---

## 4. Regression guard

With **all mods off**, confirm the faithful build is untouched:

- [ ] Intro FMV plays in full, correct aspect
- [ ] Game presents 4:3
- [ ] Audio and CD-DA fine
- [ ] Memory-card save and load work

---

## 5. If you hit the black-stage bug

That one is intermittent and I could not reproduce it. If it happens, capture
this **before** rewinding or reloading — the live state is the evidence:

1. **Do not press anything.** Screenshot/photograph the screen.
2. Note: which destination, was it the **first** stage entered after the intro,
   and what music is playing.
3. If a `--debug` build is running, grab these over port 4545:
   `gpu_state`, `overlay_loader_status`, `dirty_ram_unsupported`,
   `dispatch_stats`, `cdrom_state`.
4. **F7 → save to a free slot.** A save state of the broken state is the single
   most useful artifact — it makes an intermittent bug reproducible on demand.
5. *Then* try F8 rewind and note whether replaying the transition fixes it.

---

## 6. Reporting

For each defect:

```
WHERE     stage / screen, and 4:3 or 16:9
WHEN      at stage start / mid-stage / at a level edge / on a transition
WHAT      what you see, one line
BOTH?     does it also happen in the other aspect mode?
REPRO     does it happen every time, or once in N?
ARTIFACT  screenshot, and a save-state slot number if you took one
```

The **BOTH?** line is the one that saves the most time — it splits widescreen
bugs from recomp bugs immediately.

Known and already logged, no need to re-report unless the behaviour differs:

* `ISSUES.md #16` — widescreen corruption/black region at stage start
* `ISSUES.md #15` — the black-stage transition (not reproduced; §5 covers it)
* Title screen and menus present 4:3 while widescreen is on
