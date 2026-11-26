"""The demo library (docs/architecture/A6-packaging-and-platforms.md, A6.7; docs/process/
development.md, "The demo library"): short generated audio in every kind of R2.2, tagged with the
mockups' made-up artists and albums, some of them wrong on purpose, and written the ways other
programs write tags (docs/process/testing.md, "Shapes"). Real music is never used.

    .venv/bin/python scripts/demo_library.py build DIR [--songs N] [--seconds S]

writes DIR/Music: the mockups' library (about 240 songs), and with --songs N more albums of made-up
names until it holds N songs (R1.11's 50,000). It runs on the release's Python with PyAV, Mutagen
and NumPy (packaging/versions.env): PyAV's own FFmpeg encodes every kind, so nothing else is needed.

What it plans is plain data (plan, more), so the tests read it without encoding anything; build
writes it.
"""

from __future__ import annotations

import argparse
import fractions
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
    ("Lumen Drift", "Glass Harbor", 2019, "Electronic", 11, 10, "flac", "2019 - Glass Harbor", ""),
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
# the soundtracks names no album artist, only the compilation flag (R2.5.3)
MORE_ALBUMS = [
    ("Mara Okafor", "Live at the Lantern", 2016, "Soul", 151, 8, "mp3", "", ""),
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


@dataclass
class Library:
    songs: list[Song]
    covers: dict[str, tuple[int, int]]  # folder -> (seed, size) of its cover.jpg
    playlists: dict[str, list[str]]  # path -> entries, as written


def _titles(rng: random.Random, n: int) -> list[str]:
    return [f"{rng.choice(WORDS)} {rng.choice(WORDS)}" for _ in range(n)]


def _album(row, rng: random.Random, lib: Library) -> None:
    artist, album, year, genre, seed, count, kind, folder, odd = row
    odd = set(odd.split())
    folder = f"{artist}/{folder or album}" if artist != "Various Artists" else folder
    titles = (
        GLASS
        if album == "Glass Harbor"
        else TIDE
        if album == "Tide Tables"
        else _titles(rng, count)
    )
    ext = KINDS[kind][0]
    size = 300 if "small-cover" in odd else 600
    if "embedded" not in odd and "no-cover" not in odd:
        lib.covers[folder] = (seed, size)
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
        if "no-albumartist" in odd:
            del tags["albumartist"]
        if "tide" in odd:  # the mockups' Tide Tables (N03, L05): the faults Needs attention shows
            tags["genre"] = [{2: "electronic", 5: "Electronica"}.get(n, "Electronic")]
            tags["year"] = None if n == 3 else year
            tags["artist"] = "lumen drift" if n == 4 else artist
        if "genres-in-one" in odd:
            tags["genre"] = [f"{genre}; Ambient"]
        lib.songs.append(
            Song(
                f"{folder}/{n:02d} - {title}.{ext}",
                kind,
                tags,
                odd & {"id3v23", "id3v1-too", "track-04", "lower-keys"},
                220 + (seed * 7 + n * 31) % 660,
                (seed, size) if "embedded" in odd else None,
            )
        )


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
    lib.songs.append(
        Song(
            "_Incoming/From Phone/Moonpull (radio).m4a",
            "aac",
            {"title": "Moonpull (radio)", "genre": [], "rating": 0},
        )
    )
    lib.playlists["Playlists/Road Trip.m3u8"] = [
        "#EXTM3U",
        "../Lumen Drift/2019 - Glass Harbor/04 - Signal Fires.flac",
        "../Kestrel Union/2022 - Low Orbit/01 - "
        + lib.songs[
            [s.path for s in lib.songs].index(
                next(s.path for s in lib.songs if s.path.startswith("Kestrel Union/"))
            )
        ].tags["title"]
        + ".mp3",
        "../Lumen Drift/Tide Tables/10 - Slack Tide.flac",  # missing: Needs attention's Find (R8.7)
    ]
    return lib


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


def encode(path: str, kind: str, seconds: float, tone: int) -> None:
    """A tone with a little noise, `seconds` long, as `kind` (PyAV's FFmpeg)."""
    import av
    import numpy as np

    _ext, fmt, codec, sample_fmt, rate = KINDS[kind]
    n = int(rate * seconds)
    t = np.arange(n) / rate
    noise = np.random.default_rng(tone).standard_normal(n)
    x = (0.3 * np.sin(2 * np.pi * tone * t) + 0.02 * noise).astype(np.float32)
    both = np.stack([x, x])
    with av.open(path, "w", format=fmt) as out:
        stream = out.add_stream(codec, rate=rate, layout="stereo")
        if codec == "vorbis":
            stream.codec_context.options = {"strict": "experimental"}
        stream.codec_context.format = sample_fmt
        step = stream.codec_context.frame_size or 1024
        for i in range(0, n, step):
            chunk = both[:, i : i + step]
            if sample_fmt.startswith("s16"):
                chunk = (chunk * 32767).astype(np.int16)
            arr = chunk.T.reshape(1, -1) if sample_fmt == "s16" else chunk
            frame = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(arr), format=sample_fmt, layout="stereo"
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
    if t.get("title"):
        tags.add(id3.TIT2(encoding=3, text=str(t["title"])))
    for key, frame in (("artist", id3.TPE1), ("album", id3.TALB), ("albumartist", id3.TPE2)):
        if t.get(key):
            tags.add(frame(encoding=3, text=str(t[key])))
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
        made = os.path.join(cache, f"{song.kind}-{song.tone}-{seconds}.{ext}")
        if not os.path.exists(made):
            encode(made + ".part." + ext, song.kind, seconds, song.tone)
            os.replace(made + ".part." + ext, made)
        shutil.copyfile(made, path)
        tag(path, song)
    for folder, (cseed, size) in lib.covers.items():
        with open(os.path.join(music, folder, "cover.jpg"), "wb") as f:
            f.write(cover_jpeg(cseed, size))
    for rel, lines in lib.playlists.items():
        path = os.path.join(music, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return lib


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
