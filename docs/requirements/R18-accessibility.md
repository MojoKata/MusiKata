# R18. Accessibility

MusiKata is usable without a mouse, without sight, with large text, and without motion. These
hold in every view, dialog and window, the mini player's included.

R18.1. **Screen readers.** Every control has an accessible name, role and state (Qt Quick's
`Accessible`), so Orca, NVDA, Narrator and VoiceOver can use MusiKata:

- list rows read as a sentence ("Signal Fires, Lumen Drift, Glass Harbor, 4 minutes 18, rated 5
  stars, playing");
- covers and mosaics are named by what they show ("Cover of Glass Harbor", "Folder Lumen Drift,
  3 folders, 37 songs, 2 to fix");
- the short messages of R6.7, a scan's progress and the end of a long lookup are announced;
- the visualizations are described, not read: "Waveform, 1 minute 38 of 4 minutes 18".

R18.2. **Keyboard.** Everything can be done from the keyboard (R6.9), with focus always visible.
What is done by dragging has another way: **Add to playlist…** and **Play next** instead of
dropping, Ctrl+Shift+↑ / ↓ to reorder a playlist, the arrow keys to seek and to set a rating.

R18.3. **Text size and scaling.** MusiKata follows the system's display scaling, fractional
scaling included, and its text size. **Text size** in Settings (R13.8) scales the whole interface
from 90 % to 150 %; every view stays usable at 150 % on the 1280 × 800 window of R6.2.1, with text
elided, never cut off or overlapping (the tour checks both sizes).

R18.4. **Contrast and colour.** Text is at least 4.5:1 against what it is drawn on, and large
text, icons and the lines that bound controls at least 3:1 (WCAG 2.2 AA), in both themes; a test
checks every text token against every surface it is used on (R6.2). Nothing is told by colour
alone: chips carry an icon and a word, path-match dots (R2.9.5) have a tooltip and are in the
folder's accessible name, and old and new values in previews (R3.7) are struck through and
labelled, not only red and green.

R18.5. **Motion.** **Reduce motion** (R13.8) follows the system's setting by default. On, views
change without sliding or fading, lyrics jump to the current line instead of scrolling (R17.2),
and the moving visualizations (the 3D analyzer, the cover's spectrum, the mini player's) are
replaced by the song's still waveform. Nothing in MusiKata ever flashes more than three times a
second.
