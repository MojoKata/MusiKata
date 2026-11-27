import QtQuick
import QtQuick.Controls.Basic
import "."

// A playlist in the sidebar (R6.3, P01-playlist-drag): its icon, name and count, highlighted while
// its page is open; a click opens it, a right click its menu (`menu`). While its name is edited
// (+, New playlist from selection, Rename; R8.3, R8.4) the name is a text box with the name
// selected: Enter, or a click elsewhere, keeps what was typed; Esc the name it had. While a drag is
// over it (R8.5, P01-playlist-drag) it is outlined and named under the drag's card ("Add to Evening
// Focus"); the tour, holding a drag still, shows the card itself there.
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
    property bool targeted: false     // a drag is over it (R8.5): highlighted, and named under it
    property string dropText: ""      // what dropping does: "Add to Evening Focus"
    property var card: null           // the drag's card, shown under it while the tour holds one
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
    Rectangle {  // a drag over it (P01): outlined in the accent
        objectName: "dropTarget"
        x: 10
        width: item.width - 20
        height: item.height
        radius: 8
        color: Theme.accentSoft
        border.color: Theme.accent
        border.width: 2
        visible: item.targeted
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
    DragCard {  // the drag held still by the tour (P01): its card under the playlist
        objectName: "heldCard"
        x: 12
        y: item.height + 6
        visible: item.card !== null
        card: item.card || ({})
    }
    Rectangle {  // what dropping does, under where the drag's card is (P01)
        objectName: "dropLabel"
        x: 34
        y: item.height + 70
        width: Math.min(label.implicitWidth + 24, item.width - x - 10)
        height: 30
        radius: 6
        color: Theme.bar
        visible: item.targeted && item.dropText !== ""
        Text {
            id: label
            x: 12
            width: parent.width - 24
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
            text: item.dropText
            color: Theme.text
            font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
        }
    }
}
