import QtQuick
import "."

// A genre in the Genres view (R9.1, G01-genres): a card tinted in the genre's own colour (one of
// Theme's, the same for the genre wherever it is shown), its name, its songs and albums, and three
// of its covers overlapping. A click opens its page; the ⋯ button, shown under the pointer or while
// its menu is open, opens its menu (R9.4).
Item {
    id: tile
    signal open()
    signal menu(var button)
    required property string name
    required property string line
    required property var covers
    required property int tone
    property bool menuOpen: false
    readonly property var tones: [Theme.accent, Theme.cyan, Theme.warn, Theme.pink, Theme.ok,
                                  Theme.err, Theme.accentHi, Theme.progress]
    readonly property color tint: tile.tones[tile.tone % tile.tones.length]
    readonly property bool loading: {
        for (let i = 0; i < pieces.count; i++)
            if (pieces.itemAt(i) && pieces.itemAt(i).loading) return true
        return false
    }
    height: 112
    Accessible.role: Accessible.Button
    Accessible.name: tile.name + ", " + tile.line

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: tile.open() }

    Rectangle {
        anchors.fill: parent
        radius: 14
        border.width: tile.menuOpen ? 1.6 : 1
        border.color: tile.menuOpen ? Theme.accent : Qt.rgba(tile.tint.r, tile.tint.g, tile.tint.b, 0.35)
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.tint(Theme.bg, Qt.rgba(tile.tint.r, tile.tint.g, tile.tint.b, 0.30)) }
            GradientStop { position: 1; color: Qt.tint(Theme.bg, Qt.rgba(tile.tint.r, tile.tint.g, tile.tint.b, 0.06)) }
        }
    }
    Text {
        x: 18
        y: 14
        width: tile.width - 18 - 44
        elide: Text.ElideRight
        text: tile.name
        color: Theme.text
        font { family: Theme.sans; pixelSize: 17; weight: Font.Bold }
    }
    Text {
        x: 18
        y: 43
        width: tile.width - 36
        elide: Text.ElideRight
        text: tile.line
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 12 }
    }
    Repeater {  // three of its covers, overlapping
        id: pieces
        model: tile.covers
        Cover {
            required property int index
            required property string modelData
            x: 18 + index * 22
            y: tile.height - 38
            z: index
            width: 26
            height: 26
            radius: 0
            sourceSide: 64
            source: modelData
        }
    }
    Item {
        id: more
        objectName: "genreMore"
        x: tile.width - 36
        y: 10
        width: 28
        height: 28
        visible: hover.hovered || tile.menuOpen
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("More for %1").arg(tile.name)
        Rectangle { anchors.fill: parent; radius: 14; color: moreHover.hovered ? Theme.hover : "transparent" }
        Icon { anchors.centerIn: parent; name: "more"; size: 16; color: Theme.text }
        HoverHandler { id: moreHover }
        TapHandler { onTapped: tile.menu(more) }
    }
}
