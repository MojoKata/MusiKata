# R1. Platform and architecture

R1.1. MusiKata runs on what its tests cover (`docs/process/testing.md`):

- Linux x86_64: Linux Mint 22.3, LMDE 7, Ubuntu 24.04 LTS and Ubuntu 26.04 LTS. A later Mint or
  LMDE release joins once the tests move to it.
- Windows 10 22H2 and Windows 11, x64 (Q7).
- macOS 14 and newer on Apple silicon (Q1).

R1.2. Everything is written in Python, and MusiKata runs on the Python its release carries: the
AppImage, the Windows installer and the macOS app each carry one, of one version for all three,
with one PySide6, both set in `packaging/versions.env`. Running from source is for development
only, never a way to install MusiKata, and uses that same version.

R1.2.1. The GUI uses PySide6 (Qt 6 with QML) and the `Basic` Qt Quick Controls style; its look is
R6.2. Playback uses Qt Multimedia, with the FFmpeg back end Qt carries on every platform (A4).

R1.2.2. Tags are read and written with Mutagen (A3), and the visualizations' arithmetic uses
NumPy (A5). Nothing else is added without a reason written in the architecture.

R1.3. MusiKata is one desktop-user process with no service and no administrator rights. It reads
and writes only the music root (R2.1), its own data folders (R1.5) and the files the user hands
it.

R1.4. Distribution:

- Linux: an AppImage, x86_64, that installs itself into the app menu on first start and, when
  asked, updates itself (R1.9).
- Windows: an Inno Setup installer, for the current user by default, without a UAC prompt.
- macOS: a signed and notarized `.dmg` holding `MusiKata.app`.

R1.5. **Local data.** The library index, the change history (R4.9), the play counts and the
caches (cover thumbnails, waveforms) are kept in a SQLite database, `musikata.db`, and a cache
folder. The database schema is versioned and migrated when MusiKata starts. The App log (R14) is
kept in text files.

| | Database | Caches | App log |
|---|---|---|---|
| Linux | `~/.local/share/musikata/` (`$XDG_DATA_HOME`) | `~/.cache/musikata/` (`$XDG_CACHE_HOME`) | `~/.local/state/musikata/` (`$XDG_STATE_HOME`) |
| Windows | `%LOCALAPPDATA%\MusiKata\` | `%LOCALAPPDATA%\MusiKata\Cache\` | `%LOCALAPPDATA%\MusiKata\Logs\` |
| macOS | `~/Library/Application Support/MusiKata/` | `~/Library/Caches/MusiKata/` | `~/Library/Logs/MusiKata/` |

R1.5.1. Deleting the database and the caches loses only play counts, the change history and
time; the next start scans the music root again and finds every tag, cover, rating and playlist
in the files (Principle 1).

R1.6. **One MusiKata at a time.** Starting MusiKata while it is already running (from the app
menu, or by opening a music file or playlist with it) hands its arguments to the running
MusiKata over a local socket, one per user and data folder, and exits. The running MusiKata
shows its window and plays or opens what it was handed.

R1.7. **Opening files.** MusiKata registers for the audio kinds of R2.2 and for `.m3u` and `.m3u8`,
but never makes itself the default player on its own. A file opened from outside the music root
plays without being added to the library.

R1.8. **Closing.** Closing the main window quits MusiKata, the mini player (R15) with it; there is
no tray icon. The queue, the position in the current song and the window's layout are saved and
restored at the next start, paused.

R1.9. **Updates.** MusiKata looks for a new release only when asked: ⋮ › **Check for updates…**
(R6.6), or once a week with **Check for updates weekly** on (R13.10, off by default). The check
asks GitHub for MusiKata's latest release and sends nothing else (R16.1). When there is a newer
one, it shows the release's notes and **Update**, which downloads it, checks its SHA-256 and
signature (`build-and-release.md`), and then: the AppImage replaces itself and restarts; on
Windows the new installer runs; on macOS the new `.dmg` opens. Nothing is installed without the
user pressing **Update**.

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
