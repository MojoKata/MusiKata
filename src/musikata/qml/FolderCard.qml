import QtQuick
import "."

// A folder in Folders' Cards mode (R2.9.4, L06-folders-cards): a wide card with its cover at the
// left, its name and counts; a selected one outlined, its check at the top right. The tint by the
// cover's colour comes with R6.2.2's colour pick, and the state chip with R3.9 (slice 7).
Rectangle {
    id: card
    signal tapped(int modifiers)
    signal activated()
    signal toggled()
    required property string name
    required property string line
    required property string cover
    required property bool playing
    required property bool selected
    property alias loading: art.loading
    height: 96
    radius: 12
    color: hover.hovered ? Theme.raised : Theme.surface
    border.color: card.selected || card.playing ? Theme.accent : Theme.border
    border.width: card.selected ? 2 : 1
    Accessible.role: Accessible.ListItem
    Accessible.name: card.name + ", " + card.line
    Accessible.selected: card.selected

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler {
        id: tap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: card.tapped(tap.point.modifiers)
        onDoubleTapped: card.activated()
    }

    Cover {
        id: art
        x: 12
        y: 12
        width: 72
        height: 72
        radius: 8
        matte: card.color
        source: card.cover
        emptyText: ""
        emptyIcon: "folder"
    }
    Text {
        x: art.x + art.width + 16
        y: 16
        width: card.width - x - 44
        elide: Text.ElideRight
        text: card.name
        color: Theme.text
        font { family: Theme.sans; pixelSize: 16; weight: Font.Bold }
    }
    Text {
        x: art.x + art.width + 16
        y: 42
        width: card.width - x - 16
        elide: Text.ElideRight
        text: card.line
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }
    Check {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        round: true
        visible: hover.hovered || card.selected
        mark: card.selected ? "all" : "none"
        onToggled: card.toggled()
    }
}
