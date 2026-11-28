"""Playback's arithmetic and its decoder (A4): `decode` opens and decodes a song's file, `stream`
holds the samples on their way to the sound device, `join` runs one song into the next in that
stream and moves within one (A4.2, A4.6), `gain` is ReplayGain and the volume (A4.4), `eq` the
equalizer's filter, crossfades and limiter (A4.4, R19.1) and `presets` its presets (R19), `queue`
decides what plays after what (A4.2, R7.2, R7.3), and `played` when a song counts as played
(R7.9). The sleep timer joins with the rest of slice 9 (A1.9)."""
