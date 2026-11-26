import QtQuick
import QtQuick.Controls.Basic
import "."

// Artists (R2.6): every artist by their sort name (R2.13), each with a mosaic of their covers,
// paged from the index as they scroll (A1.5).
Item {
    id: view
    required property var library

    GridView {
        id: grid
        objectName: "artists"
        readonly property int columns: Math.max(2, Math.floor((width + 18) / (150 + 18)))
        x: 28
        y: 8
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
