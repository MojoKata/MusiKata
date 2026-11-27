import QtQuick
import QtQuick.Controls.Basic
import "."

// A playlist's page (R8.2, P01-playlist-drag), with no header over it: a mosaic of four of its
// covers, "PLAYLIST · M3U8", its name, the line with its count, length, file and paths; Play,
// Shuffle and Export… (R8.8); then its songs (PlaylistRow), selected as the Songs list's are (R2.6),
// clicks and keys forwarded to the model: Enter plays the selection from its first song, the rest
// after it (R7.1), Delete takes the entries selected out of the playlist without asking (R8.6, R6.9),
// the right-click menu acts on the selection when the row is in it, and a missing entry's Find looks
// for its file (R8.7). The selection bar offers Play next, Remove from playlist, Add to playlist,
// Edit tags and Infer from path. Its songs are dragged (R8.5, R6.10), the selection when the row is
// in it: within it to reorder, with the insertion line where they land, onto a playlist or the
// queue, or out as their files; Ctrl+Shift+↑ / ↓ moves the songs selected (R6.9, R18.2). A file
// manager's files dropped on it are added at its end. A smart playlist's (R8.9) says "SMART
// PLAYLIST", shows its rule in words under the line and Edit rule beside Export…; its rows have no
// drag handles, nothing dropped on it is taken (the message says why), and Remove from playlist
// isn't offered.
Item {
    id: page
    required property var library
    required property var player
    property var edit: null
    property var ratings: null
    property var infer: null
    property var playlists: null
    property var dragging: null       // drag and drop (musikata.dragging): reordering, dropping
    property var smart: null          // Edit rule (musikata.smart, R8.9)
    readonly property var playlist: library.playlistPage
    readonly property var songs: playlist.songs
    focus: true

    function tapped(index, modifiers) {
        page.forceActiveFocus()
        page.songs.click(index, (modifiers & Qt.ControlModifier) !== 0, (modifiers & Qt.ShiftModifier) !== 0)
    }
    Keys.onReturnPressed: page.player.playSelection(page.songs)
    Keys.onEnterPressed: page.player.playSelection(page.songs)
    Keys.onDeletePressed: if (page.playlists) page.playlists.removeSelected(page.songs)
    Keys.onPressed: (event) => {
        // Ctrl+Shift+↑ / ↓ (⇧⌘ on macOS): the songs selected move (R6.9, R18.2)
        if (page.playlists !== null && page.playlists.pressMove(page.songs, event.key, event.modifiers)) {
            event.accepted = true
            return
        }
        const row = page.songs.press(event.key, event.modifiers, Math.max(1, Math.floor(list.height / 46)))
        event.accepted = row !== -2
        if (row >= 0)
            list.positionViewAtIndex(row, ListView.Contain)
    }

    // [x, width] of the columns: handle, #, title (with its cover), album, genre, rating, time
    readonly property var columns: {
        const w = list.width
        const free = Math.max(0, w - 12 - 16 - 8 - 24 - 16 - 16 - 16 - 16 - 90 - 16 - 48 - 12)
        const t = free * 0.42, a = free * 0.33, g = free * 0.25
        return [[12, 16], [36, 24], [76, t], [76 + t + 16, a], [76 + t + 16 + a + 16, g],
                [w - 12 - 48 - 16 - 90, 90], [w - 12 - 48, 48]]
    }

    ListView {
        id: list
        objectName: "playlistSongs"
        x: 20
        width: page.width - 36
        height: page.height
        clip: true
        reuseItems: true
        spacing: 2
        boundsBehavior: Flickable.StopAtBounds
        model: page.songs
        header: Item {
            id: head
            width: list.width
            height: Math.max(art.y + art.height, buttons.y + buttons.height) + 24 + 34

            Mosaic {
                id: art
                objectName: "playlistMosaic"
                x: 8
                y: 24
                width: 140
                height: 140
                tiles: page.playlist.tiles
                emptyIcon: "playlist"
            }
            Text {
                id: kicker
                x: art.x + art.width + 28
                y: art.y + 4
                text: page.playlist.kicker
                color: Theme.cell
                font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.6; capitalization: Font.AllUppercase }
            }
            Text {
                id: name
                objectName: "playlistTitle"
                x: kicker.x
                anchors.top: kicker.bottom
                anchors.topMargin: 4
                width: head.width - x - 12
                elide: Text.ElideRight
                text: page.playlist.name
                color: Theme.text
                font { family: Theme.sans; pixelSize: 36; weight: Font.Bold }
            }
            Text {
                id: detail
                objectName: "playlistDetail"
                x: kicker.x
                anchors.top: name.bottom
                anchors.topMargin: 2
                width: head.width - x - 12
                elide: Text.ElideMiddle
                text: page.playlist.detail
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13 }
            }
            Text {  // a smart playlist's rule in words (R8.9)
                id: rule
                objectName: "playlistRule"
                x: kicker.x
                anchors.top: detail.bottom
                anchors.topMargin: 4
                width: head.width - x - 12
                visible: text !== ""
                elide: Text.ElideRight
                text: page.playlist.rule
                color: Theme.accentHi
                font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
            }
            Row {
                id: buttons
                x: kicker.x
                anchors.top: rule.visible ? rule.bottom : detail.bottom
                anchors.topMargin: 14
                spacing: 10
                Btn {
                    objectName: "playlistPlay"
                    label: qsTr("Play")
                    icon: "play"
                    primary: true
                    minWidth: 100
                    later: page.library.playNote || (page.playlist.playable ? "" : qsTr("No song of it is in the library"))
                    onClicked: page.player.playPlaylist(page.playlist.id)
                }
                Btn {
                    objectName: "playlistShuffle"
                    label: qsTr("Shuffle")
                    icon: "shuffle"
                    later: page.library.playNote || (page.playlist.playable ? "" : qsTr("No song of it is in the library"))
                    onClicked: page.player.shufflePlaylist(page.playlist.id)
                }
                Btn {
                    objectName: "playlistExport"
                    label: qsTr("Export…")
                    icon: "file"
                    visible: page.playlists !== null
                    onClicked: page.playlists.openExport(page.playlist.id)
                }
                Btn {  // Edit rule (R8.9): its dialog, the rule's conditions, limit and order
                    objectName: "editRule"
                    label: qsTr("Edit rule")
                    icon: "wand"
                    visible: page.smart !== null && page.playlist.rule !== ""
                    later: page.playlist.ruleLater
                    onClicked: page.smart.openEdit(page.playlist.id)
                }
            }
            Repeater {
                model: [["#", 1], [qsTr("TITLE"), 2], [qsTr("ALBUM"), 3], [qsTr("GENRE"), 4], [qsTr("RATING"), 5], [qsTr("TIME"), 6]]
                Text {
                    required property var modelData
                    x: page.columns[modelData[1]][0] + (modelData[1] === 2 ? 44 : 0)
                    y: head.height - 30
                    width: page.columns[modelData[1]][1] - (modelData[1] === 2 ? 44 : 0)
                    height: 22
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: modelData[1] === 1 || modelData[1] === 6 ? Text.AlignRight : Text.AlignLeft
                    elide: Text.ElideRight
                    text: modelData[0]
                    color: Theme.faint
                    font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4 }
                }
            }
            Rectangle { y: head.height - 6; width: head.width; height: 1; color: Theme.border }
        }
        delegate: PlaylistRow {
            required property int index
            width: list.width
            columns: page.columns
            focused: page.activeFocus
            smart: page.playlist.smart
            onTapped: (modifiers) => page.tapped(index, modifiers)
            onActivated: page.player.playFrom(page.songs, index)
            onMenu: songMenu.openFor(page.songs, index)
            onRated: (star) => { if (page.ratings) page.ratings.rateRow(page.songs, index, star) }
            onFind: if (page.playlists) page.playlists.findRow(page.songs, index)
            DragSource {  // by its handle or anywhere on it: within the playlist, or elsewhere (R8.5)
                dragging: page.dragging
                onCarry: page.dragging.carry(page.songs, index)
            }
        }
        ScrollBar.vertical: ScrollBar { }
    }
    DropArea {  // its own songs dragged within it (R8.5), and a file manager's files
        id: drop
        objectName: "playlistPageDrop"
        anchors.fill: list
        enabled: page.dragging !== null
        // the row the line is above: past a row's middle, the one after it
        function rowAt(y) {
            const at = list.contentY + y
            let n = list.indexAt(20, at)
            if (n < 0)
                n = list.indexAt(20, at + list.spacing)  // between two rows: the one after
            if (n < 0)
                return at < 0 ? 0 : list.count  // over the header, or below the last row
            const item = list.itemAtIndex(n)
            return at > item.y + item.height / 2 ? n + 1 : n
        }
        onEntered: (drag) => {
            drag.accepted = page.dragging.enter("page", page.playlist.id, drag.getDataAsString(page.dragging.mime), drag.urls)
            if (drag.accepted)
                page.dragging.over(drop.rowAt(drag.y))
        }
        onPositionChanged: (drag) => page.dragging.over(drop.rowAt(drag.y))
        onExited: page.dragging.leave("page", page.playlist.id)
        onDropped: (event) => { if (page.dragging.drop("page", page.playlist.id, event.getDataAsString(page.dragging.mime), event.urls)) event.accept(Qt.CopyAction) }
    }
    Rectangle {  // the playlist outlined while a file manager's files are over it
        anchors.fill: list
        radius: 10
        color: "transparent"
        border.color: page.dragging !== null && page.dragging.refused ? Theme.err : Theme.accent
        border.width: 2
        visible: page.dragging !== null && page.dragging.target === "page:" + page.playlist.id && page.dragging.line < 0
    }
    Item {  // where a reorder lands (R8.5, P01): the insertion line, above row `line`
        objectName: "insertionLine"
        readonly property int row: page.dragging !== null ? page.dragging.line : -1
        readonly property var target: row >= 0 && list.count > 0 ? list.itemAtIndex(Math.min(row, list.count - 1)) : null
        visible: target !== null
        x: list.x
        width: list.width
        height: 8
        y: target ? list.y + target.y - list.contentY + (row >= list.count ? target.height + 1 : -1) - height / 2 : 0
        Rectangle { y: 3; width: parent.width; height: 2; radius: 1; color: Theme.accent }
        Rectangle { x: -4; width: 8; height: 8; radius: 4; color: Theme.accent }
    }
    Text {  // a playlist of no songs yet
        objectName: "playlistEmpty"
        anchors.horizontalCenter: parent.horizontalCenter
        y: 280
        width: Math.min(implicitWidth, page.width - 56)
        elide: Text.ElideRight
        visible: text !== ""
        text: page.playlist.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 14 }
    }
    SongMenu {
        id: songMenu
        player: page.player
        edit: page.edit
        infer: page.infer
        playlists: page.playlists
        playlistList: page.library.playlists
        inPlaylist: !page.playlist.smart
    }
    SelectionBar {
        objectName: "playlistSelectionBar"
        text: page.songs.selectionText
        playLabel: qsTr("Play next")
        playObjectName: "playNextSelection"
        laterActions: page.playlist.actions
        editing: page.edit !== null && page.edit.opened
        playlists: page.playlists
        playlistList: page.library.playlists
        songs: page.songs
        onAct: (action) => {
            if (action === "remove" && page.playlists !== null)
                page.playlists.removeSelected(page.songs)
            else if (action === "edit" && page.edit !== null)
                page.edit.editSelection(page.songs)
            else if (action === "infer" && page.infer !== null)
                page.infer.openSelection(page.songs)
        }
        // not while a drag is going on (P01): it would sit over the rows it drops between
        visible: page.songs.selectionCount > 0 && !(page.dragging !== null && (page.dragging.busy || page.dragging.held))
        anchors.horizontalCenter: list.horizontalCenter
        anchors.bottom: list.bottom
        anchors.bottomMargin: 20
        onPlay: page.player.playNextSelection(page.songs)
        onClear: page.songs.clearSelection()
    }
}
