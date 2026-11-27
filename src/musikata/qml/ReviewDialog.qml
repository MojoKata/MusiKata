import QtQuick
import "."

// Review… (R2.12, from Needs attention's group of copies, L09-needs-attention): the group's copies
// in a dialog over the window, drawn after T01-infer-from-path's: its title, Exact copies or
// Likely and what that means; a row per copy with the copy kept (a radio button) and those checked
// for the trash, each with its format, path, details, plays and rating (CopyRow); the footer saying
// what goes and that Undo can't take files out of the trash (R2.11), Cancel, and Move N to the
// trash, which asks first (CopiesQuestion). Esc, the × or Cancel closes it, moving nothing. What it
// shows and does is musikata.duplicates'.
Item {
    id: dialog
    required property var copies
    readonly property real pad: 32
    visible: dialog.copies.opened
    onVisibleChanged: if (visible) card.forceActiveFocus()

    Rectangle {  // the scrim: the window behind, dimmed and out of reach
        anchors.fill: parent
        color: Theme.scrim
        TapHandler { }
        WheelHandler { }
    }
    FocusScope {
        id: card
        objectName: "reviewDialog"
        width: Math.min(parent.width - 96, 1180)
        height: Math.min(parent.height - 80, about.y + about.height + 20 + heads.height + 5
                         + table.contentHeight + 20 + foot.height)
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.copies.title
        Keys.onEscapePressed: dialog.copies.close()

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: title
            objectName: "reviewTitle"
            x: dialog.pad
            y: 26
            width: Math.min(implicitWidth, close.x - x - 24 - badge.width)
            elide: Text.ElideRight
            text: dialog.copies.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Chip {
            id: badge
            x: title.x + title.width + 14
            y: 29
            label: dialog.copies.badge
            tone: dialog.copies.likely ? "warn" : "ok"
        }
        Item {
            id: close
            objectName: "closeReview"
            x: parent.width - 56
            y: 22
            width: 32
            height: 32
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Close %1").arg(dialog.copies.title)
            Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: dialog.copies.close() }
        }
        Text {
            id: about
            objectName: "reviewAbout"
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 6
            width: parent.width - 2 * dialog.pad
            wrapMode: Text.WordWrap
            text: dialog.copies.about
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }

        Rectangle {  // the copies, as T01's preview lists the files
            id: frame
            x: dialog.pad
            anchors.top: about.bottom
            anchors.topMargin: 20
            anchors.bottom: foot.top
            anchors.bottomMargin: 20
            width: parent.width - 2 * dialog.pad
            radius: 12
            color: Theme.surface
            border.color: Theme.border
            Item {  // the heads of the columns
                id: heads
                x: 14
                width: parent.width - 28
                height: 44
                readonly property real tail: width - 360
                Repeater {
                    model: [
                        { x: 8, w: 180, text: qsTr("KEEP OR TRASH") },
                        { x: 196, w: 148, text: qsTr("FORMAT") },
                        { x: 356, w: heads.tail - 372, text: qsTr("FILE") },
                        { x: heads.tail, w: 64, text: qsTr("PLAYS"), right: true },
                        { x: heads.tail + 76, w: 72, text: qsTr("RATING") }
                    ]
                    Text {
                        required property var modelData
                        x: modelData.x
                        width: modelData.w
                        height: heads.height
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                        elide: Text.ElideRight
                        text: modelData.text
                        color: Theme.muted
                        font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.4 }
                    }
                }
            }
            Rectangle { x: 1; y: heads.height; width: parent.width - 2; height: 1; color: Theme.border }
            ListView {
                id: table
                objectName: "reviewCopies"
                x: 14
                y: heads.height + 1
                width: parent.width - 28
                height: parent.height - y - 4
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: dialog.copies.rows
                delegate: CopyRow {
                    required property var modelData
                    width: table.width
                    copy: modelData
                    detailed: true
                    onKeep: dialog.copies.keep(modelData.song)
                    onToggle: dialog.copies.toggle(modelData.song)
                }
            }
        }

        Rectangle { y: foot.y - 1; width: parent.width; height: 1; color: Theme.border }
        Item {  // what goes, Cancel and Move N to the trash
            id: foot
            x: dialog.pad
            y: parent.height - height
            width: parent.width - 2 * dialog.pad
            height: 76
            Text {
                objectName: "reviewFooter"
                width: cancel.x - 16
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: dialog.copies.footer
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 14 }
            }
            Btn {
                id: cancel
                objectName: "cancelReview"
                x: move.x - width - 12
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 120
                label: qsTr("Cancel")
                height: 40
                onClicked: dialog.copies.close()
            }
            Btn {
                id: move
                objectName: "moveCopies"
                x: parent.width - width
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 180
                label: dialog.copies.moveLabel
                primary: true
                height: 40
                later: dialog.copies.moveLater
                onClicked: dialog.copies.move()
            }
        }
    }
}
