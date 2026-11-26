import QtQuick
import "."

// A row of the Songs list: what the model gives, laid out in the view's columns; the song playing
// has its title in the accent. A double click asks for it to be played.
Rectangle {
    id: row
    signal activated()
    required property var columns       // [x, width] of each column, from SongsView
    required property string path
    required property bool playing
    required property string track
    required property string title
    required property string artist
    required property string album
    required property string genre
    required property string year
    required property int rating
    required property string time
    height: 36
    radius: 6
    color: hover.hovered ? Theme.hover : "transparent"

    HoverHandler { id: hover }
    TapHandler { onDoubleTapped: row.activated() }

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

    Cell { column: 0; text: row.track; color: Theme.muted; horizontalAlignment: Text.AlignRight }
    Cell { column: 1; text: row.title; color: row.playing ? Theme.accentHi : Theme.text }
    Cell { column: 2; text: row.artist }
    Cell { column: 3; text: row.album }
    Cell { column: 4; text: row.genre }
    Cell { column: 5; text: row.year || "—"; color: row.year ? Theme.cell : Theme.faint }
    Stars {
        x: row.columns[6][0]
        anchors.verticalCenter: parent.verticalCenter
        rating: row.rating
    }
    Cell { column: 7; text: row.time; color: Theme.muted; horizontalAlignment: Text.AlignRight }
}
