Mega Man 8 Widescreen (experimental)
====================================

Renders a genuinely wider field of view rather than stretching or cropping the
original 4:3 image. Mega Man 8 is a pure-2D title, so this uses the framework's
native-wide path: the recompiler widens the game's own screen-extent cull
(func_800FA050, a 320-wide / 256-tall reject) so actors and tiles that the game
would normally discard at the screen edge are produced and drawn.

Default: OFF. With the feature disabled the game presents native 4:3 and the
output is byte-identical to the faithful build.

The background is widened too: MM8's tile renderer (func_800F98D8) draws extra
columns and starts further left, so the revealed margins are filled with real
background rather than black, and the HUD is re-anchored to the true wide edge
rather than floating at its old 4:3 position.

Known limitations (this is why it ships as experimental):
  * At a stage's left/right boundary the camera clamps, so the outermost strip
    can still be black - there is no map data further out to draw.
  * Only the intro stage has been exercised so far.
See docs/WIDESCREEN.md in the project repository for current status.
