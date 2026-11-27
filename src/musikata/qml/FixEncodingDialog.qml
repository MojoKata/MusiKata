import QtQuick
import "."

// Fix encoding… (R4.10, T06-fix-encoding), from Needs attention or the Edit tags panel's ⋯ menu, as a
// dialog over the window: the song's file in its title, what happened to its tags; a row per way
// to read them, the most likely first, each with a radio button, its name and the tags as it reads
// them, or that it can't read them; the checkbox that makes the choice every song's of the album,
// and the files it writes (R3.7's preview, PreviewTable) in the readings' place when asked for;
// the footer saying what is written and that Undo puts the old bytes back, Cancel and Save N files
// (R3.8), which while the save goes on says how far it has come. Esc, the × or Cancel closes it,
// saving nothing. What it shows and does is musikata.encodings'.
Item {
    id: dialog
    required property var fix
    readonly property real pad: 28
    readonly property bool loading: dialog.fix.loading  // the tour waits for the songs
    visible: dialog.fix.opened
    onVisibleChanged: if (visible) card.forceActiveFocus()

    Rectangle {  // the scrim: the window behind, dimmed and out of reach
        anchors.fill: parent
        color: Theme.scrim
        TapHandler { }
        WheelHandler { }
    }
    FocusScope {
        id: card
        objectName: "fixEncodingDialog"
        width: Math.min(parent.width - 96, 980)
        height: Math.min(parent.height - 80, about.y + about.height + 22 + body.height + 20 + whole.height + 22 + foot.height)
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.fix.title
        Keys.onEscapePressed: dialog.fix.close()

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: title
            objectName: "fixTitle"
            x: dialog.pad
            y: 26
            width: close.x - x - 16
            elide: Text.ElideMiddle
            text: dialog.fix.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Item {
            id: close
            objectName: "closeFix"
            x: parent.width - 56
            y: 22
            width: 32
            height: 32
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Close %1").arg(dialog.fix.title)
            Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: dialog.fix.close() }
        }
        Text {
            id: about
            objectName: "fixAbout"
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 6
            width: parent.width - 2 * dialog.pad
            wrapMode: Text.WordWrap
            text: dialog.fix.about
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }

        Item {  // the readings, or the files the choice writes
            id: body
            x: dialog.pad
            anchors.top: about.bottom
            anchors.topMargin: 22
            width: parent.width - 2 * dialog.pad
            height: dialog.fix.showFiles ? 320 : heads.height + 4 + dialog.fix.readings.length * 52
            readonly property real labelWidth: Math.round(width * 0.31)
            readonly property real cellWidth: (width - labelWidth - 16) / Math.max(1, dialog.fix.columns.length)

            Item {  // the heads of the columns: READ AS, then each tag read
                id: heads
                visible: !dialog.fix.showFiles
                width: parent.width
                height: 26
                Text {
                    x: 44
                    width: body.labelWidth - 52
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("READ AS")
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.4 }
                }
                Repeater {
                    model: dialog.fix.columns
                    Text {
                        required property var modelData
                        required property int index
                        x: body.labelWidth + index * body.cellWidth
                        width: body.cellWidth - 12
                        height: heads.height
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                        text: modelData.label.toUpperCase()
                        color: Theme.muted
                        font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.4 }
                    }
                }
            }
            Column {
                id: readings
                objectName: "fixReadings"
                visible: !dialog.fix.showFiles
                y: heads.height + 4
                width: parent.width
                spacing: 8
                Repeater {
                    model: dialog.fix.readings
                    Rectangle {
                        id: reading
                        required property var modelData
                        required property int index
                        objectName: "fixReading"
                        width: readings.width
                        height: 44
                        radius: 9
                        color: reading.modelData.chosen ? Theme.accentSoft : Theme.raised
                        border.color: reading.modelData.chosen ? Theme.accent : Theme.border
                        border.width: reading.modelData.chosen ? 1.5 : 1
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: reading.modelData.label
                        Accessible.checked: reading.modelData.chosen
                        Item {  // the radio button
                            x: 14
                            anchors.verticalCenter: parent.verticalCenter
                            width: 22
                            height: 22
                            opacity: reading.modelData.readable ? 1 : 0.5
                            Rectangle {
                                anchors.fill: parent
                                radius: 11
                                color: "transparent"
                                border.width: 2
                                border.color: reading.modelData.chosen ? Theme.accent : Theme.borderStrong
                            }
                            Rectangle {
                                anchors.centerIn: parent
                                width: 10
                                height: 10
                                radius: 5
                                color: Theme.accent
                                visible: reading.modelData.chosen
                            }
                        }
                        Column {
                            x: 44
                            width: body.labelWidth - 52
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                width: parent.width
                                elide: Text.ElideRight
                                text: reading.modelData.label
                                color: Theme.text
                                font { family: Theme.sans; pixelSize: 14; weight: reading.modelData.chosen ? Font.DemiBold : Font.Normal }
                            }
                            Text {
                                objectName: "fixLikely"
                                width: parent.width
                                visible: text !== ""
                                elide: Text.ElideRight
                                text: reading.modelData.badge
                                color: Theme.ok
                                font { family: Theme.sans; pixelSize: 12; weight: Font.DemiBold }
                            }
                        }
                        Repeater {
                            model: reading.modelData.texts
                            Text {
                                required property var modelData
                                required property int index
                                x: body.labelWidth + index * body.cellWidth
                                width: body.cellWidth - 12
                                anchors.verticalCenter: parent.verticalCenter
                                elide: Text.ElideRight
                                text: modelData
                                color: reading.modelData.chosen ? Theme.text : Theme.muted
                                font { family: Theme.sans; pixelSize: 14; weight: reading.modelData.chosen ? Font.DemiBold : Font.Normal }
                            }
                        }
                        Text {
                            x: body.labelWidth
                            width: parent.width - x - 16
                            anchors.verticalCenter: parent.verticalCenter
                            visible: !reading.modelData.readable
                            elide: Text.ElideRight
                            text: reading.modelData.note
                            color: Theme.faint
                            font { family: Theme.sans; pixelSize: 13 }
                        }
                        HoverHandler { cursorShape: reading.modelData.readable ? Qt.PointingHandCursor : Qt.ArrowCursor }
                        TapHandler { onTapped: dialog.fix.choose(reading.index) }
                    }
                }
            }
            PreviewTable {
                objectName: "fixPreview"
                visible: dialog.fix.showFiles
                anchors.fill: parent
                preview: dialog.fix.preview
            }
        }

        Item {  // the same for every song of the album, and the files the choice writes
            id: whole
            x: dialog.pad
            anchors.top: body.bottom
            anchors.topMargin: 20
            width: parent.width - 2 * dialog.pad
            height: 34
            Row {
                anchors.verticalCenter: parent.verticalCenter
                width: files.x - 16
                spacing: 10
                visible: dialog.fix.wholeText !== ""
                Check {
                    objectName: "fixWhole"
                    anchors.verticalCenter: parent.verticalCenter
                    mark: dialog.fix.whole ? "all" : "none"
                    Accessible.name: dialog.fix.wholeText
                    onToggled: dialog.fix.toggleWhole()
                }
                Text {
                    width: parent.width - 30
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: dialog.fix.wholeText
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 14 }
                    TapHandler { onTapped: dialog.fix.toggleWhole() }
                }
            }
            Btn {
                id: files
                objectName: "fixFiles"
                x: parent.width - width
                anchors.verticalCenter: parent.verticalCenter
                quiet: true
                height: 32
                label: dialog.fix.showFiles ? qsTr("Show the readings") : qsTr("Show the files")
                onClicked: dialog.fix.toggleFiles()
            }
        }

        Rectangle { y: foot.y - 1; width: parent.width; height: 1; color: Theme.border }
        Item {  // R3.8: what is written, Cancel and Save N files
            id: foot
            x: dialog.pad
            y: parent.height - height
            width: parent.width - 2 * dialog.pad
            height: 76
            Text {
                objectName: "fixProblem"
                width: cancel.x - 16
                y: 6
                visible: text !== ""
                elide: Text.ElideRight
                text: dialog.fix.problem
                color: Theme.err
                font { family: Theme.sans; pixelSize: 13 }
            }
            Text {
                objectName: "fixFooter"
                width: cancel.x - 16
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: dialog.fix.problem !== "" ? 10 : 0
                elide: Text.ElideRight
                text: dialog.fix.footer
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 14 }
            }
            Btn {
                id: cancel
                objectName: "cancelFix"
                x: save.x - width - 12
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 120
                label: qsTr("Cancel")
                height: 40
                onClicked: dialog.fix.close()
            }
            Btn {
                id: save
                objectName: "saveFix"
                x: parent.width - width
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 160
                label: dialog.fix.saveLabel
                icon: "check"
                primary: true
                height: 40
                later: dialog.fix.saveLater
                onClicked: dialog.fix.save()
            }
        }
    }
}
