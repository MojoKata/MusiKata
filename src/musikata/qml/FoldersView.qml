import QtQuick
import QtQuick.Controls.Basic
import "."

// Folders (R2.9, L04-folders to L08-folder-songs): the open folder's subfolders, then its files,
// from the one FolderModel every mode binds to (A2.7), in the mode the header's switch chose
// (R2.9.4): Large and Small images (covers, names and counts under them, the files after as a list
// under "4 songs in this folder"), Cards, and List (one table, a folder's row two rows tall). A
// folder of songs heads its files with a strip like an album's page (R2.9.7). One list draws every
// mode: in the image modes a folder's row is a cell of the grid, the first of each line holding the
// line's height and the rest drawn beside it.
//
// A click selects (Ctrl/⌘-click adds, Shift-click takes the range), as does a cover's checkbox and
// List's, and a drag box in the image modes (R2.9.6); a double click or Enter opens a folder or
// plays a file and the files after it (R7.1); a right click on a row of files or of List opens its
// menu, Play next, Add to queue (R7.2), Edit tags, Album art, Organize files… (R12.2) and Show in
// file manager (R2.9.6); Alt+↑ (⌘↑ on macOS) or Backspace
// goes up, Alt+← or the mouse's back button back. Edit tags, on the selection bar, in the menu and on
// a folder of songs' strip, opens the panel on the songs selected or beneath the folders (R2.9.6,
// R4.2); Infer from path, in the same places, its dialog on the same songs (R3.1); Album art opens
// its dialog (R5.2) on their album, offered on the bar and in the menu when they are one album, and
// on the strip on the album most of the folder's songs are on. Each folder shows the worst
// path-match state beneath it (R2.9.5: a dot on its cover, a chip on its card and its List row),
// each file its path-match chip (R3.9), and a folder of songs whose files differ from their path
// says how in a line under its strip (R2.9.7).
// A folder or file dragged, in every mode, carries its songs, or the selection's when it is in
// it, and gives a file manager the folders and files themselves (R2.9.6, R6.10).
Item {
    id: view
    required property var library
    required property var player
    property var playlists: null  // Add to playlist and New playlist from selection (R8)
    property var edit: null
    property var art: null      // the Album art dialog's bridge (R5.2)
    property var infer: null    // Infer from path's dialog (R3)
    property var ratings: null  // a star clicked in a row rates its song (R10.2)
    property var dragging: null  // folders and files dragged: the selection when the row is in it
    property var organize: null  // Organize files' dialog (R12.2)
    property var tints: null    // Cards tinted with their covers' colours (R6.2.2)
    property var attention: null  // Show in file manager (R2.9.6), as Needs attention's Show in folder
    property var removing: null  // Move to trash and Ignore this folder (R2.11, R2.11.1); Delete's
    readonly property var folders: library.folders
    readonly property var rowsModel: folders.model
    readonly property string mode: folders.mode
    readonly property bool songsMode: folders.songsMode
    readonly property bool gridMode: !songsMode && mode !== "list"
    readonly property bool listMode: !songsMode && mode === "list"
    property int current: -1            // the row Enter acts on: the last clicked
    focus: true

    function tapped(index, modifiers) {
        view.forceActiveFocus()
        view.current = index
        view.rowsModel.click(index, (modifiers & Qt.ControlModifier) !== 0, (modifiers & Qt.ShiftModifier) !== 0)
    }
    function step(by) {
        const n = Math.max(0, Math.min(rows.count - 1, (view.current < 0 ? 0 : view.current + by)))
        view.current = n
        view.rowsModel.click(n, false, false)
        rows.positionViewAtIndex(n, ListView.Contain)
    }

    // not behind a modal dialog (Main's `modal`)
    readonly property bool behindModal: view.Window.window !== null && view.Window.window.modal === true
    Shortcut { sequences: view.folders.upKeys; enabled: !view.behindModal; onActivated: view.folders.up() }
    Shortcut { sequence: "Alt+Left"; enabled: !view.behindModal; onActivated: view.folders.back() }
    TapHandler { acceptedButtons: Qt.BackButton; onTapped: view.folders.back() }
    Keys.onReturnPressed: if (view.current >= 0) view.folders.activate(view.current)
    Keys.onEnterPressed: if (view.current >= 0) view.folders.activate(view.current)
    Keys.onDeletePressed: if (view.removing !== null) view.removing.askSelection(view.rowsModel)
    // ← and → move the selection here, rather than seek (R6.9); Alt+← stays Back
    Keys.onShortcutOverride: (event) => event.accepted = (event.key === Qt.Key_Left || event.key === Qt.Key_Right) && !(event.modifiers & Qt.AltModifier)
    Keys.onLeftPressed: view.step(-1)
    Keys.onRightPressed: view.step(1)
    Keys.onUpPressed: view.step(view.gridMode && view.current < view.folders.folderRows ? -rows.columns : -1)
    Keys.onDownPressed: view.step(view.gridMode && view.current + rows.columns < view.folders.folderRows ? rows.columns : 1)
    Connections {
        target: view.folders
        function onOpened() { view.current = -1 }
    }

    // ---------- a folder of songs' strip (R2.9.7, L08) ----------

    Item {
        id: strip
        objectName: "strip"
        visible: view.songsMode
        x: 28
        y: 8
        width: view.width - 56
        height: visible ? 156 + (pathLine.visible ? pathLine.height + 12 : 0) : 0

        Cover {
            id: stripArt
            width: 140
            height: 140
            radius: 12
            sourceSide: 256
            source: view.folders.cover
            emptyText: qsTr("No art")
            emptyIcon: "folder"
        }
        Item {
            x: stripArt.width + 28
            width: strip.width - x
            height: stripArt.height
            Text {
                id: kicker
                y: 6
                width: parent.width
                elide: Text.ElideRight
                text: view.folders.kicker
                color: Theme.cell
                font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.6; capitalization: Font.AllUppercase }
            }
            Text {
                id: stripName
                anchors.top: kicker.bottom
                anchors.topMargin: 2
                width: parent.width
                elide: Text.ElideRight
                text: view.folders.title
                color: Theme.text
                font { family: Theme.sans; pixelSize: 32; weight: Font.Bold }
            }
            Text {
                id: artLine
                anchors.top: stripName.bottom
                width: parent.width
                elide: Text.ElideRight
                text: view.folders.artLine
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13 }
            }
            Row {
                anchors.top: artLine.bottom
                anchors.topMargin: 14
                spacing: 10
                Repeater {
                    model: view.folders.stripButtons
                    Btn {
                        required property var modelData
                        objectName: modelData.action === "edit" ? "editFolder"
                                    : modelData.action === "art" ? "folderArt"
                                    : modelData.action === "infer" ? "inferFolder" : ""
                        label: modelData.label
                        icon: modelData.icon
                        later: modelData.later
                        primary: modelData.primary === true
                        onClicked: {
                            if (modelData.action === "edit")
                                view.edit.editFolder(view.folders)
                            else if (modelData.action === "art")
                                view.art.openFolder(view.folders.path, view.folders.title)
                            else if (modelData.action === "infer" && view.infer !== null)
                                view.infer.openFolder(view.folders.path)
                        }
                    }
                }
                Repeater {
                    model: view.folders.chips
                    Chip {
                        required property var modelData
                        anchors.verticalCenter: parent.verticalCenter
                        label: modelData.text
                        tone: modelData.tone
                    }
                }
            }
        }
        Rectangle {  // how its files differ from their path (R2.9.7, L08)
            id: pathLine
            objectName: "pathLine"
            y: stripArt.height + 12
            width: strip.width
            height: lineText.implicitHeight + 24
            radius: 10
            visible: view.folders.pathLine !== ""
            color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.12)
            Accessible.role: Accessible.StaticText
            Accessible.name: lineText.text
            Icon { x: 14; y: 12; name: "attention"; size: 16; color: Theme.warn }
            Text {
                id: lineText
                x: 42
                y: 12
                width: parent.width - 56
                wrapMode: Text.WordWrap
                text: view.folders.pathLine
                color: Theme.warn
                font { family: Theme.sans; pixelSize: 14 }
            }
        }
    }

    // ---------- the columns' headers ----------

    // [x, width] of each column of a table `w` wide, from fixed widths and shares of what is left
    function columnsOf(w, fixed, share, gap) {
        const free = Math.max(0, w - 24 - fixed.reduce((a, b) => a + b, 0) - gap * (fixed.length - 1))
        let x = 12, out = []
        for (let i = 0; i < fixed.length; i++) {
            const cw = fixed[i] + share[i] * free
            out.push([x, cw])
            x += cw + 16
        }
        return out
    }
    // List: check, name, artist, album, year, rating, time
    readonly property var listColumns: columnsOf(rows.width, [22, 0, 0, 0, 44, 70, 52], [0, 0.46, 0.27, 0.27, 0, 0, 0], 16)
    // the files in the image modes: file, title, album (or where), rating, time, from path
    readonly property var fileColumns: columnsOf(rows.width, [0, 0, 0, 70, 44, 170], [0.42, 0.30, 0.28, 0, 0, 0], 16)
    // a folder of songs: file, title, artist, genre, year, from path
    readonly property var songColumns: columnsOf(rows.width, [0, 0, 0, 0, 44, 170], [0.32, 0.28, 0.22, 0.18, 0, 0], 16)

    component Heads: Item {
        id: heads
        property var columns: []
        property var labels: []             // [label, column, at right, indent]
        height: 33
        Repeater {
            model: heads.labels
            Text {
                required property var modelData
                readonly property var column: heads.columns[modelData[1]] || [0, 0]
                x: column[0] + (modelData[3] || 0)
                width: column[1] - (modelData[3] || 0)
                height: 32
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: modelData[2] ? Text.AlignRight : Text.AlignLeft
                elide: Text.ElideRight
                text: modelData[0]
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4 }
            }
        }
        Rectangle { y: 32; width: heads.width; height: 1; color: Theme.border }
    }

    Item {  // List's header, with the checkbox that selects every row or none
        id: listHead
        visible: view.listMode || view.songsMode
        x: rows.x
        y: view.songsMode ? strip.y + strip.height + 8 : 0
        width: rows.width
        height: visible ? 34 : 0
        Check {
            objectName: "selectAll"
            visible: view.listMode
            x: view.listColumns[0][0]
            y: 6
            mark: view.folders.selectionState
            onToggled: view.folders.selectionState === "none" ? view.rowsModel.selectAll() : view.rowsModel.clearSelection()
        }
        Heads {
            width: parent.width
            columns: view.listMode ? view.listColumns : view.songColumns
            labels: view.listMode
                ? [[qsTr("NAME"), 1], [qsTr("ARTIST"), 2], [view.folders.thirdLabel === "FOLDER" ? qsTr("FOLDER") : qsTr("ALBUM"), 3],
                   [qsTr("YEAR"), 4], [qsTr("RATING"), 5], [qsTr("TIME"), 6, true]]
                : [[qsTr("FILE"), 0, false, 26], [qsTr("TITLE"), 1], [qsTr("ARTIST"), 2], [qsTr("GENRE"), 3], [qsTr("YEAR"), 4],
                   [qsTr("FROM PATH"), 5]]
        }
    }

    // ---------- the rows, in every mode ----------

    ListView {
        id: rows
        objectName: "folderRows"
        readonly property bool large: view.mode === "large"
        readonly property bool cards: view.mode === "cards"
        // the grid of the image modes: columns, each cell's size, and the tile in it
        readonly property int columns: cards ? Math.max(1, Math.floor((width + 16) / (300 + 16)))
                                     : large ? Math.max(1, Math.floor((width + 24) / (220 + 24)))
                                     : Math.max(2, Math.floor((width + 18) / (150 + 18)))
        readonly property real cellWidth: cards ? (width + 16) / columns : Math.floor((width - 14) / columns)
        readonly property real tile: cards ? cellWidth - 16 : cellWidth - (large ? 24 : 18)
        readonly property real cellHeight: cards ? 96 + 16 : tile + (large ? 60 : 56) + 22
        readonly property real gridTop: 8
        x: view.gridMode ? 28 : 20
        y: view.songsMode || view.listMode ? listHead.y + listHead.height : 0
        width: view.width - x - (rows.cards && view.gridMode ? 24 : view.gridMode ? 10 : 16)
        height: view.height - y
        clip: true
        interactive: false          // a drag draws the selection box; the wheel and the bar scroll
        boundsBehavior: Flickable.StopAtBounds
        topMargin: view.gridMode ? gridTop : 0
        bottomMargin: 80            // room above the selection bar
        model: view.rowsModel
        ScrollBar.vertical: ScrollBar { }
        WheelHandler {
            onWheel: (event) => {
                const most = Math.max(rows.originY - rows.topMargin, rows.contentHeight + rows.originY + rows.bottomMargin - rows.height)
                rows.contentY = Math.max(rows.originY - rows.topMargin, Math.min(most, rows.contentY - event.angleDelta.y))
            }
        }
        TapHandler { onTapped: view.rowsModel.clearSelection() }

        delegate: Item {
            id: cell
            required property int index
            required property string kind
            required property string name
            required property string line
            required property string cover
            required property string title
            required property string numbered
            required property string artist
            required property string album
            required property string genre
            required property string year
            required property int rating
            required property string time
            required property string third
            required property var odd
            required property bool playing
            required property bool selected
            required property string dot
            required property var pathChip
            readonly property bool isFolder: kind === "folder"
            readonly property bool inGrid: view.gridMode && isFolder
            readonly property int column: inGrid ? index % rows.columns : 0
            // the first file in the image modes carries the heading over the files
            readonly property real headed: view.gridMode && !isFolder && index === view.folders.folderRows ? 96 : 0
            width: rows.width
            height: inGrid ? (column === 0 ? rows.cellHeight : 0)
                  : headed + (view.listMode && isFolder ? 66 : (view.songsMode ? 42 : 38))
            z: inGrid ? 1 : 0

            Item {
                visible: cell.headed > 0
                width: rows.width
                height: cell.headed
                Text {
                    objectName: "filesTitle"
                    y: 18
                    width: parent.width
                    elide: Text.ElideRight
                    text: view.folders.filesTitle
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 17; weight: Font.Bold }
                }
                Heads {
                    y: 56
                    width: parent.width
                    columns: view.fileColumns
                    labels: [[qsTr("FILE"), 0, false, 26], [qsTr("TITLE"), 1],
                             [view.folders.thirdLabel === "FOLDER" ? qsTr("FOLDER") : qsTr("ALBUM"), 2],
                             [qsTr("RATING"), 3], [qsTr("TIME"), 4, true], [qsTr("FROM PATH"), 5]]
                }
            }
            Loader {
                x: cell.inGrid ? cell.column * rows.cellWidth + (rows.cards ? 0 : 4) : 0
                y: cell.inGrid && cell.column > 0 ? -rows.cellHeight : cell.headed
                width: cell.inGrid ? rows.tile : rows.width
                sourceComponent: view.listMode ? listRow : (cell.inGrid ? (rows.cards ? card : tile) : fileRow)
            }
            Component {
                id: tile
                FolderTile {
                    large: rows.large
                    dot: cell.dot
                    name: cell.name
                    line: cell.line
                    cover: cell.cover
                    playing: cell.playing
                    selected: cell.selected
                    onTapped: (modifiers) => view.tapped(cell.index, modifiers)
                    onActivated: view.folders.activate(cell.index)
                    onToggled: view.rowsModel.toggle(cell.index)
                    onPlay: view.folders.playRow(cell.index)
                    DragSource { dragging: view.dragging; onCarry: view.dragging.carry(view.rowsModel, cell.index) }
                }
            }
            Component {
                id: card
                FolderCard {
                    tints: view.tints
                    pathChip: cell.pathChip
                    name: cell.name
                    line: cell.line
                    cover: cell.cover
                    playing: cell.playing
                    selected: cell.selected
                    onTapped: (modifiers) => view.tapped(cell.index, modifiers)
                    onActivated: view.folders.activate(cell.index)
                    onToggled: view.rowsModel.toggle(cell.index)
                    DragSource { dragging: view.dragging; onCarry: view.dragging.carry(view.rowsModel, cell.index) }
                }
            }
            Component {
                id: listRow
                FolderListRow {
                    objectName: "folderListRow"
                    columns: view.listColumns
                    isFolder: cell.isFolder
                    pathChip: cell.pathChip
                    name: cell.name
                    line: cell.line
                    cover: cell.cover
                    artist: cell.artist
                    album: view.folders.thirdLabel === "FOLDER" ? cell.third : cell.album
                    year: cell.year
                    rating: cell.rating
                    time: cell.time
                    playing: cell.playing
                    selected: cell.selected
                    onTapped: (modifiers) => view.tapped(cell.index, modifiers)
                    onActivated: view.folders.activate(cell.index)
                    onToggled: view.rowsModel.toggle(cell.index)
                    onMenu: songMenu.openFor(view.rowsModel, cell.index)
                    onRated: (star) => { if (view.ratings) view.ratings.rateRow(view.rowsModel, cell.index, star) }
                    DragSource { dragging: view.dragging; onCarry: view.dragging.carry(view.rowsModel, cell.index) }
                }
            }
            Component {
                id: fileRow
                FileRow {
                    columns: view.songsMode ? view.songColumns : view.fileColumns
                    songs: view.songsMode
                    name: cell.name
                    title: cell.title
                    numbered: cell.numbered
                    artist: cell.artist
                    genre: cell.genre
                    year: cell.year
                    third: cell.third
                    rating: cell.rating
                    time: cell.time
                    odd: cell.odd
                    pathChip: cell.pathChip
                    playing: cell.playing
                    selected: cell.selected
                    onTapped: (modifiers) => view.tapped(cell.index, modifiers)
                    onActivated: view.folders.activate(cell.index)
                    onMenu: songMenu.openFor(view.rowsModel, cell.index)
                    DragSource { dragging: view.dragging; onCarry: view.dragging.carry(view.rowsModel, cell.index) }
                }
            }
        }

        // the drag box (R2.9.6): the rows it covers, worked out from the grid's geometry
        DragHandler {
            id: band
            target: null
            enabled: view.gridMode
            property real startY: 0
            onActiveChanged: {
                if (active) {
                    startY = centroid.pressPosition.y + rows.contentY
                    view.forceActiveFocus()
                }
            }
            onCentroidChanged: if (active) view.rowsModel.selectRows(view.covered(), (centroid.modifiers & Qt.ControlModifier) !== 0)
        }
    }
    Rectangle {  // the drag box itself
        visible: band.active
        readonly property real x0: Math.min(band.centroid.pressPosition.x, band.centroid.position.x)
        readonly property real y0: Math.min(band.startY - rows.contentY, band.centroid.position.y)
        x: rows.x + x0
        y: rows.y + y0
        width: Math.abs(band.centroid.position.x - band.centroid.pressPosition.x)
        height: Math.abs(band.centroid.position.y + rows.contentY - band.startY)
        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12)
        border.color: Theme.accent
    }
    // the rows under the drag box, in the content's coordinates
    function covered() {
        const left = Math.min(band.centroid.pressPosition.x, band.centroid.position.x)
        const right = Math.max(band.centroid.pressPosition.x, band.centroid.position.x)
        const y = band.centroid.position.y + rows.contentY
        const top = Math.min(band.startY, y), bottom = Math.max(band.startY, y)
        const out = [], n = view.folders.folderRows
        for (let i = 0; i < n; i++) {
            const cx = (i % rows.columns) * rows.cellWidth, cy = Math.floor(i / rows.columns) * rows.cellHeight
            if (cx < right && cx + rows.tile > left && cy < bottom && cy + rows.cellHeight - 22 > top)
                out.push(i)
        }
        const filesTop = Math.ceil(n / rows.columns) * rows.cellHeight + (rows.count > n ? 96 : 0)
        for (let j = n; j < rows.count; j++) {
            const fy = filesTop + (j - n) * 38
            if (fy < bottom && fy + 38 > top)
                out.push(j)
        }
        return out
    }

    SongMenu { id: songMenu; player: view.player; edit: view.edit; art: view.art; infer: view.infer; organize: view.organize; reveal: view.attention; removing: view.removing; playlists: view.playlists; playlistList: view.library.playlists }

    SelectionBar {
        objectName: "selectionBar"
        text: view.folders.selectionText
        laterActions: view.folders.laterActions
        playlists: view.playlists
        playlistList: view.library.playlists
        songs: view.rowsModel
        editing: view.edit !== null && view.edit.opened
        onAct: (action) => {
            if (action === "edit")
                view.edit.editSelection(view.rowsModel)
            else if (action === "art")
                view.art.openAlbum(view.folders.selectedAlbum)
            else if (action === "infer" && view.infer !== null)
                view.infer.openSelection(view.rowsModel)
            else if (action === "organize" && view.organize !== null)
                view.organize.openSelection(view.rowsModel)
        }
        playNote: view.library.playNote
        onPlay: view.folders.playSelection()
        onClear: view.rowsModel.clearSelection()
        visible: view.folders.selectionCount > 0
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 20
    }

    Text {  // the library empty, or a search that found nothing (R2.7)
        objectName: "empty"
        anchors.horizontalCenter: parent.horizontalCenter
        y: 80
        width: Math.min(implicitWidth, view.width - 56)
        elide: Text.ElideRight
        visible: text !== ""
        text: view.library.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 14 }
    }
}
