import QtQuick
import QtQuick.Controls.Basic
import "."

// A button of the pages (L02-album): an icon and a label, the primary one on the primary gradient
// (R6.2), a quiet one only its label in the accent (X02-root-unavailable's Choose another
// folder…). One that can't act now (`later`: its action comes with a later slice, or it waits on
// the root, R2.10) is drawn faded and says why in its
// tooltip, and does nothing.
Rectangle {
    id: btn
    signal clicked()
    property string label
    property string icon
    property bool primary: false
    property bool quiet: false
    property string later: ""          // the tooltip of a button not built yet
    readonly property bool available: later === ""
    property real minWidth: 0
    width: Math.max(btn.minWidth, row.width + 32)
    height: 36
    radius: 8
    color: btn.primary ? Theme.primaryA : (hover.hovered && btn.available ? Theme.hover
                                          : btn.quiet ? "transparent" : Theme.surface)
    border.color: btn.primary || btn.quiet ? "transparent" : Theme.borderStrong
    gradient: btn.primary ? primaryGradient : null
    opacity: btn.available ? 1 : 0.45
    Accessible.role: Accessible.Button
    Accessible.name: btn.label
    Accessible.description: btn.later

    Gradient {
        id: primaryGradient
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: Theme.primaryA }
        GradientStop { position: 1; color: Theme.primaryB }
    }
    HoverHandler { id: hover; cursorShape: btn.available ? Qt.PointingHandCursor : Qt.ArrowCursor }
    TapHandler { enabled: btn.available; onTapped: btn.clicked() }
    ToolTip.visible: hover.hovered && !btn.available
    ToolTip.text: btn.later
    ToolTip.delay: 400

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 8
        Icon {
            anchors.verticalCenter: parent.verticalCenter
            name: btn.icon
            size: 16
            color: btn.primary ? "#ffffff" : btn.quiet ? Theme.accentHi : Theme.text
            visible: btn.icon !== ""
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: btn.label
            color: btn.primary ? "#ffffff" : btn.quiet ? Theme.accentHi : Theme.text
            font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
        }
    }
}
