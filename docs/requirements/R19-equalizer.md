# R19. Equalizer

An equalizer on MusiKata's own audio stream (R7.6), whose presets are either parametric (bands of
any kind, placed anywhere) or graphic (ten sliders), with presets that come with it, presets of the
user's own, and a preset chosen by each song's genre. Mockups: `N05-equalizer` (parametric),
`N06-equalizer-graphic`.

R19.1. **The bands.** Each preset is one of two kinds:

- **Parametric:** 1 to 10 bands. Each band has a type (bell, low shelf, high shelf, low cut or high
  cut), a frequency from 20 Hz to 20 kHz, a gain from −12 to +12 dB (none for the cuts) and a Q
  from 0.1 to 10. A new parametric preset starts with five: a low shelf, three bells and a high
  shelf, all at 0 dB.
- **Graphic:** ten sliders, one per octave: 31, 62, 125 and 250 Hz, 500 Hz, 1, 2, 4, 8 and 16 kHz,
  each from −12 to +12 dB. A graphic preset is ten bells at those frequencies, one octave wide, so
  it plays exactly as the same parametric preset would.

Both kinds have a preamp from −12 to +12 dB. The equalizer is on or off as a whole. It works after
ReplayGain (R7.5) and before the volume, and never clips: when a boost would push the sound past
full scale, the level is held down instead.

R19.2. **The Equalizer panel** opens from the **Equalizer** button in Now Playing's top row
(R11.4), from ⋮ › **Equalizer…** (R6.6), and from Settings (R13.7). It floats over the view and
stays open while the music plays: the on/off switch; the preset picker, the preset's kind
(**Parametric** or **Graphic**, R19.6) and its actions; the bands; and **Choose by genre**
(R19.4). Every change is heard at once.

- **Parametric** (`N05-equalizer`): a graph of the response from 20 Hz to 20 kHz, with a numbered
  handle per band. Dragging a handle sets its frequency and gain; the scroll wheel over it sets
  its Q. Double-clicking a handle sets its gain to 0 dB; double-clicking the graph where there is
  no handle adds a bell there; **Delete** removes the selected band. Under the graph, in four
  columns from the graph's left edge: the selected band's handle, with a delete button at the
  foot of the row; its type, as a vertical segmented control (Bell, Low shelf, High shelf, Low cut,
  High cut); sliders for its frequency and for the preamp; and sliders for its gain and Q. Each
  slider's value is shown above its right end and can be typed into. The panel shows no
  instructions for the mouse.
- **Graphic** (`N06-equalizer-graphic`): the preamp and a slider per band with its value, and the
  curve they make drawn across them. Double-clicking a slider sets it back to 0 dB.

Every handle, slider and field works from the keyboard (R18.2): Tab moves between bands, the
arrow keys move the selected one.

R19.3. **Presets.**

- **Built in:** Flat, Bass boost, Treble boost, Vocal, Rock, Pop, Jazz, Classical, Electronic and
  Loudness, all parametric. They can't be changed or removed; **Duplicate** makes a custom copy of
  one.
- **Custom:** **Save as new…** makes one from the bands as they are; **Update** saves the bands
  into the custom preset chosen; **Rename…** and **Delete** (after asking) do what they say.
- Changing a band while a preset is chosen shows it as changed ("Bass boost (changed)") until it
  is saved as new, updated, or another preset is chosen.

R19.4. **By genre.** A table matches genres to presets (Classical → Classical, Jazz → Jazz, and
any the user adds; the built-in genres come matched to the built-in presets of the same name).
With **Choose by genre** on, each song takes the preset of its first genre that has one (R9.2),
or the preset chosen in the panel when none has; the panel says which ("Classical, chosen by
genre"). A preset chosen by hand while **Choose by genre** is on plays for the song that is
playing; the next song takes its genre's preset again, and the panel says so ("Car, for this
song").

R19.5. **What is kept.** Whether it is on, the preset chosen, the custom presets and the genre
table are kept in the shared settings (R1.5, R13.9), so every root has them.

R19.6. **Changing a preset's kind.** The **Parametric** / **Graphic** switch turns the preset
chosen into the other kind. A built-in preset can't be changed, so switching one makes a custom
copy of the other kind ("Rock (graphic)").

- **Graphic to parametric** loses nothing: the ten sliders become ten bells.
- **Parametric to graphic** sets the ten sliders to match the curve as closely as ten can, and
  first shows the old curve and the new one together, with how close they come ("Ten sliders come
  within 1.5 dB of this curve"), to confirm or cancel. Switching back to parametric before any
  slider is changed gives back the bands exactly as they were.

R19.7. **Import and export.** **Import…** reads a preset from a text file in Equalizer APO's format
(`Preamp: -6.2 dB`, `Filter 1: ON PK Fc 105 Hz Gain -3.2 dB Q 0.70`), the format the AutoEq
project publishes corrections for headphones in, and makes it a custom parametric preset named
after the file. Peak, low shelf, high shelf, low pass and high pass filters are read; any other
line, and any band past the tenth, is listed as skipped. **Export…** writes the preset chosen in
the same format, a graphic one as its ten bells.
