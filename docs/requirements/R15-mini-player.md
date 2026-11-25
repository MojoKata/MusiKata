# R15. Mini player

A small window of its own that plays on while MusiKata's main window is out of the way. It has
seven layouts, each a different balance of art, visuals and detail; the user picks one, and can
switch at any time. Mockups: `M01-mini-players`, `M02-mini-player-menu`.

R15.1. **Opening and closing.** The mini player opens from the pop-out button in the now-playing
bar, just left of the Now Playing button (R6.5), from ⋮ › **Mini player** (R6.6), or with
Ctrl+Shift+M (⇧⌘M on macOS). Opening it minimizes the main window (a setting, R13, on by default).
**Show MusiKata** (its menu, its MusiKata icon, or Ctrl+Shift+M again) closes it and brings the
main window back; closing it with its **×** does the same. Playback never stops on opening or
closing it.

R15.2. **The window.** It has no title bar of its own: rounded corners, its own shadow, and the
same design tokens as the main window (R6.2). It is moved by dragging anywhere that isn't a
control, resized from its edges within the limits of its layout, and snaps to the screen's edges.
**Stay on top** (the pin) keeps it above other windows, on by default; on Wayland the compositor
decides whether it is honoured. Its position, size, layout and Stay on top are kept, per layout
for size.

R15.3. **Layouts,** chosen from its right-click menu (R15.4) and kept:

| # | Layout | What it shows | Default size |
|---|---|---|---|
| 1 | **Strip** | One row: the cover, title, artist and album, a ten-bar spectrum (R11.3's bands gathered into ten) with the time under it, previous, play/pause and next, and the progress as a gradient line along the bottom | 496 × 76 |
| 2 | **Cover** | The cover edge to edge, with translucent spectrum bars over its lower part and the green progress line at its foot (as R11.4.3); under the pointer, the title, artist and album, previous, play/pause and next appear over a dark gradient | 300 × 300 |
| 3 | **Card** | Upright and complete: the cover, "Track 4 of 10 · Glass Harbor", title, rating (settable, R10.2), artist, year and genre, the song's waveform as a seek bar (R11.2) with the times, shuffle, previous, play/pause, next and repeat, and the next song in the queue | 300 × 582 |
| 4 | **Analyzer** | A small 3D analyzer (R11.3) filling the window, the song's cover, title and artist in a card at the top left, the controls in a pill at the bottom right, the progress along the bottom | 496 × 170 |
| 5 | **Disc** | The cover as a round disc, a progress ring around it in the `progress` colour, the spectrum as short rays around the ring, then title, artist and album, previous, play/pause and next | 240 × 320 |
| 6 | **Details** | The Card without the cover or the next song: track, title, rating, artist, year and genre, the waveform seek bar with the times, and the full controls | 300 × 240 |
| 7 | **Remote** | The right half of the Strip: the ten-bar spectrum and the time, previous, play/pause and next, × and the pin, and the progress line; the song's title and artist are its tooltip | 246 × 76 |

R15.4. **Controls.** Every layout has play/pause, previous and next, **×** and the pin; all but
Strip and Remote also have the MusiKata icon (Show MusiKata) in a corner. In **Cover** they appear
only under the pointer. The scroll wheel over it changes the volume; Space, ← / → and Ctrl+→ /
Ctrl+← work as in the main window (R6.9) while it has focus. Its right-click menu
(`M02-mini-player-menu`) lists the seven layouts by name and number, the current one checked, then
**Stay on top**, **Show MusiKata** and **Close mini player**. Dropping songs onto it adds them to
the queue (R7.2).

R15.5. **Visuals.** Its spectrum and analyzer come from the same audio as Now Playing's (A5.2),
and stop drawing when it is hidden, covered by a full-screen window, or playback is paused (as
R11.3.2). With no song playing it shows the last one, paused.
