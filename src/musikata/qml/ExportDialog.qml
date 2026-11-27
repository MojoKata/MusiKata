import QtQuick
import QtQuick.Dialogs
import "."

// Export… (R8.8), from a playlist's page: over the window, "Export Road Trip"; the two ways, a
// playlist naming the songs where they are (absolute paths) or the songs copied, numbered, beside a
// playlist naming them (a car's USB stick, a phone); the folder, chosen in the platform's dialog;
// then Export, the songs copied off the GUI thread with the progress shown, and Cancel, which stops
// the copying or closes the dialog. Esc cancels too. What it says and does is musikata.playlists'.
Item {
    id: dialog
    required property var playlists
    readonly property real pad: 28
    visible: dialog.playlists.exportOpen
    onVisibleChanged: if (visible) card.forceActiveFocus()

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        TapHandler { }
        WheelHandler { }
    }
    FocusScope {
        id: card
        objectName: "exportDialog"
        width: Math.min(parent.width - 96, 640)
        height: where.y + where.height + 24 + foot.height
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.playlists.exportTitle
        Keys.onEscapePressed: dialog.playlists.cancelExport()

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: title
            objectName: "exportTitle"
            x: dialog.pad
            y: 24
            width: parent.width - 2 * dialog.pad
            elide: Text.ElideRight
            text: dialog.playlists.exportTitle
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Column {
            id: ways
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 18
            width: parent.width - 2 * dialog.pad
            spacing: 10
            Repeater {
                model: dialog.playlists.exportModes
                Rectangle {
                    id: way
                    required property var modelData
                    objectName: "exportMode-" + modelData.mode
                    width: ways.width
                    height: wayText.height + 24
                    radius: 10
                    color: way.modelData.chosen ? Theme.accentSoft : Theme.surface
                    border.color: way.modelData.chosen ? Theme.accent : Theme.border
                    Accessible.role: Accessible.RadioButton
                    Accessible.name: way.modelData.label
                    Accessible.checked: way.modelData.chosen
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: dialog.playlists.setExportMode(way.modelData.mode) }
                    Rectangle {
                        x: 14
                        y: 14
                        width: 16
                        height: 16
                        radius: 8
                        color: "transparent"
                        border.color: way.modelData.chosen ? Theme.accent : Theme.borderStrong
                        border.width: 1.5
                        Rectangle {
                            anchors.centerIn: parent
                            width: 8
                            height: 8
                            radius: 4
                            color: Theme.accent
                            visible: way.modelData.chosen
                        }
                    }
                    Column {
                        id: wayText
                        x: 42
                        y: 12
                        width: way.width - x - 14
                        spacing: 3
                        Text {
                            width: parent.width
                            wrapMode: Text.Wrap
                            text: way.modelData.label
                            color: Theme.text
                            font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                        }
                        Text {
                            width: parent.width
                            wrapMode: Text.Wrap
                            text: way.modelData.detail
                            color: Theme.muted
                            font { family: Theme.sans; pixelSize: 12 }
                        }
                    }
                }
            }
        }
        Item {
            id: where
            x: dialog.pad
            anchors.top: ways.bottom
            anchors.topMargin: 16
            width: parent.width - 2 * dialog.pad
            height: 40
            Text {
                objectName: "exportFolder"
                width: choose.x - 12
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideMiddle
                text: dialog.playlists.exportFolder || qsTr("No folder chosen yet")
                color: dialog.playlists.exportFolder ? Theme.text : Theme.faint
                font { family: Theme.sans; pixelSize: 13 }
            }
            Btn {
                id: choose
                objectName: "exportChoose"
                x: parent.width - width
                height: 36
                anchors.verticalCenter: parent.verticalCenter
                label: qsTr("Choose folder…")
                icon: "folder"
                later: dialog.playlists.exporting ? qsTr("Export is going on") : ""
                onClicked: pick.open()
            }
        }
        Item {
            id: foot
            width: parent.width
            height: 76
            anchors.bottom: parent.bottom
            Rectangle {  // the copying's progress
                x: dialog.pad
                y: 0
                width: parent.width - 2 * dialog.pad
                height: 4
                radius: 2
                color: Theme.border
                visible: dialog.playlists.exporting
                Rectangle {
                    width: parent.width * dialog.playlists.exportProgress
                    height: parent.height
                    radius: 2
                    color: Theme.accent
                }
            }
            Text {
                objectName: "exportText"
                x: dialog.pad
                width: buttons.x - x - 16
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                text: dialog.playlists.exportText
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13 }
            }
            Row {
                id: buttons
                x: parent.width - width - dialog.pad
                anchors.verticalCenter: parent.verticalCenter
                spacing: 12
                Btn {
                    objectName: "cancelExport"
                    minWidth: 110
                    height: 40
                    label: qsTr("Cancel")
                    onClicked: dialog.playlists.cancelExport()
                }
                Btn {
                    objectName: "doExport"
                    minWidth: 120
                    height: 40
                    primary: true
                    label: qsTr("Export")
                    later: dialog.playlists.exporting ? qsTr("Export is going on") : dialog.playlists.exportLater
                    onClicked: dialog.playlists.export()
                }
            }
        }
    }
    FolderDialog {
        id: pick
        title: qsTr("Export to a folder")
        onAccepted: dialog.playlists.setExportFolder(selectedFolder.toString())
    }
}
