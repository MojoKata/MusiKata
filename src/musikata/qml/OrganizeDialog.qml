import QtQuick
import QtQuick.Controls.Basic
import "."

// Organize files (R12, T03-organize-files), as a dialog over the window: its title and what it
// does; the layout under the root (R12.1); every move, each with its checkbox, the old path dimmed
// above "→ the new one", a conflict or a file that stays said under it in amber (R12.4); under the
// list "+ 10 more moves · 2 empty folders will be removed" (R12.3) and what isn't moved and why;
// the playlists that will be updated, in amber (R12.4); and the footer with the total and the
// conflicts, Cancel and Move N files, which while the moves go on says how far they have come.
// Brought from outside the root (R12.5) it is Add to your library: Copy or Move into the library,
// and Infer from path for the files whose tags are missing. Esc, the × or Cancel closes it, moving
// nothing. What it shows and does is musikata.organize's.
Item {
    id: dialog
    required property var organize
    readonly property real pad: 32
    readonly property bool loading: dialog.organize.loading  // the tour waits for the songs
    visible: dialog.organize.opened
    onVisibleChanged: if (visible) card.forceActiveFocus()

    component Radio: Item {  // R12.5's two ways
        id: radio
        signal clicked()
        property string label
        property bool chosen
        width: radioRow.width
        height: 30
        Accessible.role: Accessible.RadioButton
        Accessible.name: radio.label
        Accessible.checked: radio.chosen
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: radio.clicked() }
        Row {
            id: radioRow
            anchors.verticalCenter: parent.verticalCenter
            spacing: 10
            Item {
                anchors.verticalCenter: parent.verticalCenter
                width: 22
                height: 22
                Rectangle {
                    anchors.fill: parent
                    radius: 11
                    color: "transparent"
                    border.width: 2
                    border.color: radio.chosen ? Theme.accent : Theme.borderStrong
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: 10
                    height: 10
                    radius: 5
                    color: Theme.accent
                    visible: radio.chosen
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: radio.label
                color: Theme.text
                font { family: Theme.sans; pixelSize: 14; weight: radio.chosen ? Font.DemiBold : Font.Normal }
            }
        }
    }

    Rectangle {  // the scrim: the window behind, dimmed and out of reach
        anchors.fill: parent
        color: Theme.scrim
        TapHandler { }
        WheelHandler { }
    }
    FocusScope {
        id: card
        objectName: "organizeDialog"
        width: Math.min(parent.width - 96, 1000)  // T03's size at 1280 × 800
        height: Math.min(parent.height - 80, 640)
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.organize.title
        Keys.onEscapePressed: dialog.organize.close()

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: title
            objectName: "organizeTitle"
            x: dialog.pad
            y: 26
            width: close.x - x - 12
            elide: Text.ElideRight
            text: dialog.organize.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Item {
            id: close
            objectName: "closeOrganize"
            x: parent.width - 56
            y: 22
            width: 32
            height: 32
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Close %1").arg(dialog.organize.title)
            Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: dialog.organize.close() }
        }
        Text {
            id: about
            objectName: "organizeAbout"
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 6
            width: parent.width - 2 * dialog.pad
            wrapMode: Text.WordWrap
            text: dialog.organize.about
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }

        Column {  // the layout (R12.1); brought from outside, the two ways and Infer from path
            id: options
            x: dialog.pad
            anchors.top: about.bottom
            anchors.topMargin: 20
            width: parent.width - 2 * dialog.pad
            spacing: 10

            Text {
                text: dialog.organize.layoutLabel
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
            }
            Rectangle {
                objectName: "organizeLayout"
                width: parent.width
                height: 48
                radius: 10
                color: Theme.input
                border.color: Theme.border
                Accessible.role: Accessible.StaticText
                Accessible.name: qsTr("Layout: %1").arg(dialog.organize.layout)
                Text {
                    x: 16
                    width: parent.width - 32
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: dialog.organize.layout
                    color: Theme.text
                    font { family: Theme.mono; pixelSize: 15 }
                }
            }
            Row {
                visible: dialog.organize.adding
                spacing: 24
                Repeater {
                    model: dialog.organize.ways
                    Radio {
                        required property var modelData
                        objectName: "way_" + modelData.name
                        label: modelData.label
                        chosen: modelData.chosen
                        onClicked: dialog.organize.setWay(modelData.name)
                    }
                }
            }
            Row {
                visible: dialog.organize.inferLabel !== ""
                spacing: 10
                Check {
                    objectName: "organizeInfer"
                    anchors.verticalCenter: parent.verticalCenter
                    mark: dialog.organize.inferOn ? "all" : "none"
                    Accessible.name: dialog.organize.inferLabel
                    onToggled: dialog.organize.toggleInfer()
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: dialog.organize.inferLabel
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 14 }
                }
            }
        }

        Rectangle {  // every move (R12.2), the line under them
            id: box
            objectName: "organizeMoves"
            x: dialog.pad
            anchors.top: options.bottom
            anchors.topMargin: 18
            anchors.bottom: banner.visible ? banner.top : foot.top
            anchors.bottomMargin: 18
            width: parent.width - 2 * dialog.pad
            radius: 12
            color: Theme.input
            border.color: Theme.border

            ListView {
                id: list
                objectName: "organizeList"
                x: 4
                y: 10
                width: parent.width - 8
                // whole rows only, above the line under them
                height: Math.max(48, Math.floor((parent.height - 10 - tail.height - 24) / 48) * 48)
                clip: true
                model: dialog.organize.moves
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { }
                // how many rows show without scrolling, for "+ N more moves" (T03)
                readonly property int fits: Math.floor(height / 48)
                onFitsChanged: Qt.callLater(dialog.organize.setShown, fits)
                Component.onCompleted: Qt.callLater(dialog.organize.setShown, fits)
                delegate: Item {
                    id: row
                    required property int index
                    required property string old
                    required property string target
                    required property bool checked
                    required property bool moving
                    required property string note
                    width: ListView.view.width
                    height: 48
                    Check {
                        objectName: "organizeCheck"
                        x: 16
                        anchors.verticalCenter: parent.verticalCenter
                        mark: row.checked ? "all" : "none"
                        Accessible.name: qsTr("Move %1").arg(row.old)
                        onToggled: dialog.organize.toggle(row.index)
                    }
                    Text {
                        id: oldPath
                        x: 54
                        y: 2
                        width: parent.width - x - 16 - (note.visible ? note.width + 16 : 0)
                        elide: Text.ElideMiddle
                        text: row.old
                        color: Theme.muted
                        font { family: Theme.mono; pixelSize: 13 }
                    }
                    Text {  // a conflict, or a file that stays (R12.4, R12.3)
                        id: note
                        x: parent.width - width - 16
                        y: 2
                        width: Math.min(implicitWidth, parent.width / 3)
                        visible: row.note !== ""
                        elide: Text.ElideRight
                        text: row.note
                        color: Theme.warn
                        font { family: Theme.sans; pixelSize: 12 }
                    }
                    Text {
                        x: 54
                        y: 24
                        width: parent.width - x - 16
                        elide: Text.ElideMiddle
                        text: "→  " + row.target
                        color: row.moving ? Theme.text : Theme.faint
                        font { family: Theme.mono; pixelSize: 13 }
                    }
                }
            }
            Column {
                id: tail
                x: 20
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 14
                width: parent.width - 40
                spacing: 4
                Text {
                    objectName: "organizeMore"
                    width: parent.width
                    visible: text !== ""
                    elide: Text.ElideRight
                    text: dialog.organize.more
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Text {
                    objectName: "organizeNotes"
                    width: parent.width
                    visible: text !== ""
                    elide: Text.ElideRight
                    text: dialog.organize.notes
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 13 }
                }
            }
        }

        Rectangle {  // the playlists updated with the moves (R12.4)
            id: banner
            objectName: "organizePlaylists"
            x: dialog.pad
            anchors.bottom: foot.top
            anchors.bottomMargin: 20
            width: parent.width - 2 * dialog.pad
            height: visible ? 44 : 0
            radius: 8
            visible: dialog.organize.playlists !== ""
            color: Theme.warnSoft
            Accessible.role: Accessible.StaticText
            Accessible.name: bannerText.text
            Icon { x: 16; anchors.verticalCenter: parent.verticalCenter; name: "attention"; size: 18; color: Theme.warn }
            Text {
                id: bannerText
                x: 48
                width: parent.width - x - 16
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: dialog.organize.playlists
                color: Theme.warn
                font { family: Theme.sans; pixelSize: 14 }
            }
        }

        Rectangle { y: foot.y - 1; width: parent.width; height: 1; color: Theme.border }
        Item {  // the total and the conflicts (R12.2, R12.4), Cancel and Move N files
            id: foot
            x: dialog.pad
            y: parent.height - height
            width: parent.width - 2 * dialog.pad
            height: 92
            Text {
                objectName: "organizeFooter"
                width: cancel.x - 16
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: dialog.organize.footer
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 14 }
            }
            Btn {
                id: cancel
                objectName: "cancelOrganize"
                x: action.x - width - 12
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 120
                label: qsTr("Cancel")
                height: 40
                onClicked: dialog.organize.close()
            }
            Btn {
                id: action
                objectName: "runOrganize"
                x: parent.width - width
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 200
                label: dialog.organize.actionLabel
                icon: "arrow"
                primary: true
                height: 40
                later: dialog.organize.actionLater
                onClicked: dialog.organize.run()
            }
        }
    }
}
