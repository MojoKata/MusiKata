import QtQuick
import "."

// A song on an album's or an artist's page (L02-album): its track number, or under the pointer a
// play button, or while it plays the playing mark; its title, the column the page adds (`extra`:
// the album, on an artist's page), its rating, its plays (R7.9) and length. A click on the play button or a double
// click plays it; a right click opens its menu (SongMenu). A click selects it (Ctrl/⌘ and Shift as
// everywhere, R2.6); selected, it is highlighted, and the current row is outlined while the list has
// the focus (R6.9).
Rectangle {
    id: row
    signal tapped(int modifiers)
    signal activated()
    signal menu()
    signal rated(int star)  // a star of its rating clicked (R10.2)
    required property var columns       // [x, width] of each column: #, title, extra, rating, plays, time
    required property string path
    required property bool playing
    required property string track
    required property string title
    required property string album
    required property int rating
    required property string plays
    required property string time
    required property bool selected
    required property bool current
    property bool focused: false        // the list has the keyboard focus: the current row outlined
    readonly property bool ringed: current && focused
    property bool showAlbum: false
    height: 40
    radius: 8
    color: row.selected ? Theme.sel : row.playing ? Theme.accentSoft : (hover.hovered ? Theme.hover : "transparent")
    border.color: Theme.accent
    border.width: row.ringed ? 1.5 : 0
    Accessible.role: Accessible.ListItem
    Accessible.name: row.title
    Accessible.selected: row.selected

    HoverHandler { id: hover }
    TapHandler {
        id: tap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: row.tapped(tap.point.modifiers)
        onDoubleTapped: row.activated()
    }
    TapHandler { acceptedButtons: Qt.RightButton; onTapped: row.menu() }

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
        TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: row.activated() }
    }
    Cell { column: 1; text: row.title; color: row.playing ? Theme.accentHi : Theme.text }
    Cell { column: 2; visible: row.showAlbum; text: row.album; color: Theme.muted }
    Stars {
        x: row.columns[3][0]
        anchors.verticalCenter: parent.verticalCenter
        rating: row.rating
        size: 12
        settable: true
        onClicked: (star) => row.rated(star)
    }
    Cell { column: 4; text: row.plays; horizontalAlignment: Text.AlignRight }
    Cell { column: 5; text: row.time; color: Theme.muted; horizontalAlignment: Text.AlignRight }
}
