import QtQuick
import QtQuick.Controls.Basic
import "."

// Infer tags from path (R3, T01-infer-from-path), as a dialog over the window: its title and what it
// does; the pattern, its tokens as chips until the field is clicked, then its text to edit, the
// preview following as the user types (R3.4.1); beside it the picker, "Detected · 9 of 9 fit",
// whose list holds every pattern tried with its count (R3.4); the tokens below, each inserted at the
// cursor by a click; Only fill empty tags or Correct tags that differ (R3.5) and R3.6's checkboxes;
// R3.7's preview (PreviewTable), the files the pattern doesn't fit last, so noted; and the footer
// counting the files and changes, with Cancel and Save N files (R3.8), which while the save goes on
// says how far it has come. Esc, the × or Cancel closes it, saving nothing. What it shows and does
// is musikata.infer's.
Item {
    id: dialog
    required property var infer
    readonly property real pad: 32
    readonly property bool loading: dialog.infer.loading  // the tour waits for the songs
    visible: dialog.infer.opened
    onVisibleChanged: if (visible) card.forceActiveFocus()

    component Radio: Item {  // R3.5's mode
        id: radio
        signal clicked()
        property string label
        property bool chosen
        width: radioRow.width
        height: 32
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
        objectName: "inferDialog"
        width: Math.min(parent.width - 96, 1180)
        height: parent.height - 80
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.infer.title
        Keys.onEscapePressed: dialog.infer.close()

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: title
            objectName: "inferTitle"
            x: dialog.pad
            y: 26
            width: close.x - x - 12
            elide: Text.ElideRight
            text: dialog.infer.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Item {
            id: close
            objectName: "closeInfer"
            x: parent.width - 56
            y: 22
            width: 32
            height: 32
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Close %1").arg(dialog.infer.title)
            Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: dialog.infer.close() }
        }
        Text {
            id: about
            objectName: "inferAbout"
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 6
            width: parent.width - 2 * dialog.pad
            wrapMode: Text.WordWrap
            text: dialog.infer.about
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }

        Column {  // the pattern, the tokens and the options
            id: options
            x: dialog.pad
            anchors.top: about.bottom
            anchors.topMargin: 20
            width: parent.width - 2 * dialog.pad
            spacing: 12

            Text {
                text: qsTr("Pattern")
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
            }
            Row {
                width: parent.width
                spacing: 16
                TextField {  // the pattern, its tokens shown as chips while it isn't being edited
                    id: field
                    objectName: "inferPattern"
                    readonly property bool chips: !activeFocus && dialog.infer.parts.length > 0
                    width: parent.width - picker.width - 16
                    height: 52
                    leftPadding: 16
                    rightPadding: 16
                    text: dialog.infer.pattern
                    color: chips ? "transparent" : Theme.text
                    selectionColor: Theme.accentSoft
                    selectedTextColor: Theme.text
                    selectByMouse: true
                    font { family: Theme.sans; pixelSize: 16 }
                    Accessible.name: qsTr("Pattern")
                    background: Rectangle {
                        radius: 10
                        color: Theme.input
                        border.color: field.activeFocus || field.chips ? Theme.accent : Theme.border
                        border.width: field.activeFocus || field.chips ? 2 : 1
                    }
                    onTextEdited: dialog.infer.setPattern(text)
                    Row {
                        x: field.leftPadding - 6
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 6
                        visible: field.chips
                        Repeater {
                            model: dialog.infer.parts
                            Rectangle {
                                required property var modelData
                                readonly property bool token: modelData.kind === "token"
                                anchors.verticalCenter: parent.verticalCenter
                                width: partText.width + (token ? 20 : 4)
                                height: 32
                                radius: 7
                                color: token ? Theme.accentSoft : "transparent"
                                Text {
                                    id: partText
                                    anchors.centerIn: parent
                                    text: modelData.text
                                    color: parent.token ? Theme.accentHi : Theme.muted
                                    font { family: Theme.sans; pixelSize: 16; weight: parent.token ? Font.DemiBold : Font.Normal }
                                }
                            }
                        }
                    }
                }
                Rectangle {  // the picker (R3.4)
                    id: picker
                    objectName: "inferPicker"
                    width: Math.min(300, options.width * 0.3)
                    height: 52
                    radius: 10
                    color: Theme.input
                    border.color: pickerHover.hovered ? Theme.borderStrong : Theme.border
                    Accessible.role: Accessible.ComboBox
                    Accessible.name: qsTr("Patterns")
                    Accessible.description: pickerText.text
                    Text {
                        id: pickerText
                        x: 18
                        width: parent.width - 52
                        anchors.verticalCenter: parent.verticalCenter
                        elide: Text.ElideRight
                        text: dialog.infer.picker
                        color: dialog.infer.detected ? Theme.ok : dialog.infer.parts.length ? Theme.text : Theme.err
                        font { family: Theme.sans; pixelSize: 15; weight: Font.DemiBold }
                    }
                    Icon { x: parent.width - 32; anchors.verticalCenter: parent.verticalCenter; name: "chevDown"; size: 14; color: Theme.muted }
                    HoverHandler { id: pickerHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: patternMenu.popup(picker, 0, picker.height) }
                    Menu {
                        id: patternMenu
                        Repeater {
                            model: dialog.infer.choices
                            MenuItem {
                                required property var modelData
                                required property int index
                                text: modelData.text + "  ·  " + modelData.label
                                checkable: true
                                checked: modelData.chosen
                                onTriggered: dialog.infer.choosePattern(index)
                            }
                        }
                    }
                }
            }
            Flow {  // the tokens, each inserted where the cursor is (R3.4.1)
                width: parent.width
                spacing: 8
                Text {
                    height: 32
                    rightPadding: 4
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Tokens:")
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 14 }
                }
                Repeater {
                    model: dialog.infer.tokens
                    Chip {
                        required property var modelData
                        objectName: "inferToken"
                        label: modelData
                        Accessible.name: qsTr("Insert %1").arg(modelData)
                        onClicked: {
                            const at = field.cursorPosition
                            field.insert(at, modelData)
                            dialog.infer.setPattern(field.text)
                        }
                    }
                }
            }
            Flow {  // R3.5's mode and R3.6's tidying
                width: parent.width
                spacing: 24
                Repeater {
                    model: dialog.infer.modes
                    Radio {
                        required property var modelData
                        objectName: "inferMode-" + modelData.name
                        label: modelData.label
                        chosen: modelData.chosen
                        onClicked: dialog.infer.setOption("mode", modelData.name)
                    }
                }
                Repeater {
                    model: dialog.infer.checks
                    Row {
                        required property var modelData
                        height: 32
                        spacing: 10
                        Check {
                            objectName: "inferCheck-" + modelData.name
                            anchors.verticalCenter: parent.verticalCenter
                            mark: modelData.on ? "all" : "none"
                            Accessible.name: modelData.label
                            onToggled: dialog.infer.toggle(modelData.name)
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
            Text {  // a save that failed, with why
                objectName: "inferProblem"
                width: parent.width
                visible: text !== ""
                elide: Text.ElideRight
                text: dialog.infer.problem
                color: Theme.err
                font { family: Theme.sans; pixelSize: 13 }
            }
        }

        PreviewTable {
            objectName: "inferPreview"
            x: dialog.pad
            anchors.top: options.bottom
            anchors.topMargin: 18
            anchors.bottom: foot.top
            anchors.bottomMargin: 18
            width: parent.width - 2 * dialog.pad
            preview: dialog.infer.preview
        }

        Rectangle { y: foot.y - 1; width: parent.width; height: 1; color: Theme.border }
        Item {  // R3.8: the files and changes that will be saved, Cancel and Save N files
            id: foot
            x: dialog.pad
            y: parent.height - height
            width: parent.width - 2 * dialog.pad
            height: 76
            Text {
                objectName: "inferFooter"
                width: cancel.x - 16
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: dialog.infer.footer
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 14 }
            }
            Btn {
                id: cancel
                objectName: "cancelInfer"
                x: save.x - width - 12
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 120
                label: qsTr("Cancel")
                height: 40
                onClicked: dialog.infer.close()
            }
            Btn {
                id: save
                objectName: "saveInfer"
                x: parent.width - width
                anchors.verticalCenter: parent.verticalCenter
                minWidth: 160
                label: dialog.infer.saveLabel
                icon: "check"
                primary: true
                height: 40
                later: dialog.infer.saveLater
                onClicked: dialog.infer.save()
            }
        }
    }
}
