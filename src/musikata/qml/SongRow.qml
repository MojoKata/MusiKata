import QtQuick
import "."

// A row of the Songs list: its checkbox, then what the model gives, laid out in the view's columns;
// the song playing has its title in the accent. Selected, it is highlighted (R2.6, L03); the current
// row is outlined while the list has the focus (R6.9). A click asks for it to be selected (Ctrl/⌘
// and Shift as everywhere), its checkbox for it to be added or taken away, a double click for it to
// be played, a right click for its menu (SongMenu).
Rectangle {
    id: row
    signal tapped(int modifiers)
    signal toggled()
    signal activated()
    signal menu()
    required property var columns       // [x, width] of each column, from SongsView
    required property string path
    required property bool playing
    required property bool selected
    required property bool current
    property bool focused: false        // the list has the keyboard focus: the current row outlined
    readonly property bool ringed: current && focused
    required property string track
    required property string title
    required property string artist
    required property string album
    required property string genre
    required property string year
    required property int rating
    required property string plays
    required property string time
    height: 36
    radius: 6
    color: row.selected ? Theme.sel : (hover.hovered ? Theme.hover : "transparent")
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

    Check {
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        mark: row.selected ? "all" : "none"
        onToggled: row.toggled()
    }

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
    Cell { column: 7; text: row.plays; horizontalAlignment: Text.AlignRight }
    Cell { column: 8; text: row.time; color: Theme.muted; horizontalAlignment: Text.AlignRight }
}
