# A5. Visualizations

A5.1. **Waveforms** (R11.1). A worker decodes the song with `QAudioDecoder` to mono floats and
reduces it to 2,000 peak pairs (the largest and smallest sample in each slice), whatever the
song's length: enough for a 1920-pixel-wide view at two bars per pixel or fewer. The peaks are
stored as a 16-bit blob (8 KB a song) in the `waveform` table, keyed by the audio hash (A2.3), so
retagging or moving a song keeps its waveform. Views draw as many bars as fit and take the
largest peak of the slices under each bar.

A5.2. **The spectrum** (R11.3). Each frame takes the newest 4,096 samples from the ring buffer of
A4.3, mixes them to mono, applies a Hann window and runs NumPy's `rfft`. The magnitudes are
gathered into bands spaced logarithmically from 32 Hz to 16 kHz (each band the largest magnitude
in its range, which keeps the low bands, a few bins wide, from looking empty), converted to dB,
and clamped to a 60 dB range. Each band rises at once and falls at a set rate, so the landscape
doesn't flicker. A 4,096-point FFT is well under a millisecond in NumPy, a small part of a 16 ms frame.

A5.3. **Drawing.** Both are custom Qt Quick items that build their geometry for the scene graph
(`QSGGeometryNode`) instead of painting with `QPainter`, so drawing is done on the GPU and 60
frames a second costs the CPU little more than the arithmetic of A5.2.

- The waveform is one triangle-strip node per colour (played and to come), rebuilt only when the
  size or the play head's bar changes.
- The analyzer keeps the last N spectra (the speed of R11.3.1 sets N). Each frame it projects them
  into a perspective landscape: depth scales a slice's width and height towards a vanishing
  point and moves it up towards the horizon. Slices are drawn back to front, each as a filled
  strip in the background colour (which hides what is behind it) under a line strip in its
  colour, the colour stepping from cyan at the front to violet at the back.

A5.4. **Why not Qt Quick 3D or Qt Graphs.** Both could draw a 3D surface, but they add large
modules to every download (A6.3), their look would need much undoing to match R6.2, and the
landscape's "3D" is a projection of 2D lines that the scene graph draws directly. The mockup
`N02-now-playing-3d-analyzer` is drawn with the same projection.

A5.5. **When nothing is shown** (R11.3.2), neither the analyzer nor the cover's spectrum (A5.6)
on screen, in Now Playing or the mini player (R15.5), they stop requesting frames and the ring buffer stops being read; the audio tap stays
attached, as detaching it would interrupt playback.

A5.6. **The cover's spectrum** (R11.4.3) is the spectrum of A5.2 gathered into 32 bands, drawn as
one translucent geometry node over the cover image and updated at 30 frames a second, which is
plenty for bars that size; the progress line is a plain rectangle moved with the position. It
costs about as much as the now-playing bar's waveform, so it needs no setting to turn it off.
