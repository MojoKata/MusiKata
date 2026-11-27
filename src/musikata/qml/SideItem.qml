import QtQuick
import "."

// A line of the sidebar (R6.3): its icon and label, highlighted while its view is open, and its
// count when it has one (Needs attention's, R2.8, L09-needs-attention); a click opens it.
Item {
    id: item
    signal clicked()
    property string label
    property string icon
    property bool active
    property string badge: ""          // a count beside the label; "" for none
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
    Rectangle {
        id: badge
        objectName: "sideBadge"
        anchors.right: parent.right
        anchors.rightMargin: 20
        anchors.verticalCenter: parent.verticalCenter
        visible: item.badge !== ""
        width: Math.max(height, count.implicitWidth + 14)
        height: 20
        radius: 10
        color: Theme.warnSoft
        Text {
            id: count
            anchors.centerIn: parent
            text: item.badge
            color: Theme.warn
            font { family: Theme.sans; pixelSize: 11; weight: Font.Bold }
        }
    }
    Text {
        x: 50
        width: (badge.visible ? badge.x - 6 : item.width - 20) - x
        height: item.height
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        text: item.label
        color: item.active ? Theme.text : Theme.cell
        font { family: Theme.sans; pixelSize: 13; weight: item.active ? Font.DemiBold : Font.Normal }
    }
}
