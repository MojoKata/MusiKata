# R5. Album art

R5.1. **Where art is found.** For each album MusiKata looks, in this order, at:

1. The pictures embedded in its songs (ID3 `APIC`, FLAC and Vorbis `METADATA_BLOCK_PICTURE`, MP4
   `covr`), the front cover first.
2. Images in the album's folder named `cover`, `folder`, `front` or `album`, any case, `.jpg`,
   `.jpeg`, `.png` or `.webp`.
3. Any other image in the album's folder, largest first.
4. Online, only when the user asks (R16.4).

The album's cover in the views is the first one found. Thumbnails are made once and kept in the
cache folder (R1.5).

R5.2. **The Album art dialog** (`T02-album-art`) opens from an album's page, the Edit tags panel's
cover, and Needs attention. It shows the current cover large, with its size, kind and file size
and where it is ("Embedded in 10 of 10"), and beside it every candidate found (R5.1), each with
a thumbnail, where it is, its size and a note ("same as embedded", "lower resolution", "named as
a back cover"). One is chosen with its radio button.

R5.2.1. An image can also be dropped onto the dialog, pasted (Ctrl+V / ⌘V), chosen with
**Choose file…**, or found with **Find online…** (R16.4).

R5.3. **What saving does,** each a checkbox:

- **Embed in every song of the album** (on): the chosen image becomes each song's front cover.
- **Save as cover.jpg in the folder** (on): written beside the songs, replacing an older
  `cover.jpg` (which goes to the trash, Principle 5).
- **Shrink to 1200 × 1200 before embedding** (on): a larger image is scaled down and saved as
  JPEG at quality 90 before it is embedded; `cover.jpg` keeps the full size. The size is a
  setting (R13).
- **Remove other embedded images** (off): drops back covers, artist photos and the rest.

The footer says what will change ("Embeds the cover in 2 songs and writes cover.jpg"), or "No
change" when the chosen cover is already everywhere. Saving is undoable (R4.9).

R5.4. **Dropping art anywhere.** An image dropped on an album's cover in any view opens the Album
art dialog with that image chosen.

R5.5. **Extracting.** On an album's page, ⋯ › **Save cover to folder** writes the embedded cover
as `cover.jpg` without opening the dialog.

R5.6. **Needs attention** (R2.8) lists albums with no cover, with a cover under 500 × 500, and
with songs whose embedded covers differ.

R5.7. **No cover.** An album without art shows a dashed tile with an image icon and "No album art"
(`L01-albums`), never a stock picture that looks like a cover.

R5.8. **Folder covers and mosaics.** In Folders (R2.9.3) every folder shows a picture:

1. **Its own cover.** An image in the folder found as R5.1's steps 2 and 3 find one, or else the
   front cover embedded in its songs when they share one. A folder of an album shows that
   album's cover.
2. **A mosaic.** A folder with no cover of its own, and folders beneath it, shows a mosaic of up
   to four of their pictures, one per subfolder, taken from the subfolders with the most songs
   and shown in name order. A subfolder that is itself a mosaic gives its first cover, so a
   mosaic never holds a smaller mosaic and stays readable at any depth. A folder of loose songs
   (singles, no subfolders) whose embedded covers differ shows a mosaic of up to four of them.

   | Pictures | Mosaic |
   |---|---|
   | 1 | That picture, whole |
   | 2 | Two halves, side by side |
   | 3 | A half on the left, two quarters on the right |
   | 4 | A 2 × 2 grid |

   The pieces are centre crops of the covers with a 2 px gap between them, under the same
   rounded corner as a single cover.
3. **None.** A folder with no picture anywhere beneath it shows the dashed tile of R5.7, with a
   folder icon and "No art".

Mosaics change as the covers beneath them change, and are cached like thumbnails (R5.1).
