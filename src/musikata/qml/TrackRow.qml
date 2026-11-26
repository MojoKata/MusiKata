import QtQuick
import "."

// A song on an album's or an artist's page (L02-album): its track number, or under the pointer a
// play button, or while it plays the playing mark; its title, the column the page adds (`extra`:
// the album, on an artist's page), its rating and length. A click on the play button or a double
// click plays it.
Rectangle {
    id: row
    signal activated()
    required property var columns       // [x, width] of each column: #, title, extra, rating, time
    required property string path
    required property bool playing
    required property string track
    required property string title
    required property string album
    required property int rating
    required property string time
    property bool showAlbum: false
    height: 40
    radius: 8
    color: row.playing ? Theme.accentSoft : (hover.hovered ? Theme.hover : "transparent")
    Accessible.role: Accessible.ListItem
    Accessible.name: row.title

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
        font { family: Theme.sans; pixelSize: 14; features: { "tnum": 1 } }
    }

    Cell {
        column: 0
        visible: !hover.hovered && !row.playing
        text: row.track
        color: Theme.muted
        horizontalAlignment: Text.AlignRight
    }
    Icon {
        x: row.columns[0][0] + row.columns[0][1] - size
        anchors.verticalCenter: parent.verticalCenter
        visible: row.playing && !hover.hovered
        name: "wave"
        size: 16
        color: Theme.accent
    }
    Item {
        x: row.columns[0][0] + row.columns[0][1] - 20
        width: 20
        height: row.height
        visible: hover.hovered
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Play %1").arg(row.title)
        Icon { anchors.centerIn: parent; name: "play"; size: 14; color: Theme.text }
        TapHandler { onTapped: row.activated() }
    }
    Cell { column: 1; text: row.title; color: row.playing ? Theme.accentHi : Theme.text }
    Cell { column: 2; visible: row.showAlbum; text: row.album; color: Theme.muted }
    Stars {
        x: row.columns[3][0]
        anchors.verticalCenter: parent.verticalCenter
        rating: row.rating
        size: 12
    }
    Cell { column: 4; text: row.time; color: Theme.muted; horizontalAlignment: Text.AlignRight }
}
