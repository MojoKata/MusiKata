import QtQuick
import "."

// A song of a playlist's page (R8.2, P01-playlist-drag): its drag handle (reordering by dragging is
// R8.5's), its number, cover, title over artist, album, genre, rating and length; the song playing
// has its title in the accent. An entry no song is at (R8.7) is dimmed, says "Missing" (or "Not in
// your music folder") and the path it names, and has Find. A click selects it (Ctrl/⌘ and Shift as
// everywhere, R2.6), selected it is highlighted, the current row outlined while the list has the
// focus (R6.9); a double click plays it, a right click opens its menu (SongMenu).
Rectangle {
    id: row
    signal tapped(int modifiers)
    signal activated()
    signal menu()
    signal rated(int star)
    signal find()
    required property var columns      // [x, width] of each column: handle, #, title, album, genre, rating, time
    required property string number
    required property string title
    required property string artist
    required property string album
    required property string genre
    required property int rating
    required property string time
    required property string cover
    required property bool playing
    required property bool selected
    required property bool current
    required property bool missing
    required property string note
    required property string where
    property bool focused: false
    readonly property bool ringed: current && focused
    height: 44
    radius: 8
    color: row.selected ? Theme.sel : (hover.hovered ? Theme.hover : "transparent")
    border.color: Theme.accent
    border.width: row.ringed ? 1.5 : 0
    Accessible.role: Accessible.ListItem
    Accessible.name: row.missing ? qsTr("%1, %2: %3").arg(row.title).arg(row.note).arg(row.where) : row.title
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
        font { family: Theme.sans; pixelSize: 13; features: { "tnum": 1 } }
    }

    Icon {  // the drag handle (R8.5: dragging to reorder comes with it)
        x: row.columns[0][0]
        anchors.verticalCenter: parent.verticalCenter
        name: "drag"
        size: 14
        color: Theme.faint
    }
    Cell { column: 1; text: row.number; color: Theme.muted; horizontalAlignment: Text.AlignRight }
    Cover {
        x: row.columns[2][0]
        anchors.verticalCenter: parent.verticalCenter
        width: 32
        height: 32
        radius: 5
        sourceSide: 64
        matte: Theme.bg
        emptyText: ""
        source: row.cover
        visible: !row.missing
    }
    Rectangle {  // a missing entry's place for its cover
        x: row.columns[2][0]
        anchors.verticalCenter: parent.verticalCenter
        width: 32
        height: 32
        radius: 5
        color: "transparent"
        border.color: Theme.borderStrong
        visible: row.missing
        Icon { anchors.centerIn: parent; name: "song"; size: 14; color: Theme.faint }
    }
    Column {
        x: row.columns[2][0] + 44
        width: row.columns[2][1] - 44
        anchors.verticalCenter: parent.verticalCenter
        opacity: row.missing ? 0.55 : 1
        Text {
            width: parent.width
            elide: Text.ElideRight
            text: row.title
            color: row.playing ? Theme.accentHi : Theme.text
            font { family: Theme.sans; pixelSize: 14 }
        }
        Text {
            width: parent.width
            elide: Text.ElideMiddle
            text: row.missing ? row.note + " · " + row.where : row.artist
            color: row.missing ? Theme.warn : Theme.muted
            font { family: Theme.sans; pixelSize: 12 }
        }
    }
    Cell { column: 3; text: row.album; visible: !row.missing }
    Cell { column: 4; text: row.genre; visible: !row.missing }
    Stars {
        x: row.columns[5][0]
        anchors.verticalCenter: parent.verticalCenter
        visible: !row.missing
        rating: row.rating
        size: 12
        settable: true
        onClicked: (star) => row.rated(star)
    }
    Btn {  // Find (R8.7): the file looked for under the root by its name and its tags
        objectName: "findMissing"
        x: row.columns[3][0]
        anchors.verticalCenter: parent.verticalCenter
        height: 30
        visible: row.missing
        label: qsTr("Find…")
        icon: "search"
        onClicked: row.find()
    }
    Cell { column: 6; text: row.time; color: Theme.muted; horizontalAlignment: Text.AlignRight }
}
