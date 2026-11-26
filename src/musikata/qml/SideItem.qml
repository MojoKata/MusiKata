import QtQuick
import "."

// A line of the sidebar (R6.3): its icon and label, highlighted while its view is open; a click
// opens it.
Item {
    id: item
    signal clicked()
    property string label
    property string icon
    property bool active
    height: 32
    Accessible.role: Accessible.Button
    Accessible.name: item.label

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: item.clicked() }
    Rectangle {
        x: 10
        width: item.width - 20
        height: item.height
        radius: 8
        color: Theme.hover
        visible: hover.hovered && !item.active
    }

    Rectangle {
        x: 10
        width: item.width - 20
        height: item.height
        radius: 8
        color: Theme.accentSoft
        visible: item.active
        Rectangle { y: 8; width: 3; height: 16; radius: 1.5; color: Theme.accent }
    }
    Icon {
        x: 32 - size / 2
        anchors.verticalCenter: parent.verticalCenter
        name: item.icon
        size: 17
        color: item.active ? Theme.accentHi : Theme.muted
    }
    Text {
        x: 50
        width: item.width - 70
        height: item.height
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        text: item.label
        color: item.active ? Theme.text : Theme.cell
        font { family: Theme.sans; pixelSize: 13; weight: item.active ? Font.DemiBold : Font.Normal }
    }
}
