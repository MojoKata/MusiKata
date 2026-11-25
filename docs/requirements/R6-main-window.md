# R6. Main window and look

R6.1. **Layout.** From left to right: the sidebar (R6.3), the current view with its header
(R6.4), and, when open, the Edit tags panel (R4.2) docked on the right. The now-playing bar (R6.5)
runs the full width along the bottom.

R6.2. **The look.** The goal is a sleek, simple, modern interface: generous spacing, soft
rounded cards, the album art as the main colour, clear typography and few lines. Dark is the
design target and the default; light and "Match system" are in ⋮ › Theme. Both themes use the
design tokens in `Theme.qml`, whose dark values are:

| Token | Dark | Use |
|---|---|---|
| `bg` | `#0e1014` | Window |
| `side` | `#12151b` | Sidebar, panels |
| `surface` / `raised` | `#171a21` / `#1e222b` | Cards, menus |
| `border` / `borderStrong` | `#232731` / `#323744` | Lines |
| `text` / `muted` / `faint` | `#eceef4` / `#99a0b2` / `#5f6577` | Text |
| `accent` / `accentSoft` | `#a78bfa` / `#2b2450` | Selection, primary buttons |
| `cyan`, `pink` | `#22d3ee`, `#f472b6` | The visualizations' gradient (R11) |
| `ok`, `warn`, `err` | `#34d399`, `#fbbf24`, `#fb7185` | States |
| `star` | `#fbbf24` | Ratings |
| `progress` | `#4ade80` | The progress line on Now Playing's cover (R11.4.3) |

R6.2.1. **Design point.** The window is designed for a 1920 × 1080 screen with MusiKata maximized
on it; the mockups are drawn at 1280 × 800, the smallest size the layout is checked at.

R6.2.2. Large views (the album page, Now Playing) tint their background with the cover's
dominant colour.

R6.3. **Sidebar.** The app's icon and name; **Library**: Albums, Artists, Songs, Genres, Folders
and Needs attention with its count (R2.8); **Playlists** with **+** (R8.3) and each playlist
with its count; the music root's card at the bottom (R2.1.1). The sidebar can be narrowed to its
icons.

R6.4. **Header.** The view's title and count, the search box (R2.7), the view-mode switch where
the view has more than one mode (grid and list in Albums; four in Folders, R2.9.4), the sort, and
the ⋮ menu. In Folders the title is the open folder's path (R2.9.1). When the header is too narrow
for everything (the Edit tags panel open, a small window), the search box becomes its icon, which
opens it over the title. On Linux and Windows the window draws its own header and
the window buttons (minimize, maximize, close) sit at its right end; on macOS the system's buttons
sit at the left of the sidebar.

R6.5. **Now-playing bar.** Left: the cover, title, artist and album, and the song's rating, which
can be set there (R10.2). Centre: shuffle, previous, play/pause, next and repeat, and under them
the song's waveform as its seek bar (R11.2) with the time played and the length. Right: the queue
(R7.2), the volume, the pop-out button that opens the mini player in a window of its own (R15),
and at the far end the **Now Playing** button (R11.4): it opens Now Playing over the whole window
above the bar, is highlighted while it is open, and closes it again.

R6.6. **The ⋮ menu,** in this order: **Rescan library** (R2.3), **Change history** (R4.9), **Mini
player** (R15), **Settings…** (R13), the theme (Match system, Dark, Light), **Show app log** (R14),
**About MusiKata**, **Quit MusiKata** (Ctrl+Q / ⌘Q).

R6.7. **Messages.** Finished actions and errors are shown in a short-lived message at the bottom of
the view, above the now-playing bar; a message about a save carries **Undo** (R4.9).

R6.8. **Confirmations.** Actions that move or remove files, or rewrite more than one file without
a preview, ask first, naming what they do: "Remove 3 songs from Road Trip?" asks nothing (the
files stay), "Move 2 files to the trash?" does.

R6.9. **Keyboard.** Space plays and pauses; Ctrl+→ / Ctrl+← (⌘ on macOS) next and previous; ← / →
seek 5 seconds; `/` search; Ctrl+E Edit tags; Ctrl+0 to Ctrl+5 rate the selection; Ctrl+Z undo;
Ctrl+, Settings; Enter plays the selection (in Folders, opens a folder); Alt+↑ / ⌘↑ and Backspace
go up a folder (R2.9.1); Ctrl+Shift+M / ⇧⌘M the mini player (R15.1); Delete removes from a
playlist. Every action is reachable by keyboard, and
focus is always visible.

R6.10. **Drag and drop.** Songs, albums, artists, genres and folders can be dragged from any
view:

- onto a playlist in the sidebar, to add them (R8.5);
- within a playlist, to reorder (R8.5);
- onto the queue, to play them next;
- out of MusiKata, onto a file manager or another app, as the files themselves.

Files and folders dropped onto MusiKata from outside are added to the library (R12.5), and an
image dropped onto a cover sets it (R5.4). While dragging, the drag shows the cover and "3 songs",
the target is highlighted and named ("Add to Evening Focus"), and an insertion line shows where a
reorder lands (`P01-playlist-drag`).
