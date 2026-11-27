import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import "."

// The Album art dialog (R5.2, R5.3; T02-album-art), over the window: the album's name and what the
// dialog does; the current cover large, its size, kind and file size, and where it is ("Embedded in
// 10 of 10"); beside it every cover found, each with its thumbnail, where it is, its size and a note,
// one chosen with its radio button; the drop zone, which takes an image dropped anywhere on the
// dialog, with Choose file… (the platform's file dialog) and Find online… (R16.4, a later version);
// Ctrl+V / ⌘V pastes (R5.2.1); why an image dropped, pasted or chosen can't be used; R5.3's four
// checkboxes; and the footer saying what saving will change, or "No change", with Save N files or
// Done. While it saves, the footer shows the progress of more than a few files and Cancel; files
// that failed are listed with why and Retry (R4.7). Esc or the × closes it. What it shows and does
// is the dialog's (musikata.albumart).
Item {
    id: dialog
    required property var art
    readonly property bool loading: dialog.art.loading  // the tour waits while the art is read
    readonly property real pad: 28
    visible: dialog.art.opened
    onVisibleChanged: if (visible) card.forceActiveFocus()

    component Option: Row {  // one of R5.3's checkboxes
        id: option
        required property string name
        required property string label
        required property bool on
        spacing: 10
        Check {
            objectName: "artOption-" + option.name
            anchors.verticalCenter: parent.verticalCenter
            width: 18
            height: 18
            mark: option.on ? "all" : "none"
            Accessible.name: option.label
            onToggled: dialog.art.setOption(option.name, !option.on)
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: option.label
            color: option.on ? Theme.text : Theme.cell
            font { family: Theme.sans; pixelSize: 14 }
            TapHandler { onTapped: dialog.art.setOption(option.name, !option.on) }
        }
    }

    Rectangle {  // the scrim: the window behind, dimmed and out of reach
        anchors.fill: parent
        color: Theme.scrim
        MouseArea {  // takes every click and turn of the wheel, so none reaches the window
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onWheel: (wheel) => { wheel.accepted = true }
        }
    }
    FocusScope {
        id: card
        objectName: "artDialog"
        width: Math.min(parent.width - 64, 900)
        height: Math.min(parent.height - 48, 590)
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.art.title
        Keys.onEscapePressed: dialog.art.close()
        Shortcut {
            sequences: [StandardKey.Paste]
            enabled: dialog.visible
            onActivated: dialog.art.paste()
        }

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.surface
            border.color: drop.containsDrag ? Theme.accent : Theme.borderStrong
            MouseArea {  // a click on the card that nothing on it takes stops here, too
                anchors.fill: parent
                acceptedButtons: Qt.AllButtons
                onWheel: (wheel) => { wheel.accepted = true }
            }
        }
        DropArea {  // an image dropped anywhere on the dialog (R5.2.1)
            id: drop
            anchors.fill: parent
            onDropped: (event) => {
                if (event.hasUrls)
                    dialog.art.addUrls(event.urls)
            }
        }
        Text {
            id: title
            objectName: "artTitle"
            x: dialog.pad
            y: 24
            width: close.x - x - 12
            elide: Text.ElideRight
            text: dialog.art.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Item {
            id: close
            objectName: "closeArt"
            x: parent.width - 52
            y: 22
            width: 32
            height: 32
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Close %1").arg(dialog.art.title)
            Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: dialog.art.close() }
        }
        Text {
            id: about
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 4
            width: parent.width - 2 * dialog.pad
            elide: Text.ElideRight
            text: dialog.art.about
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }

        // the current cover (R5.2), large, with what it is and where
        Cover {
            id: current
            objectName: "artCurrent"
            x: dialog.pad
            y: 92
            width: Math.min(250, card.width * 0.3)
            height: width
            radius: 12
            matte: Theme.surface
            sourceSide: 512
            source: dialog.art.current.source || ""
        }
        Text {
            id: currentLine
            objectName: "artCurrentLine"
            x: dialog.pad
            anchors.top: current.bottom
            anchors.topMargin: 12
            width: current.width
            elide: Text.ElideRight
            text: dialog.art.current.line || ""
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 13 }
        }
        Chip {
            objectName: "artWhere"
            x: dialog.pad
            anchors.top: currentLine.bottom
            anchors.topMargin: 10
            visible: label !== ""
            label: dialog.art.current.where || ""
            tone: dialog.art.current.tone || "warn"
        }

        // the covers found (R5.2), the drop zone and what an image added couldn't be
        Item {
            id: found
            x: current.x + current.width + 30
            y: 92
            width: card.width - x - dialog.pad
            height: options.y - y - 16
            Text {
                id: foundLabel
                text: qsTr("FOUND")
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.4 }
            }
            Text {  // while the album's art is read
                id: looking
                anchors.top: foundLabel.bottom
                anchors.topMargin: 12
                visible: dialog.art.loading
                text: qsTr("Looking for covers…")
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 14 }
            }
            ListView {
                id: candidates
                objectName: "artCandidates"
                anchors.top: foundLabel.bottom
                anchors.topMargin: 10
                width: parent.width
                height: Math.min(contentHeight, zone.y - y - 10)
                clip: true
                spacing: 10
                boundsBehavior: Flickable.StopAtBounds
                model: dialog.art.candidates
                ScrollBar.vertical: ScrollBar { }
                delegate: Rectangle {
                    id: row
                    required property var modelData
                    objectName: "artCandidate"
                    width: ListView.view.width
                    height: 68
                    radius: 10
                    color: modelData.chosen ? Theme.accentSoft : (rowHover.hovered && modelData.usable ? Theme.hover : Theme.raised)
                    border.color: modelData.chosen ? Theme.accent : Theme.border
                    border.width: modelData.chosen ? 1.5 : 1
                    opacity: modelData.usable ? 1 : 0.6
                    Accessible.role: Accessible.RadioButton
                    Accessible.name: modelData.title
                    Accessible.description: modelData.detail
                    Accessible.checked: modelData.chosen
                    HoverHandler { id: rowHover; cursorShape: row.modelData.usable ? Qt.PointingHandCursor : Qt.ArrowCursor }
                    TapHandler { enabled: row.modelData.usable; onTapped: dialog.art.choose(row.modelData.key) }
                    Cover {
                        x: 10
                        y: 9
                        width: 50
                        height: 50
                        radius: 6
                        matte: row.color
                        sourceSide: 112
                        emptyText: ""
                        source: row.modelData.usable ? row.modelData.source : ""
                    }
                    Text {
                        x: 74
                        y: 12
                        width: radio.x - x - 12
                        elide: Text.ElideRight
                        text: row.modelData.title
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 15; weight: Font.DemiBold }
                    }
                    Text {
                        x: 74
                        y: 36
                        width: radio.x - x - 12
                        elide: Text.ElideRight
                        text: row.modelData.detail
                        color: row.modelData.usable ? Theme.muted : Theme.err
                        font { family: Theme.sans; pixelSize: 13 }
                    }
                    Rectangle {  // its radio button
                        id: radio
                        x: row.width - 34
                        anchors.verticalCenter: parent.verticalCenter
                        width: 18
                        height: 18
                        radius: 9
                        color: "transparent"
                        border.color: row.modelData.chosen ? Theme.accent : Theme.borderStrong
                        border.width: 1.6
                        Rectangle {
                            anchors.centerIn: parent
                            width: 9
                            height: 9
                            radius: 4.5
                            color: Theme.accent
                            visible: row.modelData.chosen
                        }
                    }
                }
            }

            Rectangle {  // the drop zone (R5.2.1)
                id: zone
                objectName: "artDropZone"
                y: Math.min(Math.max(candidates.y + candidates.contentHeight, looking.visible ? looking.y + looking.height : 0) + 14,
                            parent.height - height - (problem.visible ? 26 : 0))
                width: parent.width
                height: 68
                radius: 10
                visible: (dialog.art.failed.title || "") === ""
                color: drop.containsDrag ? Theme.accentSoft : Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.05)
                border.color: drop.containsDrag ? Theme.accent : Theme.borderStrong
                border.width: 1.2
                Accessible.role: Accessible.Grouping
                Accessible.name: qsTr("Drop an image here, paste it, or choose a file")
                Icon { x: 18; anchors.verticalCenter: parent.verticalCenter; name: "image"; size: 22; color: Theme.muted }
                Text {
                    x: 54
                    y: 12
                    width: parent.width - x - 12
                    elide: Text.ElideRight
                    text: qsTr("Drop an image here, paste it, or")
                    color: Theme.cell
                    font { family: Theme.sans; pixelSize: 14 }
                }
                Row {
                    x: 54
                    y: 34
                    spacing: 6
                    Text {
                        id: chooseFile
                        objectName: "chooseFile"
                        text: qsTr("Choose file…")
                        color: Theme.accentHi
                        font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                        Accessible.role: Accessible.Button
                        Accessible.name: text
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: files.open() }
                    }
                    Text {
                        text: qsTr("or")
                        color: Theme.cell
                        font { family: Theme.sans; pixelSize: 14 }
                    }
                    Row {  // R16.4: a later version's
                        id: online
                        objectName: "findOnline"
                        spacing: 5
                        opacity: 0.45
                        Accessible.role: Accessible.Button
                        Accessible.name: qsTr("Find online…")
                        Accessible.description: dialog.art.onlineNote
                        Icon { anchors.verticalCenter: parent.verticalCenter; name: "globe"; size: 14; color: Theme.accentHi }
                        Text {
                            text: qsTr("Find online…")
                            color: Theme.accentHi
                            font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                        }
                        HoverHandler { id: onlineHover }
                        ToolTip.visible: onlineHover.hovered
                        ToolTip.text: dialog.art.onlineNote
                        ToolTip.delay: 400
                    }
                }
            }
            Text {  // why an image dropped, pasted or chosen can't be used
                id: problem
                objectName: "artMessage"
                anchors.top: zone.bottom
                anchors.topMargin: 8
                width: parent.width
                visible: text !== "" && zone.visible
                elide: Text.ElideRight
                text: dialog.art.message
                color: Theme.err
                font { family: Theme.sans; pixelSize: 13 }
                Accessible.role: Accessible.AlertMessage
                Accessible.name: text
            }

            Rectangle {  // R4.7: the files that failed, with why, and Retry
                objectName: "artFailed"
                y: zone.y
                width: parent.width
                height: Math.min(failedColumn.height + 24, parent.height - y)
                visible: (dialog.art.failed.title || "") !== ""
                radius: 10
                clip: true
                color: Theme.errSoft
                border.color: Qt.rgba(Theme.err.r, Theme.err.g, Theme.err.b, 0.45)
                Accessible.role: Accessible.AlertMessage
                Accessible.name: dialog.art.failed.title || ""
                Column {
                    id: failedColumn
                    x: 12
                    y: 12
                    width: parent.width - 24
                    spacing: 6
                    Row {
                        width: parent.width
                        spacing: 8
                        Text {
                            width: parent.width - retry.width - dismiss.width - 16
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideRight
                            text: dialog.art.failed.title || ""
                            color: Theme.text
                            font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                        }
                        Btn { id: retry; objectName: "retryArt"; label: qsTr("Retry"); icon: "refresh"; height: 30; onClicked: dialog.art.retry() }
                        Btn { id: dismiss; objectName: "dismissArt"; label: qsTr("Dismiss"); quiet: true; height: 30; onClicked: dialog.art.dismissFailed() }
                    }
                    Repeater {
                        model: (dialog.art.failed.rows || []).slice(0, 3)
                        Text {
                            required property var modelData
                            width: failedColumn.width
                            elide: Text.ElideRight
                            text: modelData.file + ": " + modelData.why
                            color: Theme.cell
                            font { family: Theme.sans; pixelSize: 13 }
                        }
                    }
                }
            }
        }

        // R5.3: what saving does
        Grid {
            id: options
            objectName: "artOptions"
            x: dialog.pad
            y: foot.y - height - 24
            columns: 2
            columnSpacing: 32
            rowSpacing: 12
            Option { name: "embed"; label: qsTr("Embed in every song of the album"); on: dialog.art.options.embed === true; width: (card.width - 2 * dialog.pad - 32) / 2 }
            Option { name: "folder"; label: qsTr("Save as cover.jpg in the folder"); on: dialog.art.options.folder === true }
            Option { name: "shrink"; label: dialog.art.options.shrinkLabel || ""; on: dialog.art.options.shrink === true; width: (card.width - 2 * dialog.pad - 32) / 2 }
            Option { name: "removeOthers"; label: qsTr("Remove other embedded images"); on: dialog.art.options.removeOthers === true }
        }

        Rectangle { y: foot.y - 1; width: parent.width; height: 1; color: Theme.border }
        Item {  // R5.3: what will change, or No change; a save's progress and Cancel (R4.7)
            id: foot
            x: dialog.pad
            y: parent.height - height
            width: parent.width - 2 * dialog.pad
            height: 74
            Text {
                objectName: "artFooter"
                width: (cancel.visible ? cancel.x : save.x) - 16
                anchors.verticalCenter: parent.verticalCenter
                visible: !progressBar.visible
                elide: Text.ElideRight
                text: dialog.art.footer
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 14 }
            }
            Item {
                id: progressBar
                objectName: "artProgress"
                width: cancel.x - 16
                height: 40
                anchors.verticalCenter: parent.verticalCenter
                visible: (dialog.art.progress.text || "") !== ""
                Accessible.role: Accessible.ProgressBar
                Accessible.name: dialog.art.progress.text || ""
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: dialog.art.progress.text || ""
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Rectangle {
                    y: 28
                    width: parent.width
                    height: 4
                    radius: 2
                    color: Theme.border
                    Rectangle {
                        width: parent.width * (dialog.art.progress.fraction || 0)
                        height: parent.height
                        radius: 2
                        color: Theme.accent
                    }
                }
            }
            Btn {
                id: cancel
                objectName: "cancelArt"
                x: save.x - width - 12
                anchors.verticalCenter: parent.verticalCenter
                visible: dialog.art.saving
                minWidth: 110
                height: 40
                label: qsTr("Cancel")
                onClicked: dialog.art.cancel()
            }
            Btn {
                id: save
                objectName: "saveArt"
                x: parent.width - width
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 120
                height: 40
                primary: true
                label: dialog.art.saveLabel
                later: dialog.art.canSave ? "" : (dialog.art.saving ? qsTr("Saving…") : qsTr("Choose a cover first"))
                onClicked: dialog.art.save()
            }
        }
    }
    FileDialog {
        id: files
        title: qsTr("Choose an image for the album")
        fileMode: FileDialog.OpenFile
        nameFilters: [qsTr("Images (*.jpg *.jpeg *.png *.webp)"), qsTr("All files (*)")]
        onAccepted: dialog.art.chooseFiles(selectedFiles)
    }
}
