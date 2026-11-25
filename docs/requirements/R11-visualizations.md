# R11. Visualizations

MusiKata has two visualizations, kept few on purpose: a linear waveform of the whole song, and a
3D spectrum analyzer of what is playing now. Both use the gradient of the design tokens, cyan to
violet to pink (R6.2). With no visualization, Now Playing shows the queue, and only a faint
spectrum on the cover (R11.4.3). The mini player (R15) carries small ones of its own.

R11.1. **The waveform** is the loudness of the whole song from start to end, drawn as thin rounded
bars mirrored about a centre line. The part already played is drawn in the gradient, the rest in
grey.

R11.1.1. A song's waveform is worked out from its audio the first time it is played, or ahead of
time for the next song in the queue, and kept in the cache (R1.5). Until it is ready a flat line
is shown, filling in as the decoding goes.

R11.2. **As the seek bar.** The now-playing bar's seek bar is the song's waveform (R6.5). Hovering
shows the time under the pointer; clicking or dragging seeks (R7.4).

R11.3. **The 3D analyzer** (`N02-now-playing-3d-analyzer`) shows the spectrum of the last few
seconds as a landscape: each slice is the spectrum at one moment, from low frequencies on the left
to high on the right, its height the level of each band. The newest slice is at the front, and
older ones recede towards the horizon, shrinking and turning from cyan to violet. Nearer slices
hide the ones behind them.

R11.3.1. The bands are spaced by octave from 32 Hz to 16 kHz, labelled along the front. The
number of bands (48, 96 or 128) and the speed (how many seconds the landscape holds) are set from
the gear in its corner, and kept.

R11.3.2. It draws at the display's refresh rate, up to 60 frames a second, and drops to 30 when
the computer can't keep up. It stops drawing when Now Playing is hidden, the window is minimized,
or playback is paused (the last landscape stays).

R11.4. **Now Playing** opens from the **Now Playing** button at the right end of the now-playing
bar (R6.5), or by clicking the bar's cover. It takes over everything above the now-playing bar,
the sidebar and the view's header included; its own top row has **‹ Library** on the left, the
visualization picker (R11.4.5), the **Lyrics** switch (R17.3) and the **Equalizer** button
(R19.2) in the middle, and the window
buttons on the right.

R11.4.1. With **Waveform** (`N01-now-playing-waveform`): the cover large on the left, then "Now
playing · Track 4 of 10", the title, artist, album, year and genre, the rating, and chips for the
format, bit depth and sample rate, bit rate and ReplayGain; **Up next** on the right; and across
the bottom the song's waveform, large, with the play head, its time, and minute marks.

R11.4.2. With **3D analyzer**: the analyzer fills the view, with a small card of the cover, title
and artist in the top-left corner.

R11.4.3. With **No visualization** (`N03-now-playing-queue`): the playing song on the left and the
queue on the right.

- **The cover**, large, with the song's spectrum drawn over its lower part as 32 translucent white
  bars (the bands of R11.3.1 gathered into 32), rising and falling with the music, and along its
  very bottom edge a thin bright green line (`progress`, R6.2) showing how much of the song has
  played. Paused, the bars settle to nothing and the line stays. Under the cover: "Now playing ·
  Track 4 of 10", the title, artist, album, year and genre, the rating, and the format.
- **The queue** (R7.2) at full size: what played last, dimmed; the playing song, highlighted; the
  songs added with **Play next** or **Add to queue** ("Next · added by you"); then the rest of
  what is playing ("Next from Glass Harbor"), each with its cover, title, artist and album, and
  length. Above it, where the queue comes from, how many songs are left and how long they take,
  **Save as playlist…** (R8.3) and **Clear**. A row under the pointer shows its drag handle and
  **×**; rows are reordered by dragging, and songs dropped on it are added (R6.10).

R11.4.4. **Esc**, **‹ Library**, or the **Now Playing** button again goes back to the view it was
opened from.

R11.4.5. **The visualization picker** is a drop-down showing the current choice with its icon
("3D analyzer ▾"). Its menu lists **Waveform**, **3D analyzer** and **No visualization**, each with
its icon, the current one checked (`N02-now-playing-3d-analyzer`); the choice is kept.
