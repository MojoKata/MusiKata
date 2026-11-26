import QtQuick
import "."

// An album in the Albums grid (L01-albums) and on an artist's page: its cover, title, and artist
// and year. The album playing is outlined; under the pointer a play button sits on the cover. A
// click opens its page; the play button plays it from its first song.
Item {
    id: tile
    signal open()
    signal play()
    required property string title
    required property string line
    required property string cover
    required property bool playing
    property alias loading: art.loading
    height: width + 56
    Accessible.role: Accessible.Button
    Accessible.name: tile.title + ", " + tile.line

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: tile.open() }

    Rectangle {  // the playing album's outline
        x: -4
        y: -4
        width: tile.width + 8
        height: tile.width + 8
        radius: 13
        color: "transparent"
        border.color: Theme.accent
        border.width: 2
        visible: tile.playing
    }
    Cover {
        id: art
        width: tile.width
        height: tile.width
        source: tile.cover
    }
    Rectangle {
        id: playButton
        anchors.centerIn: art
        width: 46
        height: 46
        radius: 23
        color: "#ffffff"
        visible: hover.hovered
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Play %1").arg(tile.title)
        Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: 1; name: "play"; size: 18; color: Theme.bg }
        TapHandler { onTapped: tile.play() }
    }
    Text {
        y: tile.width + 10
        width: tile.width
        elide: Text.ElideRight
        text: tile.title
        color: Theme.text
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
