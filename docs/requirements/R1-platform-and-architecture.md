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

- Linux: an AppImage, x86_64, that installs itself into the app menu on first start and updates
  itself.
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
no tray icon. The queue, the
position in the current song and the window's layout are saved and restored at the next start,
paused.
