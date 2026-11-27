import QtQuick
import QtQuick.Controls.Basic
import "."

// Albums (R2.6, L01-albums): the genre chips of the most common genres, and the albums as a grid
// of covers or, with the header's switch (R6.4), a list; paged from the index as they scroll (A1.5).
// An album dragged, from the grid or the list, carries its songs (R6.10, DragSource).
Item {
    id: view
    required property var library
    required property var player
    property var art: null  // Album art (R5.4): an image dropped on a cover
    property var dragging: null  // an album dragged (R6.10)
    readonly property bool listMode: view.library.albumsMode === "list"

    Flickable {  // the genre chips (R2.6)
        id: chips
        x: 28
        y: 0
        width: view.width - 28 - 24
        height: 34
        contentWidth: chipRow.width
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Row {
            id: chipRow
            spacing: 8
            Chip {
                label: qsTr("All")
                chosen: view.library.genre === ""
                onClicked: view.library.setGenre("")
            }
            Repeater {
                model: view.library.genres
                Chip {
                    required property string modelData
                    label: modelData
                    chosen: view.library.genre === modelData
                    onClicked: view.library.setGenre(modelData)
                }
            }
            Chip {
                id: more
                visible: view.library.moreGenres.length > 0
                label: view.library.moreText
                chosen: view.library.moreChosen
                onClicked: moreMenu.popup(more, 0, more.height + 4)
            }
        }
    }
    Menu {
        id: moreMenu
        Repeater {
            model: view.library.moreGenres
            MenuItem {
                required property string modelData
                text: modelData
                onTriggered: view.library.setGenre(modelData)
            }
        }
    }

    GridView {
        id: grid
        objectName: "albums"
        visible: !view.listMode
        readonly property int columns: Math.max(2, Math.floor((width + 18) / (150 + 18)))
        x: 28
        y: chips.y + chips.height + 22
        width: view.width - 28 - 10
        height: view.height - y
        cellWidth: Math.floor((width - 14) / columns)
        cellHeight: (cellWidth - 18) + 56 + 22
        clip: true
        reuseItems: true
        boundsBehavior: Flickable.StopAtBounds
        model: view.listMode ? null : view.library.albums
        delegate: Item {
            id: cell
            required property int albumId
            required property string title
            required property string line
            required property string cover
            required property bool playing
            width: grid.cellWidth
            height: grid.cellHeight
            AlbumTile {
                x: 4
                y: 4
                width: grid.cellWidth - 18
                title: cell.title
                line: cell.line
                cover: cell.cover
                playing: cell.playing
                onOpen: view.library.openAlbum(cell.albumId)
                onPlay: view.player.playAlbum(cell.albumId)
                onImageDropped: (urls) => { if (view.art) view.art.dropOnAlbum(cell.albumId, urls) }
                DragSource { dragging: view.dragging; onCarry: view.dragging.carryAlbum(cell.albumId) }
            }
        }
        ScrollBar.vertical: ScrollBar { }
    }

    Item {
        id: table
        visible: view.listMode
        x: 20
        y: chips.y + chips.height + 14
        width: view.width - 36
        height: view.height - y

        // [x, width] of each column: cover, title, artist, year, genre, songs, time
        readonly property real gap: 16
        readonly property var fixed: [36, 0, 0, 44, 0, 70, 52]
        readonly property var share: [0, 0.38, 0.34, 0, 0.28, 0, 0]
        readonly property real free: Math.max(0, width - 24 - fixed.reduce((a, b) => a + b, 0) - gap * 6)
        readonly property var columns: {
            let x = 12, out = []
            for (let i = 0; i < fixed.length; i++) {
                const w = fixed[i] + share[i] * free
                out.push([x, w])
                x += w + gap
            }
            return out
        }

        Repeater {
            model: ["", qsTr("TITLE"), qsTr("ARTIST"), qsTr("YEAR"), qsTr("GENRE"), qsTr("SONGS"), qsTr("TIME")]
            Text {
                required property int index
                required property string modelData
                x: table.columns[index][0]
                width: table.columns[index][1]
                height: 32
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: index >= 5 ? Text.AlignRight : Text.AlignLeft
                text: modelData
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4 }
            }
        }
        Rectangle { y: 32; width: table.width; height: 1; color: Theme.border }

        ListView {
            id: rows
            objectName: "albumRows"
            y: 34
            width: table.width
            height: table.height - y
            clip: true
            reuseItems: true
            boundsBehavior: Flickable.StopAtBounds
            model: view.listMode ? view.library.albums : null
            delegate: AlbumRow {
                width: rows.width
                columns: table.columns
                onOpen: view.library.openAlbum(albumId)
                onImageDropped: (urls) => { if (view.art) view.art.dropOnAlbum(albumId, urls) }
                DragSource { dragging: view.dragging; onCarry: view.dragging.carryAlbum(albumId) }
            }
            ScrollBar.vertical: ScrollBar { }
        }
    }

    Text {  // the library empty, or a search that found nothing (R2.7)
        objectName: "empty"
        anchors.horizontalCenter: parent.horizontalCenter
        y: chips.y + chips.height + 80
        width: Math.min(implicitWidth, view.width - 56)
        elide: Text.ElideRight
        visible: text !== ""
        text: view.library.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 14 }
    }
}
