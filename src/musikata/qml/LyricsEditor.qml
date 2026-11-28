import QtQuick
import QtQuick.Controls.Basic
import "."

// Edit… and Add… of Now Playing's lyrics (R17.5), over the window: "Edit lyrics · Signal Fires", the
// lyrics as text, timed ones with their [mm:ss.xx] times; under it where Save keeps them (R13.11);
// Cancel, × or Esc closes it, changing nothing; Save writes them, one entry in the change history
// whose Undo puts them back (R4.9), and closes it, or says what failed. What it says is
// musikata.lyrics'.
Item {
    id: dialog
    required property var lyrics
    readonly property real pad: 28
    visible: dialog.lyrics.editing
    onVisibleChanged: if (visible) { area.text = dialog.lyrics.editText; area.forceActiveFocus() }

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        TapHandler { }
        WheelHandler { }
    }
    FocusScope {
        id: card
        objectName: "lyricsEditor"
        width: Math.min(parent.width - 96, 760)
        height: Math.min(parent.height - 80, 680)
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.lyrics.editTitle
        Keys.onEscapePressed: dialog.lyrics.cancel()

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: title
            objectName: "lyricsEditorTitle"
            x: dialog.pad
            y: 24
            width: close.x - x - 16
            elide: Text.ElideRight
            text: dialog.lyrics.editTitle
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Item {
            id: close
            objectName: "closeLyricsEditor"
            x: parent.width - 56
            y: 22
            width: 32
            height: 32
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Close %1").arg(dialog.lyrics.editTitle)
            Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
            HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: dialog.lyrics.cancel() }
        }
        Text {
            id: about
            objectName: "lyricsEditorAbout"
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 6
            width: parent.width - 2 * dialog.pad
            wrapMode: Text.Wrap
            text: qsTr("Timed lyrics start each line with its time, [mm:ss.xx]; lines without one are plain lyrics.")
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 13 }
        }
        Rectangle {
            id: box
            x: dialog.pad
            anchors.top: about.bottom
            anchors.topMargin: 14
            anchors.bottom: foot.top
            width: parent.width - 2 * dialog.pad
            radius: 10
            color: Theme.input
            border.color: area.activeFocus ? Theme.accent : Theme.borderStrong
            ScrollView {
                anchors.fill: parent
                anchors.margins: 2
                TextArea {
                    id: area
                    objectName: "lyricsText"
                    onTextChanged: dialog.lyrics.setText(text)  // its text set as it opens
                    readOnly: dialog.lyrics.saving
                    wrapMode: TextEdit.Wrap
                    color: Theme.text
                    selectionColor: Theme.sel
                    selectedTextColor: Theme.text
                    placeholderText: qsTr("[00:12.00] The first line, or the lyrics as plain text")
                    placeholderTextColor: Theme.faint
                    font { family: Theme.mono; pixelSize: 14 }
                    background: Item { }
                    Accessible.role: Accessible.EditableText
                    Accessible.name: qsTr("Lyrics")
                    Keys.onEscapePressed: dialog.lyrics.cancel()
                }
            }
        }
        Item {
            id: foot
            width: parent.width
            height: 72
            anchors.bottom: parent.bottom
            Text {
                objectName: "lyricsWhere"
                x: dialog.pad
                width: buttons.x - x - 16
                anchors.verticalCenter: parent.verticalCenter
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
                text: dialog.lyrics.editProblem !== "" ? dialog.lyrics.editProblem : dialog.lyrics.editWhere
                color: dialog.lyrics.editProblem !== "" ? Theme.err : Theme.muted
                font { family: Theme.sans; pixelSize: 13 }
            }
            Row {
                id: buttons
                x: parent.width - width - dialog.pad
                anchors.verticalCenter: parent.verticalCenter
                spacing: 12
                Btn {
                    objectName: "cancelLyrics"
                    minWidth: 110
                    height: 40
                    label: qsTr("Cancel")
                    onClicked: dialog.lyrics.cancel()
                }
                Btn {
                    objectName: "saveLyrics"
                    minWidth: 110
                    height: 40
                    primary: true
                    label: dialog.lyrics.saving ? qsTr("Saving…") : qsTr("Save")
                    later: dialog.lyrics.saveLater
                    onClicked: dialog.lyrics.save()
                }
            }
        }
    }
}
