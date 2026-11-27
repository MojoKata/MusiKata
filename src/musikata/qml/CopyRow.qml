import QtQuick
import "."

// A copy of a song (R2.12, L09-needs-attention): Keep, a radio button, on the copy kept; Trash, a
// checkbox, on each other; its format, its path under the root, its plays and rating, and on the
// copy MusiKata proposes, why it is kept ("Keep: lossless"). In the Review… dialog (`detailed`)
// the line under the path says its details: bit rate, sample rate, length and album. What a click
// does is the bridge's (`keep`, `toggle`).
Item {
    id: copyRow
    required property var copy
    property bool detailed: false
    signal keep()
    signal toggle()
    readonly property real tail: copyRow.width - 360   // where the plays, stars and why begin
    height: copyRow.detailed ? 60 : 52
    Accessible.role: Accessible.ListItem
    Accessible.name: copyRow.copy.path

    Rectangle {  // between this copy and the one above
        width: parent.width
        height: 1
        color: Theme.border
        visible: !copyRow.copy.kept
    }
    Item {  // Keep: the radio button
        id: radio
        objectName: "keepCopy"
        x: 8
        anchors.verticalCenter: parent.verticalCenter
        width: 22
        height: 22
        Accessible.role: Accessible.RadioButton
        Accessible.name: qsTr("Keep %1").arg(copyRow.copy.name)
        Accessible.checked: copyRow.copy.kept
        Rectangle {
            anchors.fill: parent
            radius: 11
            color: "transparent"
            border.width: 2
            border.color: copyRow.copy.kept ? Theme.accent : Theme.borderStrong
        }
        Rectangle {
            anchors.centerIn: parent
            width: 10
            height: 10
            radius: 5
            color: Theme.accent
            visible: copyRow.copy.kept
        }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: copyRow.keep() }
    }
    Text {
        x: 40
        anchors.verticalCenter: parent.verticalCenter
        visible: copyRow.copy.kept
        text: qsTr("Keep")
        color: Theme.accentHi
        font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
    }
    Check {  // Trash: the checkbox
        id: check
        objectName: "trashCopy"
        x: 104
        anchors.verticalCenter: parent.verticalCenter
        visible: !copyRow.copy.kept
        mark: copyRow.copy.checked ? "all" : "none"
        Accessible.name: qsTr("Trash %1").arg(copyRow.copy.name)
        onToggled: copyRow.toggle()
    }
    Text {
        x: check.x + check.width + 10
        anchors.verticalCenter: parent.verticalCenter
        visible: !copyRow.copy.kept
        text: qsTr("Trash")
        color: copyRow.copy.checked ? Theme.err : Theme.muted
        font { family: Theme.sans; pixelSize: 14; weight: copyRow.copy.checked ? Font.DemiBold : Font.Normal }
    }
    Text {
        id: format
        x: 196
        width: 148
        anchors.verticalCenter: parent.verticalCenter
        elide: Text.ElideRight
        text: copyRow.copy.format
        color: Theme.text
        font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
    }
    Text {
        id: path
        x: 356
        y: copyRow.detailed ? 10 : (copyRow.height - height) / 2
        width: copyRow.tail - 16 - x
        elide: Text.ElideMiddle
        text: copyRow.copy.path
        color: Theme.cell
        font { family: Theme.sans; pixelSize: 14 }
    }
    Text {
        x: path.x
        y: 33
        width: path.width
        visible: copyRow.detailed
        elide: Text.ElideRight
        text: copyRow.copy.album ? copyRow.copy.details + " · " + copyRow.copy.album : copyRow.copy.details
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 12 }
    }
    Text {
        x: copyRow.tail
        width: 64
        anchors.verticalCenter: parent.verticalCenter
        horizontalAlignment: Text.AlignRight
        elide: Text.ElideRight
        text: copyRow.copy.plays
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }
    Stars {
        x: copyRow.tail + 76
        anchors.verticalCenter: parent.verticalCenter
        rating: copyRow.copy.rating
        size: 12
    }
    Text {
        x: copyRow.tail + 156
        width: copyRow.width - x - 8
        anchors.verticalCenter: parent.verticalCenter
        elide: Text.ElideRight
        text: copyRow.copy.why
        color: Theme.ok
        font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
    }
}
