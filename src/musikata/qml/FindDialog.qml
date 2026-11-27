import QtQuick
import QtQuick.Controls.Basic
import "."

// Find (R8.7), from a missing entry of a playlist's page or Needs attention's group (R2.8): over the
// window, "Find Slack Tide", the playlist and the place its entry names; the songs under the root of
// the same file name, or of its title and artist, each with why it is offered and Use this, which
// makes the entry name it; Cancel, × or Esc closes it, changing nothing. What it finds and says is
// musikata.playlists'.
Item {
    id: dialog
    required property var playlists
    readonly property real pad: 28
    visible: dialog.playlists.findOpen
    onVisibleChanged: if (visible) card.forceActiveFocus()

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        TapHandler { }
        WheelHandler { }
    }
    FocusScope {
        id: card
        objectName: "findDialog"
        width: Math.min(parent.width - 96, 760)
        height: Math.min(parent.height - 80, said.y + said.height + 16 + Math.max(60, found.contentHeight) + 84)
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.playlists.findTitle
        Keys.onEscapePressed: dialog.playlists.closeFind()

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: title
            objectName: "findTitle"
            x: dialog.pad
            y: 24
            width: close.x - x - 16
            elide: Text.ElideRight
            text: dialog.playlists.findTitle
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Item {
            id: close
            objectName: "closeFind"
            x: parent.width - 56
            y: 22
            width: 32
            height: 32
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Close %1").arg(dialog.playlists.findTitle)
            Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: dialog.playlists.closeFind() }
        }
        Text {
            id: about
            objectName: "findAbout"
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 6
            width: parent.width - 2 * dialog.pad
            wrapMode: Text.Wrap
            text: dialog.playlists.findAbout
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 13 }
        }
        Text {
            id: said
            objectName: "findText"
            x: dialog.pad
            anchors.top: about.bottom
            anchors.topMargin: 14
            width: parent.width - 2 * dialog.pad
            wrapMode: Text.Wrap
            text: dialog.playlists.findText
            color: Theme.cell
            font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
        }
        ListView {
            id: found
            objectName: "findRows"
            x: dialog.pad
            anchors.top: said.bottom
            anchors.topMargin: 12
            anchors.bottom: foot.top
            anchors.bottomMargin: 12
            width: parent.width - 2 * dialog.pad
            clip: true
            spacing: 6
            boundsBehavior: Flickable.StopAtBounds
            model: dialog.playlists.findRows
            delegate: Rectangle {
                id: offer
                required property var modelData
                required property int index
                width: found.width
                height: 54
                radius: 10
                color: Theme.surface
                border.color: Theme.border
                Accessible.role: Accessible.ListItem
                Accessible.name: offer.modelData.title + ", " + offer.modelData.path
                Column {
                    x: 14
                    width: use.x - 14 - x
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text {
                        width: parent.width
                        elide: Text.ElideRight
                        text: offer.modelData.artist ? offer.modelData.title + " · " + offer.modelData.artist : offer.modelData.title
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 14 }
                    }
                    Text {
                        width: parent.width
                        elide: Text.ElideMiddle
                        text: [offer.modelData.why, offer.modelData.time, offer.modelData.path].filter((t) => t !== "").join(" · ")
                        color: Theme.muted
                        font { family: Theme.sans; pixelSize: 12 }
                    }
                }
                Btn {
                    id: use
                    objectName: "useFound"
                    x: parent.width - width - 10
                    anchors.verticalCenter: parent.verticalCenter
                    height: 34
                    label: qsTr("Use this")
                    onClicked: dialog.playlists.choose(offer.index)
                }
            }
        }
        Item {
            id: foot
            width: parent.width
            height: 64
            anchors.bottom: parent.bottom
            Btn {
                objectName: "cancelFind"
                anchors.right: parent.right
                anchors.rightMargin: dialog.pad
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 110
                height: 40
                label: qsTr("Cancel")
                onClicked: dialog.playlists.closeFind()
            }
        }
    }
}
