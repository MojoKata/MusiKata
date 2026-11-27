import QtQuick
import QtQuick.Controls.Basic
import "."

// A playlist in the sidebar (R6.3, P01-playlist-drag): its icon, name and count, highlighted while
// its page is open; a click opens it, a right click its menu (`menu`). While its name is edited
// (+, New playlist from selection, Rename; R8.3, R8.4) the name is a text box with the name
// selected: Enter, or a click elsewhere, keeps what was typed; Esc the name it had.
Item {
    id: item
    signal clicked()
    signal menu()
    signal renamed(string name)
    signal cancelled()
    required property string name
    required property string count
    property bool active
    property bool editing: false
    height: 32
    Accessible.role: Accessible.Button
    Accessible.name: qsTr("%1, %2 songs").arg(item.name).arg(item.count)

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: item.clicked() }
    TapHandler { acceptedButtons: Qt.RightButton; onTapped: item.menu() }
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
        name: "playlist"
        size: 17
        color: item.active ? Theme.accentHi : Theme.muted
    }
    Text {
        id: count
        anchors.right: parent.right
        anchors.rightMargin: 22
        anchors.verticalCenter: parent.verticalCenter
        visible: !item.editing
        text: item.count
        color: Theme.faint
        font { family: Theme.sans; pixelSize: 12; features: { "tnum": 1 } }
    }
    Text {
        x: 50
        width: count.x - 8 - x
        height: item.height
        visible: !item.editing
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        text: item.name
        color: item.active ? Theme.text : Theme.cell
        font { family: Theme.sans; pixelSize: 13; weight: item.active ? Font.DemiBold : Font.Normal }
    }
    TextField {
        id: field
        objectName: "playlistName"
        x: 44
        width: item.width - x - 14
        height: 28
        anchors.verticalCenter: parent.verticalCenter
        visible: item.editing
        text: item.name
        color: Theme.text
        selectedTextColor: Theme.text
        selectionColor: Theme.accentSoft
        leftPadding: 6
        font { family: Theme.sans; pixelSize: 13 }
        Accessible.name: qsTr("Playlist name")
        background: Rectangle { radius: 6; color: Theme.surface; border.color: Theme.accent }
        onVisibleChanged: if (visible) { text = item.name; forceActiveFocus(); selectAll() }
        Keys.onReturnPressed: item.renamed(field.text)
        Keys.onEnterPressed: item.renamed(field.text)
        Keys.onEscapePressed: item.cancelled()
        onActiveFocusChanged: if (!activeFocus && item.editing) item.renamed(field.text)
    }
}
