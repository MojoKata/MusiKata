# R7. Playback

R7.1. **Playing.** Double-clicking a song, or pressing Enter on a selection, plays it and puts the
rest of its list (the album, the playlist, the filtered Songs view) after it in the queue.
**Play** on an album, artist, genre or playlist does the same from its first song.

R7.2. **The queue.** The queue button in the now-playing bar opens **Up next**, a panel of the
songs to come, then the songs played; Now Playing with **No visualization** shows the same queue
at full size (R11.4.3). Songs can be reordered and removed there, and dropped onto
it (R6.10). Every song list's context menu has **Play next** and **Add to queue**. The queue is
kept across restarts (R1.8).

R7.3. **Shuffle and repeat.** Shuffle plays the queue in a random order without repeating a song
until all have played. Repeat cycles Off, All and One. Both are kept across restarts.

R7.4. **Seeking.** Clicking or dragging on the waveform in the now-playing bar or in Now Playing
seeks there (R11.2); ← and → seek 5 seconds.

R7.5. **ReplayGain.** Track, Album (the default) or Off, a setting (R13). Album uses the album gain
when the album is played in order and the track gain otherwise. Songs without ReplayGain tags play
at a pre-amp of −6 dB so they aren't louder than those with them. MusiKata reads ReplayGain;
computing it is [#2](https://github.com/MojoKata/MusiKata/issues/2).

R7.6. **Between songs.** Playback is gapless: one song runs into the next with no gap and no click,
and the silence MP3 and AAC encoders add at a file's start and end is left out, so live albums,
mixes and albums made to flow play as they were made. This holds across songs of different sample
rates and kinds. Crossfading is [#4](https://github.com/MojoKata/MusiKata/issues/4).

R7.6.1. The equalizer (R19) and ReplayGain (R7.5) apply to the same stream, and change at the
join between two songs without a click.

R7.7. **Output.** The output device is the system's default unless one is chosen in Settings
(R13); when the device in use goes away, playback pauses and moves to the default.

R7.8. **The system's controls.** MusiKata shows the song and its cover and takes play, pause,
next, previous and seek from the system:

- Linux: MPRIS over D-Bus, so the desktop's media keys and sound menu work.
- Windows: the System Media Transport Controls, so the media keys and the volume overlay work.
- macOS: Now Playing in Control Centre and the media keys.

R7.9. **Play counts.** A song counts as played once 50% of it, or 4 minutes, has played. Play
counts and the last-played time are kept in the root's `.musikata/plays/`, a file per computer
(R1.5); the count shown adds up the plays of every computer that plays the root, and the Songs
view can sort by it.

R7.10. **Sleep timer.** ⋮ › **Sleep timer** (R6.6) and the mini player's menu (R15.4) offer 15,
30, 45 and 60 minutes, **Custom…**, **End of this song**, **End of this album** and **Off**.

- While it runs, a moon and the time left show beside the volume in the now-playing bar (R6.5,
  `N03-now-playing-queue`); clicking them opens the same choices, to change or cancel it.
- Over its last 30 seconds the volume fades to nothing; then playback pauses and the volume is put
  back where it was. Reduce motion (R18.5) doesn't change the fade, which is sound.
- It is never saved: quitting MusiKata cancels it, and the next start has none.
