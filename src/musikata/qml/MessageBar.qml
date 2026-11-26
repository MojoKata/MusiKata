import QtQuick
import "."

// The message that follows a finished action (R6.7): short-lived, at the foot of the view above
// the now-playing bar; one about a save, or an undo, carries **Undo** (R4.9). Its text, whether it
// offers Undo and how long it stays are the history's (musikata.history).
Rectangle {
    id: bar
    required property var history
    readonly property var message: bar.history.message
    visible: bar.message.text !== undefined
    width: Math.min(row.width + 28, maxWidth)
    property real maxWidth: 640
    height: 48
    radius: 12
    color: Theme.raised
    border.color: Theme.borderStrong
    Accessible.role: Accessible.AlertMessage
    Accessible.name: bar.message.text || ""

    Row {
        id: row
        x: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 12
        Icon { anchors.verticalCenter: parent.verticalCenter; name: "check"; size: 16; color: Theme.ok }
        Text {
            id: said
            objectName: "messageText"
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, bar.maxWidth - 28 - 16 - 12 - (undo.visible ? undo.width + 12 : 0) - 40)
            elide: Text.ElideRight
            text: bar.message.text || ""
            color: Theme.text
            font { family: Theme.sans; pixelSize: 13 }
        }
        Btn {
            id: undo
            objectName: "messageUndo"
            anchors.verticalCenter: parent.verticalCenter
            visible: (bar.message.undo || "") !== ""
            label: qsTr("Undo")
            icon: "undo"
            quiet: true
            height: 32
            onClicked: bar.history.undoMessage()
        }
        Item {
            objectName: "dismissMessage"
            anchors.verticalCenter: parent.verticalCenter
            width: 28
            height: 28
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Dismiss")
            Rectangle { anchors.fill: parent; radius: 14; color: dismissHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "close"; size: 14; color: Theme.muted }
            HoverHandler { id: dismissHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: bar.history.dismiss() }
        }
    }
}
