import QtQuick
import QtQuick.Controls.Basic
import "."

// The selection bar (R2.9.6, L06-folders-cards): what is selected, "2 folders · 21 songs selected";
// Play, which plays its first song (the queue comes with slice 4); the actions of later slices
// (Add to playlist, Edit tags, Infer from path, Organize…) faded, saying so in their tooltips; and
// ✕, which clears it.
Rectangle {
    id: bar
    required property var folders
    width: Math.min(content.width + 32, parent ? parent.width - 32 : content.width + 32)
    height: 46
    radius: 12
    color: Theme.raised
    border.color: Theme.borderStrong
    property string playNote: ""  // why Play waits: the root isn't there (R2.10)
    Accessible.role: Accessible.ToolBar
    Accessible.name: bar.folders.selectionText

    component Action: Rectangle {
        id: action
        signal clicked()
        property string label
        property string icon
        property string later: ""
        readonly property bool available: later === ""
        width: actionRow.width + 16
        height: 32
        radius: 8
        color: actionHover.hovered && available ? Theme.hover : "transparent"
        opacity: available ? 1 : 0.45
        Accessible.role: Accessible.Button
        Accessible.name: label
        Accessible.description: later
        HoverHandler { id: actionHover; cursorShape: action.available ? Qt.PointingHandCursor : Qt.ArrowCursor }
        TapHandler { enabled: action.available; onTapped: action.clicked() }
        ToolTip.visible: actionHover.hovered && !available
        ToolTip.text: later
        ToolTip.delay: 400
        Row {
            id: actionRow
            anchors.centerIn: parent
            spacing: 6
            Icon { anchors.verticalCenter: parent.verticalCenter; name: action.icon; size: 15; color: Theme.accentHi }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: action.label
                color: Theme.accentHi
                font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
            }
        }
    }

    Row {
        id: content
        x: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6
        Text {
            objectName: "selectionText"
            anchors.verticalCenter: parent.verticalCenter
            rightPadding: 10
            text: bar.folders.selectionText
            color: Theme.text
            font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
        }
        Action {
            objectName: "playSelection"
            label: qsTr("Play")
            icon: "play"
            later: bar.playNote
            onClicked: bar.folders.playSelection()
        }
        Repeater {
            model: bar.folders.laterActions
            Action {
                required property var modelData
                label: modelData.label
                icon: modelData.icon
                later: modelData.later
            }
        }
        Rectangle {
            objectName: "clearSelection"
            anchors.verticalCenter: parent.verticalCenter
            width: 28
            height: 28
            radius: 6
            color: clearHover.hovered ? Theme.hover : "transparent"
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Clear the selection")
            HoverHandler { id: clearHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: bar.folders.model.clearSelection() }
            Icon { anchors.centerIn: parent; name: "close"; size: 14; color: Theme.muted }
        }
    }
}
