import QtQuick
import "."

// A chip: a genre to filter by (R2.6), chosen or not, or an album's state (`tone`: ok, warn, info).
Rectangle {
    id: chip
    signal clicked()
    property string label
    property string tone: ""            // "" for a filter chip
    property bool chosen: false
    property string icon: tone === "ok" ? "check" : tone === "warn" ? "attention" : tone === "info" ? "image" : ""
    readonly property color ink: tone === "ok" ? Theme.ok : tone === "warn" ? Theme.warn
                                 : chosen ? Theme.text : Theme.cell
    width: content.width + (tone ? 20 : 28)
    height: tone ? 26 : 32
    radius: height / 2
    color: tone === "ok" ? Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.12)
         : tone === "warn" ? Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.12)
         : chosen ? Theme.accentSoft : (hover.hovered && !tone ? Theme.hover : Theme.surface)
    border.color: chosen ? Theme.accent : (tone ? "transparent" : Theme.border)
    Accessible.role: tone ? Accessible.StaticText : Accessible.Button
    Accessible.name: chip.label

    HoverHandler { id: hover; enabled: chip.tone === "" }
    TapHandler { enabled: chip.tone === ""; onTapped: chip.clicked() }

    Row {
        id: content
        anchors.centerIn: parent
        spacing: 6
        Icon {
            anchors.verticalCenter: parent.verticalCenter
            visible: chip.icon !== ""
            name: chip.icon
            size: 13
            color: chip.ink
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: chip.label
            color: chip.ink
            font { family: Theme.sans; pixelSize: chip.tone ? 12 : 13; weight: chip.chosen ? Font.DemiBold : Font.Normal }
        }
    }
}
