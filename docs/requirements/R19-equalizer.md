# R19. Equalizer

A ten-band equalizer on MusiKata's own audio stream (R7.6), with presets that come with it,
presets of the user's own, and a preset chosen by each song's genre. Mockup: `N05-equalizer`.

R19.1. **The bands.** Ten bands, one per octave: 31, 62, 125 and 250 Hz, 500 Hz, 1, 2, 4, 8 and
16 kHz, each from −12 to +12 dB, and a preamp from −12 to +12 dB. The equalizer is on or off as a
whole. It works after ReplayGain (R7.5) and before the volume, and never clips: when a boost would
push the sound past full scale, the level is held down instead.

R19.2. **The Equalizer panel** (`N05-equalizer`) opens from the **Equalizer** button in Now
Playing's top row (R11.4), from ⋮ › **Equalizer…** (R6.6), and from Settings (R13.7). It floats
over the view and stays open while the music plays: the on/off switch; the preset picker; a
slider per band with its value, and the curve they make drawn across them; the preamp; the
preset's actions; and **Choose by genre** (R19.4). Every change is heard at once. The sliders work
from the keyboard (R18.2), and double-clicking one sets it back to 0 dB.

R19.3. **Presets.**

- **Built in:** Flat, Bass boost, Treble boost, Vocal, Rock, Pop, Jazz, Classical, Electronic and
  Loudness. They can't be changed or removed; **Duplicate** makes a custom copy of one.
- **Custom:** **Save as new…** makes one from the sliders as they are; **Update** saves the
  sliders into the custom preset chosen; **Rename…** and **Delete** (after asking) do what they
  say.
- Moving a slider while a preset is chosen shows it as changed ("Bass boost (changed)") until it
  is saved as new, updated, or another preset is chosen.

R19.4. **By genre.** A table matches genres to presets (Classical → Classical, Jazz → Jazz, and
any the user adds; the built-in genres come matched to the built-in presets of the same name).
With **Choose by genre** on, each song takes the preset of its first genre that has one (R9.2),
or the preset chosen in the panel when none has; the panel says which ("Classical, chosen by
genre"). Choosing a preset by hand turns **Choose by genre** off, until it is turned on again.

R19.5. **What is kept.** Whether it is on, the preset chosen, the custom presets and the genre
table are kept in the shared settings (R1.5), so every root has them.
