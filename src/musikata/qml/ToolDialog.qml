import QtQuick
import QtQuick.Controls.Basic
import "."

// A bulk tool of the Edit tags panel's ⋯ menu (R4.5), as a dialog over the window, drawn after
// T01-infer-from-path's: the tool's name and what it does, its options, R3.7's preview of what it
// would do (PreviewTable), and the footer counting the files and changes with Cancel and Save N
// files (R3.8), which saves through the panel (R4.7). Number tracks has no options; Replace in field
// takes the field, what to find and what to put in its place, and whether it is a regular expression
// or matches case, saying why an expression can't be used; Tidy case the fields to tidy; Copy from…
// the song to copy from and the fields to copy. Esc, the × or Cancel closes it, saving nothing. What
// it shows and does is the tool's (musikata.bulktools).
Item {
    id: dialog
    required property var tool
    readonly property var options: dialog.tool.options
    readonly property real pad: 32
    visible: dialog.tool.opened
    onVisibleChanged: if (visible) card.forceActiveFocus()

    component OptionText: Column {  // a text option, typed: Find, Replace with
        id: option
        required property string name
        required property string label
        required property string value
        required property var tool
        property real fieldWidth: 360
        spacing: 6
        Text {
            text: option.label
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 13 }
        }
        TextField {
            objectName: "tool-" + option.name
            width: option.fieldWidth
            height: 36
            leftPadding: 12
            rightPadding: 12
            text: option.value
            color: Theme.text
            selectionColor: Theme.accentSoft
            selectedTextColor: Theme.text
            selectByMouse: true
            font { family: Theme.sans; pixelSize: 14 }
            Accessible.name: option.label
            background: Rectangle {
                radius: 8
                color: Theme.input
                border.color: parent.activeFocus ? Theme.accent : Theme.border
            }
            onTextEdited: option.tool.setOption(option.name, text)
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
        objectName: "toolDialog"
        width: Math.min(parent.width - 96, 1180)
        height: parent.height - 80
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.tool.title
        Keys.onEscapePressed: dialog.tool.close()

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: title
            objectName: "toolTitle"
            x: dialog.pad
            y: 26
            width: close.x - x - 12
            elide: Text.ElideRight
            text: dialog.tool.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Item {
            id: close
            objectName: "closeTool"
            x: parent.width - 56
            y: 22
            width: 32
            height: 32
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Close %1").arg(dialog.tool.title)
            Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: dialog.tool.close() }
        }
        Text {
            id: about
            objectName: "toolAbout"
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 6
            width: parent.width - 2 * dialog.pad
            wrapMode: Text.WordWrap
            text: dialog.tool.about
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }

        Column {  // the tool's options
            id: options
            x: dialog.pad
            anchors.top: about.bottom
            anchors.topMargin: 18
            width: parent.width - 2 * dialog.pad
            visible: dialog.tool.tool !== "number"  // Number tracks has none
            spacing: 12

            Row {  // Replace in field: what to find, and what to put in its place
                visible: dialog.tool.tool === "replace"
                spacing: 16
                OptionText { name: "find"; label: qsTr("Find"); value: dialog.options.find || ""; tool: dialog.tool; fieldWidth: Math.min(360, (options.width - 16) / 2) }
                OptionText { name: "by"; label: qsTr("Replace with"); value: dialog.options.by || ""; tool: dialog.tool; fieldWidth: Math.min(360, (options.width - 16) / 2) }
            }
            Text {  // Replace in field: why the expression can't be used
                objectName: "toolProblem"
                width: parent.width
                visible: text !== ""
                elide: Text.ElideRight
                text: dialog.tool.problem
                color: Theme.err
                font { family: Theme.sans; pixelSize: 13 }
            }
            Row {  // Replace in field: how it finds
                visible: dialog.tool.tool === "replace"
                spacing: 24
                Repeater {
                    model: [
                        { name: "regex", label: qsTr("Regular expression"), on: dialog.options.regex === true },
                        { name: "match_case", label: qsTr("Match case"), on: dialog.options.matchCase === true }
                    ]
                    Row {
                        required property var modelData
                        spacing: 10
                        Check {
                            anchors.verticalCenter: parent.verticalCenter
                            mark: modelData.on ? "all" : "none"
                            Accessible.name: modelData.label
                            onToggled: dialog.tool.setOption(modelData.name, !modelData.on)
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            color: Theme.text
                            font { family: Theme.sans; pixelSize: 14 }
                        }
                    }
                }
            }
            Row {  // Copy from…: the song to copy from
                visible: dialog.tool.tool === "copy"
                spacing: 12
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("From")
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 14 }
                }
                Rectangle {
                    id: source
                    objectName: "toolSource"
                    width: Math.min(520, options.width - 60)
                    height: 36
                    radius: 8
                    color: Theme.input
                    border.color: sourceHover.hovered ? Theme.borderStrong : Theme.border
                    Accessible.role: Accessible.ComboBox
                    Accessible.name: qsTr("Copy from")
                    Accessible.description: sourceText.text
                    Text {
                        id: sourceText
                        x: 12
                        width: parent.width - 44
                        anchors.verticalCenter: parent.verticalCenter
                        elide: Text.ElideRight
                        text: (dialog.options.sources || [])[dialog.options.source || 0] || ""
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 14 }
                    }
                    Icon { x: parent.width - 26; anchors.verticalCenter: parent.verticalCenter; name: "chevDown"; size: 14; color: Theme.muted }
                    HoverHandler { id: sourceHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: sources.popup(source, 0, source.height) }
                    Menu {
                        id: sources
                        Repeater {
                            model: dialog.options.sources || []
                            MenuItem {
                                required property var modelData
                                required property int index
                                text: modelData
                                onTriggered: dialog.tool.setOption("source", index)
                            }
                        }
                    }
                }
            }
            Flow {  // the field to replace in (one), or the fields to tidy or copy (any)
                visible: dialog.tool.tool !== "number"
                width: parent.width
                spacing: 8
                Text {
                    height: 32
                    rightPadding: 4
                    verticalAlignment: Text.AlignVCenter
                    text: dialog.tool.tool === "replace" ? qsTr("In") : qsTr("Fields")
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 14 }
                }
                Repeater {
                    model: dialog.options.fields || []
                    Chip {
                        required property var modelData
                        objectName: "toolField-" + modelData.name
                        label: modelData.label
                        chosen: modelData.chosen
                        Accessible.role: dialog.tool.tool === "replace" ? Accessible.RadioButton : Accessible.CheckBox
                        Accessible.checked: modelData.chosen
                        onClicked: dialog.tool.tool === "replace" ? dialog.tool.setOption("field", modelData.name) : dialog.tool.toggleField(modelData.name)
                    }
                }
            }
        }

        PreviewTable {
            objectName: "toolPreview"
            x: dialog.pad
            anchors.top: options.visible ? options.bottom : about.bottom
            anchors.topMargin: options.visible ? 18 : 24
            anchors.bottom: foot.top
            anchors.bottomMargin: 18
            width: parent.width - 2 * dialog.pad
            preview: dialog.tool.preview
        }

        Rectangle { y: foot.y - 1; width: parent.width; height: 1; color: Theme.border }
        Item {  // R3.8: the files and changes that will be saved, Cancel and Save N files
            id: foot
            x: dialog.pad
            y: parent.height - height
            width: parent.width - 2 * dialog.pad
            height: 76
            Text {
                objectName: "toolFooter"
                width: cancel.x - 16
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: dialog.tool.preview.footer
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 14 }
            }
            Btn {
                id: cancel
                objectName: "cancelTool"
                x: save.x - width - 12
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 120
                label: qsTr("Cancel")
                height: 40
                onClicked: dialog.tool.close()
            }
            Btn {
                id: save
                objectName: "saveTool"
                x: parent.width - width
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 160
                label: dialog.tool.preview.saveLabel
                icon: "check"
                primary: true
                height: 40
                later: dialog.tool.preview.canSave && dialog.tool.problem === "" ? "" : qsTr("Nothing to save")
                onClicked: dialog.tool.save()
            }
        }
    }
}
