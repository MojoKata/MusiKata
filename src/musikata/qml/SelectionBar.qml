import QtQuick
import QtQuick.Controls.Basic
import "."

// The selection bar (R2.9.6, L06-folders-cards; L03-songs-bulk-edit): what is selected, "2 folders ·
// 21 songs selected", "4 selected"; its first action, Play in Folders (the songs selected, from the
// first, R7.1) or Play next in Songs (R7.2); the actions of later slices (Add to playlist, Edit tags,
// Infer from path, Organize…) faded, saying so in their tooltips; and ✕, which clears it.
Rectangle {
    id: bar
    signal play()
    signal clear()
    required property string text
    property string playLabel: qsTr("Play")
    property string playObjectName: "playSelection"
    property var laterActions: []
    width: Math.min(content.width + 32, parent ? parent.width - 32 : content.width + 32)
    height: 46
    radius: 12
    color: Theme.raised
    border.color: Theme.borderStrong
    property string playNote: ""  // why Play waits: the root isn't there (R2.10)
    Accessible.role: Accessible.ToolBar
    Accessible.name: bar.text

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
            text: bar.text
            color: Theme.text
            font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
        }
        Action {
            objectName: bar.playObjectName
            label: bar.playLabel
            icon: "play"
            later: bar.playNote
            onClicked: bar.play()
        }
        Repeater {
            model: bar.laterActions
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
            TapHandler { onTapped: bar.clear() }
            Icon { anchors.centerIn: parent; name: "close"; size: 14; color: Theme.muted }
        }
    }
}
