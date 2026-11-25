# R17. Lyrics

MusiKata shows a song's lyrics as it plays, in step with the music when they carry times, and
helps find, correct and keep them, in the files like everything else (Principle 1). Mockup:
`N04-now-playing-lyrics`.

R17.1. **Where lyrics come from,** in this order:

1. An `.lrc` file beside the song with the same name (`04 - Signal Fires.lrc`), which moves with
   the song (R12.3).
2. Lyrics in the song's tags: ID3 `SYLT` (with times) or `USLT`; Vorbis and FLAC `LYRICS`; MP4
   `©lyr`. Lyrics in LRC form inside a plain lyrics tag count as timed.
3. Online, only when asked (R17.4).

R17.2. **Timed and plain.** Timed lyrics (LRC: a time for each line) are followed as the song
plays: the current line large and bright, the lines sung dimmed, the next ones muted, scrolling
smoothly to keep the current line a third of the way down. Clicking a line seeks to it (R7.4).
Plain lyrics are shown as text that scrolls by hand. Lyrics marked instrumental show
"Instrumental".

R17.3. **In Now Playing** (`N04-now-playing-lyrics`). The **Lyrics** switch beside the
visualization picker (R11.4) shows the lyrics in place of what is on the right: Up next with
**Waveform**, the queue with **No visualization**; with **3D analyzer**, the current and next
lines sit over the analyzer's lower part. Above the lyrics: where they come from ("Timed · from
04 - Signal Fires.lrc"), **Find online…** and **Edit…**. The switch is kept.

R17.3.1. A song without lyrics shows "No lyrics for this song" with **Find online…** and **Add…**.

R17.4. **Finding them online.** **Find online…** asks LRCLIB (R16.1) for the song's artist,
title, album and length, and lists what it has, timed versions first, each with its length and
its first lines. **Save** keeps the chosen one where Settings says (R13.11): beside the song as
`.lrc` (the default), in its tags, or both. An album's ⋯ menu has **Find lyrics** for every song of
it that has none, shown as a list to check before saving. Saving is undoable (R4.9).

R17.5. **Editing.** **Edit…** opens the lyrics as text, timed ones with their `[mm:ss.xx]` times.
While the song plays, **Set time** gives the line under the cursor the current position and
moves to the next line, so plain lyrics can be timed by tapping along. **Save** keeps them as
R17.4 does.
