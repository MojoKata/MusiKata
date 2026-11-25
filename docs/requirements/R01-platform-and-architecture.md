# R1. Platform and architecture

R1.1. MusiKata runs on what its tests cover (`docs/process/testing.md`):

- Linux x86_64: Linux Mint 22.3, LMDE 7, Ubuntu 24.04 LTS and Ubuntu 26.04 LTS. A later Mint or
  LMDE release joins once the tests move to it.
- Windows 10 22H2 and Windows 11, x64.
- macOS 14 and newer, as two apps: one for Apple silicon (arm64), one for Intel (x86_64).

R1.2. Everything is written in Python, and MusiKata runs on the Python its release carries: the
AppImage, the Windows installer and the macOS app each carry one, of one version for all three,
with one PySide6, both set in `packaging/versions.env`. Running from source is for development
only, never a way to install MusiKata, and uses that same version.

R1.2.1. The GUI uses PySide6 (Qt 6 with QML) and the `Basic` Qt Quick Controls style, with the look
of R6.2. Playback is MusiKata's own, so it can be gapless (R7.6) and equalized (R19): songs are
decoded with PyAV, FFmpeg's Python binding, and played through Qt Multimedia's audio output (A4).

R1.2.2. Tags are read and written with Mutagen (A3), and the visualizations' arithmetic uses NumPy
(A5), as is the equalizer's (R19). Nothing else is added without a reason written in the
architecture.

R1.3. MusiKata runs as the desktop user, with no service and no administrator rights: one app, whose
worker processes (A1.3) are its own and end when it quits. It reads and writes only the music root
(R2.1), its own data folders (R1.5) and the files the user hands it.

R1.4. Distribution:

- Linux: an AppImage, x86_64, that installs itself into the app menu on first start and, when
  asked, updates itself (R1.9).
- Windows: an Inno Setup installer, for the current user by default, without a UAC prompt.
- macOS: two `.dmg`s, one for Apple silicon and one for Intel, each holding `MusiKata.app`, and
  MusiKata's own Homebrew tap (`brew install --cask mojokata/musikata/musikata`), which picks the
  right one. They are ad-hoc signed, so the first start needs **Open Anyway** in System Settings ›
  Privacy & Security, once. With a Developer ID they become signed and notarized, and MusiKata moves
  to Homebrew's own casks (`build-and-release.md`).

R1.5. **Local data,** in three places:

- **The root's own folder,** `<root>/.musikata/`: what belongs to the library and goes with it to
  any computer: the root's settings (`settings.json`), play counts (`plays/`, a file per computer,
  R7.9), ratings that can't go in a file (`ratings.json`, R10.3), Needs attention dismissals
  (`ignored.json`, R2.8) and the change history (`history/`, R4.9). Plain files, each replaced whole
  when it changes, so two computers sharing a root never hold a lock and neither loses the other's
  changes (A2.8).
- **The shared settings** (`settings.json`), the same for every root (which settings are which:
  R13.9): `~/.musikata/` on Linux, `%USERPROFILE%\.musikata\` on Windows, `~/Library/Application
  Support/MusiKata/` on macOS.
- **This computer's index and caches,** one set per root: the library index, a SQLite database
  (`musikata.db`) whose schema is versioned and migrated at start, and the caches (cover thumbnails,
  waveforms, lookup answers); and the App log (R14) in text files. A root's set follows the root
  when its drive is mounted at another path, and is removed when the root hasn't been opened for 180
  days (A2.9).

| | Index, per root | Caches, per root | App log |
|---|---|---|---|
| Linux | `~/.local/share/musikata/roots/` (`$XDG_DATA_HOME`) | `~/.cache/musikata/` (`$XDG_CACHE_HOME`) | `~/.local/state/musikata/` (`$XDG_STATE_HOME`) |
| Windows | `%LOCALAPPDATA%\MusiKata\Roots\` | `%LOCALAPPDATA%\MusiKata\Cache\` | `%LOCALAPPDATA%\MusiKata\Logs\` |
| macOS | `~/Library/Application Support/MusiKata/Roots/` | `~/Library/Caches/MusiKata/` | `~/Library/Logs/MusiKata/` |

R1.5.1. Deleting the index and the caches loses only time: the next start scans the root again
and finds every tag, cover, rating and playlist in its files and every play, dismissal and past
save in its `.musikata` folder (Principle 1).

R1.5.2. A root whose `.musikata` folder can't be written (a read-only share, a full drive) still
opens. Its settings can't be changed, and Settings says why; its plays, dismissals and change
history are kept in this computer's index only, and Settings says that too.

R1.6. **One MusiKata at a time.** Starting MusiKata while it is already running (from the app menu,
or by opening a music file or playlist with it) hands its arguments to the running MusiKata over a
local socket, one per user and data folder, and exits. The running MusiKata shows its window and
plays or opens what it was handed. Started with another music root than the one open (`--root`,
R2.1), it asks "Switch to /media/usb/Music?" and, on **Switch**, closes the library it has open and
opens that one.

R1.7. **Opening files.** MusiKata registers for the audio kinds of R2.2 and for `.m3u` and `.m3u8`
as a choice in the system's **Open with**, but never makes itself the default player; that is the
user's to choose in the system's settings. A song opened with it (from the system, or as
`musikata FILE …`) plays at once, as double-clicking it in the library does (R7.1): the queue
becomes the rest of its album from that song on, or, for files from outside the music root, the
other files opened with it. A playlist opened with it plays from its first song.

R1.7.1. **Files from outside the root** play where they are and are not added to the library
(`N07-now-playing-not-in-library`). Their tags are read and shown as usual; Now Playing marks
such a song "Not in your library" and offers **Add to library…**, which is R12.5's Copy or Move.
Their plays aren't counted (R7.9), as play counts belong to a root; a rating set on one is written
into its file (R10.3).

R1.8. **Closing.** Closing the main window quits MusiKata, the mini player (R15) with it; there is
no tray icon. The queue, the position in the current song and the window's layout are saved and
restored at the next start, paused.

R1.9. **Updates.** MusiKata looks for a new release only when asked: ⋮ › **Check for updates…**
(R6.6), or once a week with **Check for updates weekly** on (R13.10, off by default). The check asks
GitHub for MusiKata's latest release and sends nothing else (R16.1). When there is a newer one, it
shows the release's notes and **Update**, which downloads it, checks its SHA-256 and, where it has
one, its signature (`build-and-release.md`), and then: the AppImage replaces itself and restarts; on
Windows the new installer runs; on macOS the new `.dmg` opens. Nothing is installed without the user
pressing **Update**.

R1.10. **Language.** MusiKata's own words are English, and every one goes through Qt's
translations (`qsTr`), so a translation is a file added, not a change to the code. Dates, times,
numbers and sizes follow the system's locale. Tags in any script are shown, sorted and searched
(R2.7), right-to-left text included.

R1.11. **Size and speed,** on the reference machine (four cores, 8 GB of memory, an SSD, at most
five years old):

| What | Target |
|---|---|
| Library size | 50,000 songs, with every view scrolling at 60 frames a second |
| Start, library unchanged | A usable window within 2 seconds; the scan of R2.3 goes on behind it |
| First scan | At least 100 songs a second from a local SSD |
| Search | Results within 100 ms of each key pressed (R2.7) |
| Memory | Under 500 MB with 50,000 songs, thumbnails included |

Tier 2 measures each on the demo library built at 50,000 songs (`testing.md`).
