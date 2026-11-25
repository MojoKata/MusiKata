# A4. Playback

A4.1. **Qt Multimedia.** `QMediaPlayer` with a `QAudioOutput` plays every kind of R2.2 through
the FFmpeg back end Qt carries on Linux, Windows and macOS, so MusiKata needs no codec of its own
and the system's codecs don't matter. It is in PySide6's Addons wheel, not Essentials, so MusiKata
depends on both (A6.2).

A4.2. **The queue** lives in `musikata` as a list of song ids with a cursor and a shuffle order;
`Player` owns one `QMediaPlayer` for the current song and opens the next one in a second player
shortly before the end (R7.6). Handing over between the two players leaves a short gap: true
gapless playback needs the audio of both files in one stream, which Qt Multimedia doesn't offer
(Q5).

A4.3. **Taking the audio for the analyzer.** `QAudioBufferOutput` (Qt 6.8 and later) attached to
the player delivers the decoded PCM as it plays, in step with what is heard. Its buffers go to a
ring buffer of the last few seconds, which the analyzer reads each frame (A5.2). Nothing is
decoded twice for the analyzer.

A4.4. **ReplayGain** is applied by setting `QAudioOutput.volume` to the user's volume times
`10^(gain/20)`, clamped so it never clips by more than the track peak allows.

A4.5. **The system's media controls** (R7.8):

| Platform | How | Dependency |
|---|---|---|
| Linux | MPRIS 2 (`org.mpris.MediaPlayer2.musikata`) on the session bus, with `QtDBus` | none beyond PySide6 |
| Windows | System Media Transport Controls, through `ISystemMediaTransportControlsInterop` for the window | `winrt-Windows.Media` (PyWinRT), Windows only |
| macOS | `MPNowPlayingInfoCenter` and `MPRemoteCommandCenter` | `pyobjc-framework-MediaPlayer`, macOS only |

Each is a small module behind one interface (`now_playing(song)`, `state(playing)`, and signals for
the commands), so the rest of the app doesn't know which is in use, and a platform without one
still plays.

A4.6. **Output devices** are listed by `QMediaDevices`, whose `audioOutputsChanged` signal is how a
vanished device is noticed (R7.7).
