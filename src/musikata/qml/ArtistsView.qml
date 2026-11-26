import QtQuick
import QtQuick.Controls.Basic
import "."

// Artists (R2.6): every artist by their sort name (R2.13), each with a mosaic of their covers,
// paged from the index as they scroll (A1.5).
Item {
    id: view
    required property var library

    ViewHeader {
        id: header
        width: view.width
        title: qsTr("Artists")
        count: view.library.artistCountText
    }

    GridView {
        id: grid
        objectName: "artists"
        readonly property int columns: Math.max(2, Math.floor((width + 18) / (150 + 18)))
        x: 28
        y: header.height + 8
        width: view.width - 28 - 10
        height: view.height - y
        cellWidth: Math.floor((width - 14) / columns)
        cellHeight: (cellWidth - 18) + 56 + 22
        clip: true
        reuseItems: true
        boundsBehavior: Flickable.StopAtBounds
        model: view.library.artists
        delegate: Item {
            id: cell
            required property int artistId
            required property string name
            required property string line
            required property var tiles
            width: grid.cellWidth
            height: grid.cellHeight
            ArtistTile {
                x: 4
                y: 4
                width: grid.cellWidth - 18
                name: cell.name
                line: cell.line
                tiles: cell.tiles
                onOpen: view.library.openArtist(cell.artistId)
            }
        }
        ScrollBar.vertical: ScrollBar { }
    }
}
