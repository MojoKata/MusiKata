import QtQuick
import "."

// An album in Albums' list mode: its cover small, title, artist, year, genre, songs and length. A
// click opens its page.
Rectangle {
    id: row
    signal open()
    required property var columns       // [x, width] of each column, from AlbumsView
    required property int albumId
    required property string title
    required property string artist
    required property string year
    required property string genre
    required property string songs
    required property string time
    required property string cover
    required property bool playing
    property alias loading: art.loading
    height: 48
    radius: 6
    color: hover.hovered ? Theme.hover : "transparent"
    Accessible.role: Accessible.Button
    Accessible.name: row.title + ", " + row.artist

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: row.open() }

    component Cell: Text {
        property int column
        x: row.columns[column][0]
        width: row.columns[column][1]
        height: row.height
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        color: Theme.cell
        font { family: Theme.sans; pixelSize: 13; features: { "tnum": 1 } }
    }

    Cover {
        id: art
        x: row.columns[0][0]
        y: 6
        width: 36
        height: 36
        radius: 5
        matte: row.color.a > 0 ? row.color : Theme.bg
        source: row.cover
        emptyText: ""
    }
    Cell { column: 1; text: row.title; color: row.playing ? Theme.accentHi : Theme.text; font.weight: Font.DemiBold }
    Cell { column: 2; text: row.artist }
    Cell { column: 3; text: row.year || "—"; color: row.year ? Theme.cell : Theme.faint }
    Cell { column: 4; text: row.genre }
    Cell { column: 5; text: row.songs; color: Theme.muted; horizontalAlignment: Text.AlignRight }
    Cell { column: 6; text: row.time; color: Theme.muted; horizontalAlignment: Text.AlignRight }
}
