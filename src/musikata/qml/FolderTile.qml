import QtQuick
import "."

// A folder in Folders' image modes (R2.9.4, L04-folders, L05-folders-large): its cover or mosaic
// (R5.8), or the dashed No art tile; its name and counts under it. The folder holding the song
// playing is outlined with the playing mark on its cover; a selected one is outlined in the accent
// with its checkbox ticked. Under the pointer the checkbox and a play button sit on the cover. A dot
// at its cover's corner says the worst path-match state beneath it (R2.9.5): amber, files can be
// fixed; red, files have no tags; none when they all match.
Item {
    id: tile
    signal tapped(int modifiers)
    signal activated()
    signal toggled()
    signal play()
    required property string name
    required property string line
    required property string cover
    required property bool playing
    required property bool selected
    property bool large: false
    property string dot: ""             // R2.9.5: "warn", "err", or "" for none
    property alias loading: art.loading
    height: width + (large ? 60 : 56)
    Accessible.role: Accessible.ListItem
    Accessible.name: tile.name + ", " + tile.line
    Accessible.selected: tile.selected

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler {
        id: tap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: tile.tapped(tap.point.modifiers)
        onDoubleTapped: tile.activated()
    }

    Rectangle {  // the outline: selected, or holding the song playing
        x: -4
        y: -4
        width: tile.width + 8
        height: tile.width + 8
        radius: 13
        color: "transparent"
        border.color: Theme.accent
        border.width: 2
        visible: tile.playing || tile.selected
    }
    Cover {
        id: art
        width: tile.width
        height: tile.width
        sourceSide: tile.large ? 512 : 256
        source: tile.cover
        emptyText: qsTr("No art")
        emptyIcon: "folder"
    }
    Rectangle {  // the worst path-match state beneath it (R2.9.5)
        objectName: "stateDot"
        x: tile.width - 12 - width
        y: 12
        width: 14
        height: 14
        radius: 7
        visible: tile.dot !== ""
        color: tile.dot === "err" ? Theme.err : Theme.warn
        border.color: Theme.bg
        border.width: 2
        Accessible.role: Accessible.StaticText
        Accessible.name: tile.dot === "err" ? qsTr("Files with no tags") : qsTr("Files to fix")
    }
    Icon {  // the playing mark
        x: 12
        y: tile.width - 12 - size
        visible: tile.playing
        name: "wave"
        size: 18
        color: "#ffffff"
    }
    Check {
        x: 10
        y: 10
        round: true
        onImage: true
        visible: hover.hovered || tile.selected
        mark: tile.selected ? "all" : "none"
        onToggled: tile.toggled()
    }
    Rectangle {
        anchors.right: art.right
        anchors.bottom: art.bottom
        anchors.margins: 12
        width: 42
        height: 42
        radius: 21
        color: "#ffffff"
        visible: hover.hovered
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Play %1").arg(tile.name)
        Icon { anchors.centerIn: parent; anchors.horizontalCenterOffset: 1; name: "play"; size: 16; color: Theme.bg }
        TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: tile.play() }
    }
    Text {
        y: tile.width + 10
        width: tile.width
        elide: Text.ElideRight
        text: tile.name
        color: Theme.text
        font { family: Theme.sans; pixelSize: tile.large ? 17 : 14; weight: Font.DemiBold }
    }
    Text {
        y: tile.width + (tile.large ? 35 : 31)
        width: tile.width
        elide: Text.ElideRight
        text: tile.line
        color: Theme.muted
        font { family: Theme.sans; pixelSize: tile.large ? 14 : 12 }
    }
}
