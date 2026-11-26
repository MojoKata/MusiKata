import QtQuick
import "."

// An artist in the Artists grid (R2.6): a mosaic of their covers, their name, and their albums and
// songs. A click opens their page.
Item {
    id: tile
    signal open()
    required property string name
    required property string line
    required property var tiles
    property alias loading: art.loading
    height: width + 56
    Accessible.role: Accessible.Button
    Accessible.name: tile.name + ", " + tile.line

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: tile.open() }

    Mosaic {
        id: art
        width: tile.width
        height: tile.width
        tiles: tile.tiles
    }
    Text {
        y: tile.width + 10
        width: tile.width
        elide: Text.ElideRight
        text: tile.name
        color: hover.hovered ? Theme.accentHi : Theme.text
        font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
    }
    Text {
        y: tile.width + 31
        width: tile.width
        elide: Text.ElideRight
        text: tile.line
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 12 }
    }
}
