import QtQuick
import "."

// A folder in Folders' Cards mode (R2.9.4, L06-folders-cards): a wide card with its cover at the
// left, its name and counts, and its state chip (R2.9.5: "Fixable" or "Untagged", how many files
// in its tooltip); a selected one outlined, its check at the top right; tinted with its cover's
// colour (R6.2.2, `tints`), strongest on the left, by the cover.
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
    property var pathChip: ({})        // R2.9.5: its chip's text, tone and tip, {} for none
    property alias loading: art.loading
    property var tints: null
    readonly property string tint: card.tints !== null ? (card.tints.revision, card.tints.of(card.cover)) : ""
    readonly property color base: hover.hovered ? Theme.raised : Theme.surface
    readonly property color shade: card.tint !== "" ? card.tint : card.base
    readonly property color leftShade: Qt.tint(card.base, Qt.rgba(card.shade.r, card.shade.g, card.shade.b, 0.7))
    readonly property color rightShade: Qt.tint(card.base, Qt.rgba(card.shade.r, card.shade.g, card.shade.b, 0.3))
    height: 96
    radius: 12
    color: card.base
    gradient: Gradient {
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: card.leftShade }
        GradientStop { position: 1; color: card.rightShade }
    }
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
        matte: card.leftShade
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
    Chip {
        objectName: "stateChip"
        x: art.x + art.width + 16
        y: 64
        visible: card.pathChip.text !== undefined
        label: card.pathChip.text || ""
        tone: card.pathChip.tone || "info"
        tip: card.pathChip.tip || ""
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
