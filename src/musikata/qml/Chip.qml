import QtQuick
import QtQuick.Controls.Basic
import "."

// A chip: a genre to filter by (R2.6), chosen or not, or an album's or a file's state (`tone`: ok,
// warn, info, err). A state's chip says one word, and its tooltip (`tip`) the detail: shown on
// hover, and while the chip has the focus; a screen reader reads it as the chip's description.
Rectangle {
    id: chip
    signal clicked()
    property string label
    property string tone: ""            // "" for a filter chip
    property string tip: ""             // the detail, in its tooltip; "" for none
    property bool chosen: false
    property string icon: tone === "ok" ? "check" : tone === "warn" || tone === "err" ? "attention"
                        : tone === "info" ? "image" : ""
    readonly property color ink: tone === "ok" ? Theme.ok : tone === "warn" ? Theme.warn
                                 : tone === "err" ? Theme.err : chosen ? Theme.text : Theme.cell
    width: content.width + (tone ? 20 : 28)
    height: tone ? 26 : 32
    radius: height / 2
    color: tone === "ok" ? Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.12)
         : tone === "warn" ? Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.12)
         : tone === "err" ? Qt.rgba(Theme.err.r, Theme.err.g, Theme.err.b, 0.12)
         : chosen ? Theme.accentSoft : (hover.hovered && !tone ? Theme.hover : Theme.surface)
    border.color: chosen ? Theme.accent : (tone ? "transparent" : Theme.border)
    Accessible.role: tone ? Accessible.StaticText : Accessible.Button
    Accessible.name: chip.label
    Accessible.description: chip.tip

    HoverHandler { id: hover; enabled: chip.tone === "" || chip.tip !== "" }
    TapHandler { enabled: chip.tone === ""; onTapped: chip.clicked() }
    ToolTip.visible: (hover.hovered || chip.activeFocus) && chip.tip !== ""
    ToolTip.text: chip.tip
    ToolTip.delay: 400

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
