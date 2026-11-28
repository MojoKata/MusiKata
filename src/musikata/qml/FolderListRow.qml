import QtQuick
import "."

// A row of Folders' List mode (R2.9.4, L07-folders-list): its checkbox; a folder two rows tall,
// its cover the row's full height, its name over its counts, then the artist, album and year its
// songs share and their total time; a file one row tall with its icon, its name, artist, album,
// year, rating and time. Selected, it is highlighted. A folder's state chip (R2.9.5: "Fixable" or
// "Untagged", how many files in its tooltip) follows its counts.
Rectangle {
    id: row
    signal tapped(int modifiers)
    signal activated()
    signal menu()  // a right click: its songs' menu (SongMenu)
    signal toggled()
    signal rated(int star)  // a star of a file's rating clicked (R10.2)
    required property var columns       // [x, width]: check, name, artist, album, year, rating, time
    required property bool isFolder
    required property string name
    required property string line
    required property string cover
    required property string artist
    required property string album
    required property string year
    required property int rating
    required property string time
    required property bool playing
    required property bool selected
    property var pathChip: ({})        // R2.9.5: a folder's chip's text, tone and tip, {} for none
    property alias loading: art.loading
    height: isFolder ? 64 : 36
    radius: 8
    color: row.selected ? Theme.sel : (hover.hovered ? Theme.hover : "transparent")
    Accessible.role: Accessible.ListItem
    Accessible.name: row.name
    Accessible.selected: row.selected

    HoverHandler { id: hover }
    TapHandler { acceptedButtons: Qt.RightButton; onTapped: row.menu() }
    TapHandler {
        id: tap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: row.tapped(tap.point.modifiers)
        onDoubleTapped: row.activated()
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

    Check {
        x: row.columns[0][0]
        anchors.verticalCenter: parent.verticalCenter
        mark: row.selected ? "all" : "none"
        onToggled: row.toggled()
    }
    Cover {
        id: art
        x: row.columns[1][0]
        y: 4
        width: row.isFolder ? 56 : 0
        height: 56
        visible: row.isFolder
        radius: 6
        matte: row.color.a > 0 ? row.color : Theme.bg
        source: row.isFolder ? row.cover : ""
        emptyText: ""
        emptyIcon: "folder"
    }
    Icon {
        x: row.columns[1][0] + 4
        anchors.verticalCenter: parent.verticalCenter
        visible: !row.isFolder
        name: "file"
        size: 15
        color: Theme.muted
    }
    Text {
        x: row.columns[1][0] + (row.isFolder ? 72 : 30)
        y: row.isFolder ? 10 : 0
        width: row.columns[1][1] - (row.isFolder ? 72 : 30)
        height: row.isFolder ? 22 : row.height
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        text: row.name
        color: row.playing ? Theme.accentHi : Theme.text
        font { family: Theme.sans; pixelSize: row.isFolder ? 15 : 13; weight: row.isFolder ? Font.DemiBold : Font.Normal }
    }
    Text {
        id: counts
        x: row.columns[1][0] + 72
        y: 34
        width: Math.min(implicitWidth, row.columns[1][1] - 72 - (stateChip.visible ? stateChip.width + 8 : 0))
        height: 20
        verticalAlignment: Text.AlignVCenter
        visible: row.isFolder
        elide: Text.ElideRight
        text: row.line
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 12 }
    }
    Chip {
        id: stateChip
        objectName: "stateChip"
        x: counts.x + counts.width + 8
        y: 31
        height: 22
        visible: row.isFolder && row.pathChip.text !== undefined
        label: row.pathChip.text || ""
        tone: row.pathChip.tone || "info"
        tip: row.pathChip.tip || ""
    }
    Cell { column: 2; text: row.artist || "—"; color: row.artist ? Theme.cell : Theme.faint }
    Cell { column: 3; text: row.album || "—"; color: row.album ? Theme.cell : Theme.faint }
    Cell { column: 4; text: row.year || "—"; color: row.year ? Theme.cell : Theme.faint }
    Stars {
        x: row.columns[5][0]
        anchors.verticalCenter: parent.verticalCenter
        visible: !row.isFolder
        rating: row.rating
        settable: !row.isFolder
        onClicked: (star) => row.rated(star)
    }
    Cell { column: 6; text: row.time; color: Theme.muted; horizontalAlignment: Text.AlignRight }
}
