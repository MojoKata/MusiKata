# A4. Playback

MusiKata plays the audio itself: it decodes each song, applies the gain and the equalizer, and
hands one continuous stream to the sound device. That is what makes gapless playback (R7.6) and
the equalizer (R19) possible (A1.7.4).

A4.1. **The pipeline.**

```
 file ──PyAV decode──▶ trim encoder padding ──▶ resample to the device's rate ──┐
                                                                                ▼
 sound device ◀── QAudioSink ◀── ring buffer (≈2 s) ◀── volume ◀── equalizer ◀── ReplayGain
                                       │
                                       └──▶ the analyzer's ring buffer (A4.3)
```

- **Decoding** is PyAV, the Python binding of FFmpeg, whose wheels carry FFmpeg's decoders for
  every kind of R2.2. Qt's own `QAudioDecoder` can't seek and doesn't report encoder padding, and
  `QMediaPlayer` plays files one at a time with a gap between them.
- **Output** is Qt Multimedia's `QAudioSink` in pull mode, reading float samples from a ring
  buffer at the device's own sample rate.
- The playback thread (A1.3) decodes and processes blocks of about 20 ms until the ring buffer
  holds two seconds; the device pulls from it on its own schedule, so a busy GUI or a slow disk
  doesn't stop the sound.

A4.2. **The queue and the joins between songs.** The queue lives in `musikata` as a list of song
ids with a cursor and a shuffle order (R7.2, R7.3). Ten seconds before a song ends, the next one is
opened and its first blocks decoded, and its samples follow the last samples of the current one
in the same stream, so there is no gap:

- Everything is resampled to the one rate the device runs at, so songs of different sample rates
  and channels join exactly.
- The silence encoders add is trimmed: an MP3's start delay and end padding from its LAME or Xing
  header, an AAC file's from its `iTunSMPB` tag, an Opus file's pre-skip. Tests check each on
  generated files with a known number of samples.
- A change of ReplayGain or equalizer preset at the join (R7.6.1) is ramped over 50 ms.

A4.3. **The analyzer's audio.** Each block handed to the ring buffer is also copied, with its
position, into the analyzer's ring buffer of the last few seconds (A5.2). The analyzer reads it
delayed by the device's reported latency, so what is drawn is what is heard.

A4.4. **Gain and the equalizer.**

- **ReplayGain** (R7.5) is a multiplication by `10^(gain/20)`, limited by the track's peak so it
  never clips.
- **The equalizer** (R19): the ten band gains are turned into one filter, about 2,000 samples
  long, rebuilt when a slider moves, and applied block by block with NumPy's FFT (overlap-add). No
  SciPy is needed, and it costs a few percent of one core.
- **Never clipping:** after the preamp, a peak limiter holds the stream under full scale.
- **Volume** is applied last, so the equalizer works at full resolution.

A4.5. **The system's media controls** (R7.8):

| Platform | How | Dependency |
|---|---|---|
| Linux | MPRIS 2 (`org.mpris.MediaPlayer2.musikata`) on the session bus, with `QtDBus` | none beyond PySide6 |
| Windows | System Media Transport Controls, through `ISystemMediaTransportControlsInterop` for the window | `winrt-Windows.Media` (PyWinRT), Windows only |
| macOS | `MPNowPlayingInfoCenter` and `MPRemoteCommandCenter` | `pyobjc-framework-MediaPlayer`, macOS only |

Each is a small module behind one interface (`now_playing(song)`, `state(playing)`, and signals for
the commands), so the rest of the app doesn't know which is in use, and a platform without one
still plays.

A4.6. **Seeking and devices.** A seek (R7.4) asks PyAV for the nearest keyframe before the
position, decodes forward to the exact sample, and replaces what is in the ring buffer, so the
sound moves within a block. Output devices are listed by `QMediaDevices`; when the device in use
goes away (`audioOutputsChanged`), playback pauses, a new `QAudioSink` is opened on the default
device at its rate, and the stream resumes from the same sample when the user presses play
(R7.7).
