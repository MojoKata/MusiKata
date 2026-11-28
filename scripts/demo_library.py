"""The demo library (docs/architecture/A6-packaging-and-platforms.md, A6.7; docs/process/
development.md, "The demo library"): short generated audio in every kind of R2.2, tagged with the
mockups' made-up artists and albums, some of them wrong on purpose, and written the ways other
programs write tags (docs/process/testing.md, "Shapes"). Real music is never used.

    .venv/bin/python scripts/demo_library.py build DIR [--songs N] [--seconds S]

writes DIR/Music: the mockups' library (about 240 songs), and with --songs N more albums of made-up
names until it holds N songs (R1.11's 50,000), and the change history of a few saves made on two
computers (R4.9; `HISTORY`), through MusiKata's own batch, so its Change history has entries. It
runs on the release's Python with PyAV, Mutagen and NumPy (packaging/versions.env): PyAV's own
FFmpeg encodes every kind, so nothing else is needed; the history imports musikata_core from src/.

What it plans is plain data (plan, more), so the tests read it without encoding anything; build
writes it.
"""

from __future__ import annotations

import argparse
import fractions
import json
import os
import random
import shutil
import sys
from dataclasses import dataclass, field

# every kind of R2.2: the file's extension, the muxer, the codec, its sample format, its rate
KINDS = {
    "mp3": ("mp3", "mp3", "libmp3lame", "fltp", 44100),
    "flac": ("flac", "flac", "flac", "s16", 44100),
    "aac": ("m4a", "ipod", "aac", "fltp", 44100),
    "alac": ("m4a", "ipod", "alac", "s16p", 44100),
    "vorbis": ("ogg", "ogg", "vorbis", "fltp", 44100),
    "opus": ("opus", "ogg", "libopus", "s16", 48000),
    "wav": ("wav", "wav", "pcm_s16le", "s16", 44100),
    "aiff": ("aiff", "aiff", "pcm_s16be", "s16", 44100),
}

# the mockups' albums (docs/mockups/src/render.py, ALBUMS; tests/test_scripts_demo_library.py
# holds the two together): artist, album, year, genre, cover seed, songs, kind, folder, what's odd
ALBUMS = [
    (
        "Lumen Drift",
        "Glass Harbor",
        2019,
        "Electronic",
        11,
        10,
        "flac",
        "2019 - Glass Harbor",
        "embedded-too large-cover back",
    ),
    ("The Paper Lanterns", "Northbound Static", 2021, "Indie Rock", 23, 12, "mp3", "", "id3v23"),
    ("Mara Okafor", "Salt & Ember", 2018, "Soul", 37, 11, "aac", "", "small-cover"),
    ("Kestrel Union", "Low Orbit", 2022, "Synthwave", 41, 9, "mp3", "2022 - Low Orbit", "track-04"),
    ("Cedar & Vale", "Quiet Acres", 2017, "Folk", 53, 13, "vorbis", "", "lower-keys"),
    ("Orbital Fern", "Spore Theory", 2020, "Ambient", 67, 8, "opus", "", ""),
    ("Juniper Sixes", "Velvet Hours", 2016, "Jazz", 71, 10, "alac", "", "embedded"),
    ("Hollow Coast", "Breakwater", 2023, "Alternative", 83, 11, "wav", "", ""),
    ("Nadia Reyes Trio", "Blue Hour Sessions", 2015, "Jazz", 97, 7, "aiff", "", ""),
    ("Static Bloom", "Neon Fieldwork", 2024, "Electronic", 101, 12, "mp3", "", "genres-in-one"),
    ("Ironwood Choir", "Hymns for Machines", 2019, "Classical", 113, 14, "flac", "", "embedded"),
    ("Ghost Meridian", "Afterlight", 2021, "Post-Rock", 127, 6, "mp3", "", "id3v1-too"),
    ("Lumen Drift", "Tide Tables", 2022, "Electronic", 131, 9, "flac", "Tide Tables", "tide"),
    ("Saffron Avenue", "Paper Moons", 2014, "Pop", 139, 12, "aac", "", ""),
    ("Mara Okafor", "Kindling", 2015, None, 149, 10, "mp3", "Kindling", "no-cover no-year"),
]
# further albums, so the Folders view has every shape of folder (R2.9, R5.8): an artist with two
# albums, three, five (Soundtracks), a Remixes folder of albums inside an artist's folder; one of
# the soundtracks names no album artist, only the compilation flag (R2.5.3); Live at the Lantern
# is an album in one file, its eight tracks in a .cue sheet beside it (R2.8, L09-needs-attention)
MORE_ALBUMS = [
    ("Mara Okafor", "Live at the Lantern", 2016, "Soul", 151, 8, "mp3", "", "one-file"),
    ("The Paper Lanterns", "Paper Weather", 2019, "Indie Rock", 461, 11, "flac", "", ""),
    (
        "Lumen Drift",
        "Glass Harbor Remixed",
        2020,
        "Electronic",
        301,
        7,
        "flac",
        "Remixes/Glass Harbor",
        "",
    ),
    (
        "Lumen Drift",
        "Tide Tables Remixed",
        2023,
        "Electronic",
        311,
        7,
        "mp3",
        "Remixes/Tide Tables",
        "",
    ),
    *[
        (
            "Various Artists",
            f"{name} (Original Soundtrack)",
            year,
            "Soundtrack",
            seed,
            6,
            kind,
            f"Soundtracks/{name}",
            odd,
        )
        for name, year, seed, kind, odd in (
            ("Low Tide Diaries", 2018, 431, "mp3", "compilation"),
            ("Paper Satellites", 2020, 433, "aac", "compilation"),
            ("The Long Signal", 2021, 439, "flac", "compilation"),
            ("Saltwater Town", 2022, 443, "opus", "compilation"),
            ("Night Ferry", 2024, 449, "vorbis", "compilation no-albumartist"),
        )
    ],
    # T06-fix-encoding (R4.10): tags saved as Windows-1251 in Latin-1 frames by an old tagger, and
    # the files named from them, so they read as gibberish (Ìàÿê for Маяк)
    ("Северный Ветер", "Тихая Гавань", 2009, "Rock", 457, 9, "mp3", "", "id3v23 cp1251"),
]
GLASS = [
    "Tidewater",
    "Glass Harbor",
    "Small Hours",
    "Signal Fires",
    "Undertow",
    "Parallax",
    "Lowlight",
    "Salt in the Wires",
    "Breakers",
    "Harbor Lights (Reprise)",
]
HARBOR = ["Тихая гавань", "Причал", "Туман", "Шторм", "Белые ночи", "Огни", "Прилив", "Маяк",
          "Утро"]  # fmt: skip  # Тихая Гавань's (T06)
TIDE = [
    "Neap Tide",
    "Spring Tide",
    "Slack Water",
    "Moonpull",
    "Ebb",
    "Perigee",
    "Bore",
    "Tidal Lock",
    "High Water Mark",
]
WORDS = [
    "Amber",
    "Arc",
    "Atlas",
    "Blue",
    "Cinder",
    "Copper",
    "Dawn",
    "Drift",
    "Echo",
    "Ember",
    "Fern",
    "Field",
    "Glass",
    "Harbor",
    "Hollow",
    "Iron",
    "Lantern",
    "Low",
    "Meridian",
    "Moon",
    "Night",
    "North",
    "Orbit",
    "Paper",
    "Quiet",
    "Salt",
    "Signal",
    "Silver",
    "Static",
    "Stone",
    "Tide",
    "Velvet",
    "Wire",
]


# the change history (R4.9, A3.5): saves made on two computers, each by MusiKata's own batch
# (tags.Batch, history.Recording), from the value written first (`before`) to the plan's, so the
# library ends as planned: (computer, when, what the save was, the album, the field, before,
# after: None for the plan's value). A save to another value is undone at the time UNDONE gives.
COMPUTERS = {
    "Studio-PC": "6f1c0a5e-2b7d-4c1e-9a43-0f2d8e5b7c11",
    "Laptop": "b2c4e6a8-1d3f-4a5b-8c7d-9e0f1a2b3c4d",
}
HISTORY = [
    ("Studio-PC", "2026-11-24T19:12:40", "Genre on 10 songs", "Glass Harbor", "genre",
     ["Electronica"], None),
    ("Laptop", "2026-11-25T20:45:12", "Year on 9 songs", "Low Orbit", "year", 2021, None),
    ("Laptop", "2026-11-25T20:52:03", "Album artist on 13 songs", "Quiet Acres", "albumartist",
     None, None),
    ("Studio-PC", "2026-11-25T21:30:00", "Album on 6 songs", "Afterlight", "album", None,
     "Afterlight (Deluxe)"),
]  # fmt: skip
UNDONE = {"Album on 6 songs": ("Laptop", "2026-11-25T21:31:20")}
# the root's own settings.json (R13.9, A2.10): the genres the user has said are the same (R9.5), so
# G01-genres' banner offers Tide Tables' Electronica beside its "electronic"; and a path pattern of
# the user's own (R3.3, R13.4), tried before the presets, so an album's folder is read for its
# songs' artist, as T01-infer-from-path detects it on Tide Tables
ROOT_SETTINGS = {
    "format": 1,
    "tags": {"same_genres": [["Electronic", "Electronica"]]},
    "patterns": {"user": ["{artist}/{album}/{track} - {title}"]},
}


@dataclass
class Song:
    """One file to write: its path under Music/, its kind, its tags (None: no tags at all), and how
    they're written (`shape`, docs/process/testing.md's "Shapes")."""

    path: str
    kind: str
    tags: dict[str, object] | None
    shape: set[str] = field(default_factory=set)
    tone: int = 440
    cover: tuple[int, int] | None = None  # embedded: (seed, size)
    back: tuple[int, int] | None = None  # a back cover embedded too (R5.2): (seed, size)
    seconds: float | None = None  # its length, when not the library's (an album in one file)


@dataclass
class Library:
    songs: list[Song]
    covers: dict[str, tuple[int, int]]  # folder -> (seed, size) of its cover.jpg
    playlists: dict[str, list[str]]  # path -> entries, as written
    # path -> how a playlist is written, when not as MusiKata writes one: its encoding (a BOM as
    # "utf-8-sig") and its line ends (R8.1.2's shapes)
    playlist_forms: dict[str, tuple[str, str]] = field(default_factory=dict)
    # folder -> its other images: (name, seed, size), a PNG (T02's back.png, R5.2)
    images: dict[str, list[tuple[str, int, int]]] = field(default_factory=dict)
    cues: dict[str, str] = field(default_factory=dict)  # path -> a .cue sheet's text (A2.6)
    # path -> an .lrc's text (R17.1), written as a Windows lyrics editor writes one: a BOM, CRLF
    lyrics: dict[str, str] = field(default_factory=dict)


def _titles(rng: random.Random, n: int) -> list[str]:
    return [f"{rng.choice(WORDS)} {rng.choice(WORDS)}" for _ in range(n)]


def _album(row, rng: random.Random, lib: Library) -> None:
    artist, album, year, genre, seed, count, kind, folder, odd = row
    odd = set(odd.split())
    named = as_latin1 if "cp1251" in odd else str  # files named from tags read as gibberish
    folder = f"{named(artist)}/{named(folder or album)}" if artist != "Various Artists" else folder
    titles = (
        GLASS
        if album == "Glass Harbor"
        else TIDE
        if album == "Tide Tables"
        else HARBOR
        if album == "Тихая Гавань"
        else _titles(rng, count)
    )
    ext = KINDS[kind][0]
    size = 300 if "small-cover" in odd else 1200 if "large-cover" in odd else 600
    if "embedded" not in odd and "no-cover" not in odd:
        lib.covers[folder] = (seed, size)
    if "back" in odd:  # T02: a back cover beside cover.jpg, and a smaller one in two songs
        lib.images[folder] = [("back.png", 311, 1400)]
    if "one-file" in odd:  # an album in one file, its tracks in a .cue sheet (A2.6, R2.8)
        _one_file(lib, folder, artist, album, year, genre, titles[:count], seed)
        for _ in titles[:count]:  # the ratings its tracks would have had: the albums after it
            rng.choice((0, 0, 3, 4, 5))  # are as they were
        return
    for n, title in enumerate(titles[:count], 1):
        tags: dict[str, object] = {
            "title": title,
            "artist": artist,
            "album": album,
            "albumartist": artist,
            "track": n,
            "tracktotal": count,
            "disc": 1,
            "disctotal": 1,
            "year": None if "no-year" in odd else year,
            "genre": [] if genre is None else [genre],
            "rating": rng.choice((0, 0, 3, 4, 5)),
        }
        if "compilation" in odd:
            tags["artist"] = f"{rng.choice(WORDS)} {rng.choice(WORDS)}"
            tags["compilation"] = True
        if "no-albumartist" in odd or "cp1251" in odd:  # T06's old tagger wrote none
            del tags["albumartist"]
        if "tide" in odd:  # the mockups' Tide Tables (N03, L05): the faults Needs attention shows
            tags["genre"] = [{2: "electronic", 5: "Electronica"}.get(n, "Electronic")]
            tags["year"] = None if n == 3 else year
            tags["artist"] = "lumen drift" if n == 4 else artist
        if "genres-in-one" in odd:
            tags["genre"] = [f"{genre}; Ambient"]
        lib.songs.append(
            Song(
                f"{folder}/{n:02d} - {named(title)}.{ext}",
                kind,
                tags,
                odd & {"id3v23", "id3v1-too", "track-04", "lower-keys", "cp1251"},
                220 + (seed * 7 + n * 31) % 660,
                (seed, size) if odd & {"embedded", "embedded-too"} else None,
                (211, 500) if "back" in odd and n in (3, 7) else None,
            )
        )


def as_latin1(text: str) -> str:
    """Text saved as Windows-1251 and read as Latin-1, as R4.10's gibberish is: Ìàÿê for
    Маяк."""
    return text.encode("cp1251").decode("latin-1")


ONE_FILE_SECONDS = 52 * 60 + 8  # Live at the Lantern's length (L07-folders-list)
SIGNAL_FIRES = "Lumen Drift/2019 - Glass Harbor/04 - Signal Fires.flac"
SIGNAL_COPY = "_Incoming/new rips/Signal Fires.flac"  # its exact copy (R2.12)
MOONPULL = "Lumen Drift/Tide Tables/04 - Moonpull.flac"
MOONPULL_COPY = "_Incoming/From Phone/Moonpull (radio).m4a"  # a likely copy of it (R2.12)
# the plays of the copies L09 shows, as Studio-PC's plays.json has them (R7.9, A2.8)
PLAYS = {SIGNAL_FIRES: 52, SIGNAL_COPY: 3, MOONPULL: 18, MOONPULL_COPY: 6}
PLAYED = "2026-11-25T20:41:00Z"
# Signal Fires' timed lyrics beside it (R17.1, N04-now-playing-lyrics), made up as the mockup's are:
# LRC's own tags, pauses between verses, a chorus sung twice (two times on one line) and one line
# with enhanced LRC's word times
SIGNAL_LYRICS = """[ar:Lumen Drift]
[ti:Signal Fires]
[al:Glass Harbor]
[by:MusiKata demo]
[length:04:18]
[offset:0]

[00:21.50]Grey light on the breakwater
[00:26.00]gulls above the pier
[00:30.40]every rope is fraying
[00:34.90]every year a year
[00:39.50]
[01:12.00]Lanterns on the water line
[01:16.40]counting ships that never came
[01:20.90]every harbour keeps a light
[01:25.30]every light a different name
[01:30.00]
[01:36.00][02:40.00]We were signal fires, burning on the shore
[01:40.60][02:44.60]calling out to no one, calling out for more
[01:45.20][02:49.20]and the tide came in to take the words away
[01:49.80][02:53.80]still I kept the embers for another day
[01:54.50][02:58.50]
[02:02.00]Salt across the windows
[02:06.40]static on the line
[02:10.90]every wave a question
[02:15.30]<02:15.30>every <02:15.90>shore <02:16.40>a <02:16.80>sign
[02:20.00]
[03:30.00]Signal fires
[03:34.50]signal fires
[03:40.00]
"""


def _one_file(lib: Library, folder: str, artist: str, album: str, year: int, genre: str | None,
              titles: list[str], seed: int) -> None:  # fmt: skip
    """An album kept as one file, with a .cue sheet beside it naming its tracks, as a ripper
    writes one (A2.6): over 20 minutes, so it is "Album in one file" in Needs attention."""
    name = f"{album}.mp3"
    tags = {"title": album, "artist": artist, "album": album, "albumartist": artist,
            "year": year, "genre": [genre] if genre else [], "rating": 0}  # fmt: skip
    lib.songs.append(Song(f"{folder}/{name}", "mp3", tags, set(), 220 + seed % 660,
                          seconds=ONE_FILE_SECONDS))  # fmt: skip
    lines = ["REM GENRE " + (genre or ""), f"REM DATE {year}", f'PERFORMER "{artist}"',
             f'TITLE "{album}"', f'FILE "{name}" MP3']  # fmt: skip
    step = ONE_FILE_SECONDS // len(titles)
    for n, title in enumerate(titles, 1):
        at = (n - 1) * step
        lines += [f"  TRACK {n:02d} AUDIO", f'    TITLE "{title}"',
                  f"    INDEX 01 {at // 60:02d}:{at % 60:02d}:00"]  # fmt: skip
    lib.cues[f"{folder}/{album}.cue"] = "\r\n".join(lines) + "\r\n"


def plan(seed: int = 1) -> Library:
    """The mockups' library, as plain data: what build writes."""
    rng = random.Random(seed)
    lib = Library([], {}, {})
    for row in ALBUMS + MORE_ALBUMS:
        _album(row, rng, lib)
    # loose files beside an artist's albums (L06's Lumen Drift, L07's Mara Okafor), one with no tags
    loose = [
        (
            "Lumen Drift/Lumen Drift - Harbor Lights.flac",
            "Harbor Lights",
            "Lumen Drift",
            "Harbor Lights - Single",
        ),
        (
            "Lumen Drift/Lumen Drift - Lowlight (Radio Edit).mp3",
            "Lowlight (Radio Edit)",
            "Lumen Drift",
            "Glass Harbor",
        ),
        ("Lumen Drift/lumen drift - ebb & flow.mp3", "ebb & flow", "lumen drift", ""),
        ("Mara Okafor/Ember (live take).mp3", "Ember (live take)", "Mara Okafor", ""),
        ("Mara Okafor/Kindling (acoustic).m4a", "Kindling (acoustic)", "Mara Okafor", ""),
    ]
    for path, title, artist, album in loose:
        kind = {"flac": "flac", "mp3": "mp3", "m4a": "aac"}[path.rsplit(".", 1)[1]]
        tags = {"title": title, "artist": artist, "album": album, "genre": [], "rating": 0}
        lib.songs.append(Song(path, kind, tags, set(), 330))
    lib.songs.append(Song("Mara Okafor/untitled 03.mp3", "mp3", None))
    # _Incoming: files whose tags say nothing, for R3 and R12 (T01, T02, M04's moves)
    for n in range(1, 4):
        lib.songs.append(
            Song(f"_Incoming/new rips/track{n:02d}.mp3", "mp3", None, tone=300 + n * 40)
        )
    # the same song more than once (R2.12, L09-needs-attention): an exact copy of Signal Fires (its
    # audio, retagged), and Moonpull as a phone saved it, a likely copy (a second longer, as AAC)
    glass = next(s for s in lib.songs if s.path == SIGNAL_FIRES)
    copied = {"title": "Signal Fires", "artist": "Lumen Drift", "genre": [], "rating": 4}
    lib.songs.append(Song(SIGNAL_COPY, glass.kind, copied, tone=glass.tone))
    lib.songs.append(
        Song(
            MOONPULL_COPY,
            "aac",
            {"title": "Moonpull", "artist": "Lumen Drift", "genre": [], "rating": 0},
            seconds=2.0,
        )
    )
    lib.lyrics[SIGNAL_FIRES.rsplit(".", 1)[0] + ".lrc"] = SIGNAL_LYRICS
    _playlists(lib)
    _apart(lib, {SIGNAL_COPY})
    return lib


def _playlists(lib: Library) -> None:
    """The playlists of P01-playlist-drag (R8): Road Trip as MusiKata writes one (R8.1), its songs
    as the mockup orders them and one missing, which Needs attention's Find looks for (R8.7);
    Evening Focus as a Windows player writes one (a BOM, CRLF, `\\`, no #EXTINF); Rainy Day an
    `.m3u` in Windows' Western encoding with CRLF, naming the album whose tags are in the wrong
    encoding by its folder."""
    paths = [s.path for s in lib.songs]

    def song(album: str, n: int = 1) -> Song:
        found = [s for s in lib.songs if s.tags and s.tags.get("album") == album]
        return next(s for s in found if s.tags and s.tags.get("track") == n)

    def extinf(s: Song) -> str:
        tags = s.tags or {}
        return f"#EXTINF:{round(s.seconds or 1)},{tags.get('artist')} - {tags.get('title')}"

    road = [
        song("Northbound Static"), song("Breakwater"), song("Low Orbit"), song("Afterlight"),
        song("Glass Harbor", 4), song("Paper Moons"), song("Velvet Hours"),
        song("Northbound Static", 2), song("Quiet Acres", 3), song("Neon Fieldwork", 5),
    ]  # fmt: skip
    lines = ["#EXTM3U"]
    for s in road:
        lines += [extinf(s), "../" + s.path]
    # missing: Needs attention's Find (R8.7)
    lines += [
        "#EXTINF:-1,Lumen Drift - Slack Tide",
        "../Lumen Drift/Tide Tables/10 - Slack Tide.flac",
    ]
    lib.playlists["Playlists/Road Trip.m3u8"] = lines
    evening = [song("Spore Theory", n) for n in range(1, 5)] + [
        song("Blue Hour Sessions", n) for n in range(1, 4)
    ]
    rel = "Playlists/Evening Focus.m3u8"
    lib.playlists[rel] = ["..\\" + s.path.replace("/", "\\") for s in evening]
    lib.playlist_forms[rel] = ("utf-8-sig", "\r\n")
    rainy = [p for p in paths if p.startswith("Ñåâåðíûé Âåòåð/")][:5] + [
        p for p in paths if p.startswith("Mara Okafor/Kindling/")
    ][:4]
    rel = "Playlists/Rainy Day.m3u"
    lib.playlists[rel] = ["#EXTM3U", *("../" + p for p in rainy)]
    lib.playlist_forms[rel] = ("cp1252", "\r\n")


def _apart(lib: Library, copies: set[str]) -> None:
    """Every song's audio its own (A2.3: songs of one kind, tone and length are exact copies,
    R2.12), but the `copies` meant as such: a song whose audio another's before it has gets the
    next tone free."""
    taken: set[tuple[str, int, float | None]] = set()
    for song in lib.songs:
        if song.path in copies:
            continue
        while (song.kind, song.tone, song.seconds) in taken:
            song.tone += 1
        taken.add((song.kind, song.tone, song.seconds))


def more(lib: Library, songs: int, seed: int = 1) -> None:
    """Albums of made-up names under More/ until lib holds `songs` songs, ten to an album, each
    kind in turn (R1.11's library at 50,000)."""
    rng = random.Random(seed + 1)
    kinds = list(KINDS)
    a = 0
    while len(lib.songs) < songs:
        a += 1
        artist = f"Artist {a // 5 + 1:04d}"
        kind = kinds[a % len(kinds)]
        album = f"{rng.choice(WORDS)} {rng.choice(WORDS)} {a}"
        n_songs = min(10, songs - len(lib.songs))
        for n in range(1, n_songs + 1):
            title = f"{rng.choice(WORDS)} {rng.choice(WORDS)}"
            lib.songs.append(
                Song(
                    f"More/{artist}/{album}/{n:02d} - {title}.{KINDS[kind][0]}",
                    kind,
                    {
                        "title": title,
                        "artist": artist,
                        "album": album,
                        "albumartist": artist,
                        "track": n,
                        "tracktotal": n_songs,
                        "year": 1990 + a % 35,
                        "genre": [rng.choice(("Electronic", "Jazz", "Folk", "Pop", "Ambient"))],
                        "rating": 0,
                    },
                    set(),
                    220 + a % 660,
                )
            )


# ---------- writing: PyAV encodes, Mutagen tags ----------


LONG_RATE = 8000  # a long song's rate, mono at LONG_BITS, so an hour is a few megabytes
LONG_BITS = 8000


def loudness(n: int, tone: int):
    """A song's loudness over its `n` samples, rising and falling as music does, with a quiet
    bridge in its middle, so its waveform (R11.1) looks like a song's, as the mockups draw it."""
    import numpy as np

    u = np.arange(n) / max(1, n)
    env = 0.35 + 0.45 * np.sin(np.pi * u) ** 0.6 + 0.15 * np.sin(23 * u) * np.sin(7 * u)
    env[(u > 0.47) & (u < 0.53)] *= 0.45
    beats = np.random.default_rng(tone + 1).random(200)  # a step of its own every 200th
    env *= 0.55 + 0.45 * beats[np.minimum((u * 200).astype(int), 199)]
    return np.clip(env, 0.06, 1.0)


def encode(path: str, kind: str, seconds: float, tone: int) -> None:
    """A tone with a little noise, `seconds` long, its loudness rising and falling (`loudness`),
    as `kind` (PyAV's FFmpeg); an MP3 longer than a minute (an album in one file) at a low rate,
    so it stays small."""
    import av
    import numpy as np

    _ext, fmt, codec, sample_fmt, rate = KINDS[kind]
    long = kind == "mp3" and seconds > 60
    rate = LONG_RATE if long else rate
    n = int(rate * seconds)
    t = np.arange(n) / rate
    noise = np.random.default_rng(tone).standard_normal(n)
    x = (0.3 * loudness(n, tone) * np.sin(2 * np.pi * tone * t) + 0.02 * noise).astype(np.float32)
    layout = "mono" if long else "stereo"
    both = np.stack([x]) if long else np.stack([x, x])
    with av.open(path, "w", format=fmt) as out:
        stream = out.add_stream(codec, rate=rate, layout=layout)
        if codec == "vorbis":
            stream.codec_context.options = {"strict": "experimental"}
        if long:
            stream.codec_context.bit_rate = LONG_BITS
        stream.codec_context.format = sample_fmt
        step = stream.codec_context.frame_size or 1024
        for i in range(0, n, step):
            chunk = both[:, i : i + step]
            if sample_fmt.startswith("s16"):
                chunk = (chunk * 32767).astype(np.int16)
            arr = chunk.T.reshape(1, -1) if sample_fmt == "s16" else chunk
            frame = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(arr), format=sample_fmt, layout=layout
            )
            frame.sample_rate, frame.pts, frame.time_base = rate, i, fractions.Fraction(1, rate)
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)


def cover_jpeg(seed: int, size: int) -> bytes:
    """A made-up cover: two colours from the seed, blended corner to corner (PyAV's JPEG)."""
    import av
    import numpy as np

    rng = random.Random(seed)
    a, b = (np.array([rng.randrange(40, 230) for _ in range(3)], float) for _ in range(2))
    ramp = np.add.outer(np.arange(size), np.arange(size)) / (2 * size - 2)
    img = (a * (1 - ramp[..., None]) + b * ramp[..., None]).astype(np.uint8)
    ctx = av.CodecContext.create("mjpeg", "w")
    ctx.width = ctx.height = size
    ctx.pix_fmt = "yuvj420p"
    ctx.time_base = fractions.Fraction(1, 25)
    frame = av.VideoFrame.from_ndarray(img, format="rgb24").reformat(format="yuvj420p")
    return b"".join(bytes(p) for p in [*ctx.encode(frame), *ctx.encode(None)])


def cover_png(seed: int, size: int) -> bytes:
    """A made-up picture as a PNG: diagonal stripes of two colours from the seed (PyAV's PNG)."""
    import av
    import numpy as np

    rng = random.Random(seed)
    a, b = (np.array([rng.randrange(40, 230) for _ in range(3)], np.uint8) for _ in range(2))
    stripes = (np.add.outer(np.arange(size), np.arange(size)) // max(1, size // 12)) % 2
    img = np.where(stripes[..., None] == 0, a, b).astype(np.uint8)
    ctx = av.CodecContext.create("png", "w")
    ctx.width = ctx.height = size
    ctx.pix_fmt = "rgb24"
    ctx.time_base = fractions.Fraction(1, 25)
    frame = av.VideoFrame.from_ndarray(img, format="rgb24")
    return b"".join(bytes(p) for p in [*ctx.encode(frame), *ctx.encode(None)])


def tag(path: str, song: Song) -> None:
    """The song's tags, written the way its shape says (A3.2's mapping)."""
    t = song.tags
    if t is None:
        return
    kind = song.kind
    if kind in ("mp3", "wav", "aiff"):
        _tag_id3(path, song)
    elif kind in ("flac", "vorbis", "opus"):
        _tag_vorbis(path, song)
    else:
        _tag_mp4(path, song)


def _tag_id3(path: str, song: Song) -> None:
    import mutagen.aiff
    import mutagen.id3 as id3
    import mutagen.wave

    t = song.tags or {}
    f = {"wav": mutagen.wave.WAVE, "aiff": mutagen.aiff.AIFF}.get(song.kind)
    if f is not None:
        audio = f(path)
        audio.add_tags()
        tags = audio.tags
    else:
        tags = id3.ID3()
    v23 = "id3v23" in song.shape
    total = t.get("tracktotal")
    # an old tagger's Windows-1251 in frames marked Latin-1 (R4.10, A3.6), else Unicode
    encoding, text = (0, as_latin1) if "cp1251" in song.shape else (3, str)
    if t.get("title"):
        tags.add(id3.TIT2(encoding=encoding, text=text(str(t["title"]))))
    for key, frame in (("artist", id3.TPE1), ("album", id3.TALB), ("albumartist", id3.TPE2)):
        if t.get(key):
            tags.add(frame(encoding=encoding, text=text(str(t[key]))))
    if t.get("track"):
        track = f"{t['track']:02d}" if "track-04" in song.shape else f"{t['track']}/{total}"
        tags.add(id3.TRCK(encoding=3, text=track))
    if t.get("year"):
        tags.add((id3.TYER if v23 else id3.TDRC)(encoding=3, text=str(t["year"])))
    if t.get("genre"):
        tags.add(id3.TCON(encoding=3, text=[str(g) for g in t["genre"]]))  # type: ignore[union-attr]
    if t.get("compilation"):
        tags.add(id3.TCMP(encoding=3, text="1"))
    if t.get("rating"):
        stars = int(t["rating"])  # type: ignore[call-overload]
        tags.add(
            id3.POPM(email="Windows Media Player 9 Series", rating=[0, 1, 64, 128, 196, 255][stars])
        )
    if song.cover:
        tags.add(
            id3.APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=cover_jpeg(*song.cover))
        )
    if f is not None:
        audio.save(v2_version=3 if v23 else 4)
    else:
        tags.save(path, v2_version=3 if v23 else 4, v1=2 if "id3v1-too" in song.shape else 0)


def _tag_vorbis(path: str, song: Song) -> None:
    import base64

    import mutagen
    from mutagen.flac import Picture

    t = song.tags or {}
    audio = mutagen.File(path)
    lower = "lower-keys" in song.shape
    for key, value in (
        ("TITLE", t.get("title")),
        ("ARTIST", t.get("artist")),
        ("ALBUM", t.get("album")),
        ("ALBUMARTIST", t.get("albumartist")),
        ("TRACKNUMBER", t.get("track")),
        ("TRACKTOTAL", t.get("tracktotal")),
        ("DATE", t.get("year")),
        ("COMPILATION", "1" if t.get("compilation") else None),
    ):
        if value:
            audio[key.lower() if lower else key] = str(value)
    if t.get("genre"):
        audio["genre" if lower else "GENRE"] = [str(g) for g in t["genre"]]  # type: ignore[union-attr]
    if t.get("rating"):
        audio["RATING"] = str(int(t["rating"]) * 20)  # type: ignore[call-overload]
    if song.cover:
        pic = Picture()
        pic.type, pic.mime, pic.width, pic.height, pic.depth = (
            3,
            "image/jpeg",
            song.cover[1],
            song.cover[1],
            24,
        )
        pic.data = cover_jpeg(*song.cover)
        if song.kind == "flac":
            audio.add_picture(pic)
        else:
            audio["METADATA_BLOCK_PICTURE"] = base64.b64encode(pic.write()).decode()
    if song.back and song.kind == "flac":  # a back cover beside the front (R5.2)
        back = Picture()
        back.type, back.mime, back.desc = 4, "image/jpeg", "Back"
        back.width = back.height = song.back[1]
        back.depth = 24
        back.data = cover_jpeg(*song.back)
        audio.add_picture(back)
    audio.save()


def _tag_mp4(path: str, song: Song) -> None:
    from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

    t = song.tags or {}
    audio = MP4(path)
    for key, atom in (
        ("title", "\xa9nam"),
        ("artist", "\xa9ART"),
        ("album", "\xa9alb"),
        ("albumartist", "aART"),
        ("year", "\xa9day"),
    ):
        if t.get(key):
            audio[atom] = str(t[key])
    if t.get("genre"):
        audio["\xa9gen"] = [str(g) for g in t["genre"]]  # type: ignore[union-attr]
    if t.get("track"):
        audio["trkn"] = [(int(t["track"]), int(t.get("tracktotal") or 0))]  # type: ignore[call-overload]
    if t.get("compilation"):
        audio["cpil"] = True
    if t.get("rating"):  # R10.4: 20 … 100
        stars = int(t["rating"])  # type: ignore[call-overload]
        audio["----:com.apple.iTunes:RATING"] = [MP4FreeForm(str(stars * 20).encode())]
    if song.cover:
        audio["covr"] = [MP4Cover(cover_jpeg(*song.cover), imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def before_history(song: Song, saves: list = HISTORY) -> Song:
    """The song as first written: each field a save of `saves` brings to the plan's value holds
    its value from before that save."""
    if song.tags is None:
        return song
    tags = dict(song.tags)
    for _computer, _when, _what, album, name, before, after in saves:
        if after is None and tags.get("album") == album:
            tags[name] = before
    return Song(song.path, song.kind, tags, song.shape, song.tone, song.cover, song.back,
                song.seconds)  # fmt: skip


def history(music: str, lib: Library, saves: list = HISTORY, undone: dict = UNDONE) -> list[str]:
    """The change history's saves (`HISTORY`), each made by MusiKata's own batch into Music's
    .musikata/history at its time, on its computer, and those UNDONE undone by MusiKata's Undo;
    each computer named by its play file, as A2.8's are, Studio-PC's holding the plays of L09's
    copies (`PLAYS`, R2.12). The entries made, by name."""
    from datetime import UTC, datetime

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    from musikata_core import history as change_history
    from musikata_core import rootfiles, scanner, tags

    class At:
        def __init__(self, when: str) -> None:
            self.when = datetime.fromisoformat(when).replace(tzinfo=UTC)

        def now(self) -> datetime:
            return self.when

        def monotonic(self) -> float:
            return 0.0

    def write(job: tags.Job) -> tags.Written:
        return tags.save(job.path, job.changes, audio_hash=scanner.audio_hash)

    made = []
    for computer, when, what, album, name, _before, after in saves:
        field_name = "genres" if name == "genre" else name
        jobs = [
            tags.Job(os.path.join(music, s.path), {field_name: s.tags[name] if after is None
                                                   else after})
            for s in lib.songs if s.tags is not None and s.tags.get("album") == album
        ]  # fmt: skip
        record = change_history.Recording(music, lambda c=computer: COMPUTERS[c], At(when))
        out = tags.Batch(jobs, write, record=record, description=what).run()
        if out.failed or out.entry is None:
            raise RuntimeError(f"the save {what!r} failed: {out.failed}")
        made.append(out.entry)
        if what in undone:
            by, at = undone[what]
            entry = change_history.read(change_history.folder_of(music), out.entry)
            assert isinstance(entry, change_history.Entry)
            plan = change_history.plan(entry, music, lambda h: [])
            record = change_history.Recording(music, lambda c=by: COMPUTERS[c], At(at), out.entry)
            done = change_history.undo(plan, music, False, write, record)
            if done.failed or done.entry is None:
                raise RuntimeError(f"undoing {what!r} failed: {done.failed}")
            made.append(done.entry)
    kinds = {s.path: s.kind for s in lib.songs}
    plays = [{"path": p, "hash": scanner.audio_hash(os.path.join(music, p), kinds[p]),
              "count": n, "last": PLAYED} for p, n in PLAYS.items() if p in kinds]  # fmt: skip
    for name, computer in COMPUTERS.items():
        doc = {"format": 1, "computer": {"id": computer, "name": name},
               "songs": plays if name == "Studio-PC" else []}  # fmt: skip
        path = rootfiles.file_of(rootfiles.folder_of(music), computer)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=2) + "\n")
    return made


def build(dest: str, songs: int = 0, seconds: float = 1.0, seed: int = 1) -> Library:
    """DIR/Music: the plan, written. Each kind is encoded once per tone and copied; tags are per
    file."""
    lib = plan(seed)
    if songs:
        more(lib, songs, seed)
    music = os.path.join(dest, "Music")
    if os.path.exists(music):
        shutil.rmtree(music)
    cache = os.path.join(dest, ".encoded")
    os.makedirs(cache, exist_ok=True)
    for song in lib.songs:
        path = os.path.join(music, song.path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ext = KINDS[song.kind][0]
        length = song.seconds or seconds
        made = os.path.join(cache, f"{song.kind}-{song.tone}-{length}.{ext}")
        if not os.path.exists(made):
            encode(made + ".part." + ext, song.kind, length, song.tone)
            os.replace(made + ".part." + ext, made)
        shutil.copyfile(made, path)
        tag(path, before_history(song))
    for folder, (cseed, size) in lib.covers.items():
        with open(os.path.join(music, folder, "cover.jpg"), "wb") as f:
            f.write(cover_jpeg(cseed, size))
    for folder, images in lib.images.items():
        for name, iseed, size in images:
            with open(os.path.join(music, folder, name), "wb") as f:
                f.write(cover_png(iseed, size))
    for rel, text in lib.cues.items():
        with open(os.path.join(music, rel), "w", encoding="utf-8", newline="") as f:
            f.write(text)
    for rel, text in lib.lyrics.items():
        with open(os.path.join(music, rel), "w", encoding="utf-8-sig", newline="") as f:
            f.write(text.replace("\n", "\r\n"))
    for rel, lines in lib.playlists.items():
        path = os.path.join(music, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        encoding, end = lib.playlist_forms.get(rel, ("utf-8", "\n"))
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(end.join(lines) + end)
    history(music, lib)
    root_settings(music)
    smart_playlist(music)
    return lib


def smart_playlist(music: str) -> str:
    """P02's Four stars and up (R8.9): a smart playlist of the songs rated four stars and up,
    highest first, made as MusiKata makes one, its songs those its rule picks from the library
    scanned into an index of its own, as the tour's will be; so the tour, whose root can't be
    written, finds it current. Its path."""
    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    from musikata_core import db, playlists, scanner, smart

    rule = smart.Rule(rating=4, order="rating")
    with tempfile.TemporaryDirectory() as tmp:
        index = db.Index(os.path.join(tmp, "musikata.db"))
        try:
            with ThreadPoolExecutor(4) as pool:
                scanner.scan(music, index, pool, hold=False)
            paths = smart.songs(index.read(), rule, 0.0)
            made = playlists.Store(music, index).create_smart(
                rule, paths, smart.suggested_name(rule)
            )
            return os.path.join(music, playlists.FOLDER, made.name + ".m3u8")
        finally:
            index.close()


def root_settings(music: str, settings: dict = ROOT_SETTINGS) -> str:
    """Music's .musikata/settings.json (`ROOT_SETTINGS`); its path."""
    path = os.path.join(music, ".musikata", "settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(settings, indent=2) + "\n")
    return path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="what", required=True)
    b = sub.add_parser("build", help="write DIR/Music")
    b.add_argument("dir")
    b.add_argument("--songs", type=int, default=0, help="add made-up albums until it holds N songs")
    b.add_argument("--seconds", type=float, default=1.0, help="each song's length (1 s)")
    args = ap.parse_args(argv)
    lib = build(args.dir, args.songs, args.seconds)
    kinds = sorted({s.kind for s in lib.songs})
    print(f"{len(lib.songs)} songs in {os.path.join(args.dir, 'Music')} ({', '.join(kinds)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
