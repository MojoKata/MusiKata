import QtQuick
import QtQuick.Controls.Basic
import "."

// A button of the pages (L02-album): an icon and a label, the primary one on the primary gradient
// (R6.2). One whose action comes with a later slice (`later`) is drawn faded and says so in its
// tooltip, and does nothing.
Rectangle {
    id: btn
    signal clicked()
    property string label
    property string icon
    property bool primary: false
    property string later: ""          // the tooltip of a button not built yet
    readonly property bool available: later === ""
    width: row.width + 32
    height: 36
    radius: 8
    color: btn.primary ? Theme.primaryA : (hover.hovered && btn.available ? Theme.hover : Theme.surface)
    border.color: btn.primary ? "transparent" : Theme.borderStrong
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
            color: btn.primary ? "#ffffff" : Theme.text
            visible: btn.icon !== ""
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: btn.label
            color: btn.primary ? "#ffffff" : Theme.text
            font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
        }
    }
}
