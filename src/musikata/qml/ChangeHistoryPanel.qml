import QtQuick
import QtQuick.Controls.Basic
import "."

// ⋮ › Change history (R4.9): a panel docked on the right, drawn as L03's Edit tags panel is (no
// mockup of its own): its heading and count, then the saves newest first under a heading per day,
// each with what it was, its time, the computer that saved it and how many files, and **Undo**; under
// each, the files it touched with the fields it changed, each with its own Undo, the first few and
// "N more files" to list the rest. A save undone is dimmed and says so; an Undo is undone in turn (a
// redo). R4.9.1's question, when a file has changed since, comes first in amber: what undoing would
// lose, file by file, and **Undo anyway**, **Undo the other N files** or **Cancel**. Esc or the ×
// closes it. What it lists and says is the history's (musikata.history).
Rectangle {
    id: panel
    required property var history
    readonly property var question: panel.history.question
    property bool loading: panel.history.loading  // the tour waits while it reads or undoes
    color: Theme.side
    focus: visible
    Accessible.role: Accessible.Pane
    Accessible.name: qsTr("Change history")
    Keys.onEscapePressed: panel.history.hide()

    TapHandler { }  // a click inside the panel stays in it
    Rectangle { width: 1; height: parent.height; color: Theme.border }

    Text {
        id: heading
        objectName: "historyHeading"
        x: 24
        y: 26
        width: parent.width - 80
        elide: Text.ElideRight
        text: qsTr("Change history") + " · " + panel.history.countText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13; weight: Font.Bold; letterSpacing: 0.5; capitalization: Font.AllUppercase }
    }
    Item {
        objectName: "closeHistory"
        x: parent.width - 48
        y: 18
        width: 32
        height: 32
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Close Change history")
        Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
        Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
        HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: panel.history.hide() }
    }

    Rectangle {  // R4.9.1: what undoing would lose, asked first
        id: asking
        objectName: "historyQuestion"
        x: 16
        y: 62
        width: parent.width - 32
        height: visible ? askColumn.height + 28 : 0
        visible: panel.question.title !== undefined
        radius: 12
        color: Theme.warnSoft
        border.color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.45)
        Accessible.role: Accessible.AlertMessage
        Accessible.name: panel.question.title || ""

        Column {
            id: askColumn
            x: 14
            y: 14
            width: parent.width - 28
            spacing: 8
            Row {
                spacing: 10
                width: parent.width
                Icon { name: "attention"; size: 18; color: Theme.warn }
                Text {
                    width: parent.width - 28
                    wrapMode: Text.WordWrap
                    text: panel.question.title || ""
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                }
            }
            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                text: panel.question.detail || ""
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 12 }
            }
            Repeater {
                model: panel.question.lines || []
                Column {
                    required property var modelData
                    width: askColumn.width
                    spacing: 2
                    Text {
                        width: parent.width
                        elide: Text.ElideMiddle
                        text: modelData.file
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 12; weight: Font.DemiBold }
                    }
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: modelData.lost
                        color: Theme.cell
                        font { family: Theme.sans; pixelSize: 12 }
                    }
                }
            }
            Flow {
                width: parent.width
                spacing: 8
                Btn {
                    objectName: "undoAnyway"
                    label: qsTr("Undo anyway")
                    icon: "undo"
                    height: 32
                    onClicked: panel.history.answer("overwrite")
                }
                Btn {
                    objectName: "undoOthers"
                    visible: panel.question.skip === true
                    label: panel.question.skipText || ""
                    height: 32
                    onClicked: panel.history.answer("skip")
                }
                Btn {
                    objectName: "cancelUndo"
                    label: qsTr("Cancel")
                    quiet: true
                    height: 32
                    onClicked: panel.history.answer("cancel")
                }
            }
        }
    }

    Text {
        objectName: "historyEmpty"
        anchors { left: parent.left; right: parent.right; leftMargin: 24; rightMargin: 24 }
        y: 96
        visible: text !== ""
        wrapMode: Text.WordWrap
        text: panel.history.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }

    ListView {
        id: rows
        objectName: "historyRows"
        x: 12
        y: asking.visible ? asking.y + asking.height + 12 : 62
        width: parent.width - 24
        height: parent.height - y - 12
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: panel.history.rows
        delegate: Item {
            id: row
            required property var modelData
            readonly property string kind: modelData.kind
            width: rows.width
            height: kind === "day" ? 38 : kind === "entry" ? 56 : kind === "file" ? 42 : 30
            Accessible.role: kind === "day" ? Accessible.Heading : Accessible.ListItem
            Accessible.name: modelData.text

            Text {  // a day's heading
                visible: row.kind === "day"
                x: 12
                y: 14
                width: row.width - 24
                elide: Text.ElideRight
                text: row.modelData.text
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4; capitalization: Font.AllUppercase }
            }

            Rectangle {  // a save
                visible: row.kind === "entry"
                y: 4
                width: row.width
                height: 50
                radius: 10
                color: entryHover.hovered ? Theme.hover : Theme.surface
                opacity: row.modelData.undone ? 0.6 : 1
                HoverHandler { id: entryHover }
                Icon {
                    x: 12
                    anchors.verticalCenter: parent.verticalCenter
                    name: row.modelData.isUndo ? "undo" : "check"
                    size: 16
                    color: row.modelData.isUndo ? Theme.accent : Theme.ok
                }
                Text {
                    x: 38
                    y: 7
                    width: entryUndo.x - x - 8
                    elide: Text.ElideRight
                    text: row.modelData.text || ""
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                }
                Text {
                    x: 38
                    y: 27
                    width: entryUndo.x - x - 8
                    elide: Text.ElideRight
                    text: (row.modelData.undone ? qsTr("Undone") + " · " : "") + (row.modelData.line || "")
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 12 }
                }
                Btn {
                    id: entryUndo
                    objectName: "undoEntry"
                    x: parent.width - width - 9
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !row.modelData.undone
                    label: qsTr("Undo")
                    icon: "undo"
                    height: 30
                    later: panel.history.busy ? qsTr("An undo is going on") : ""
                    Accessible.name: qsTr("Undo") + " " + (row.modelData.text || "")
                    onClicked: panel.history.undo(row.modelData.name)
                }
            }

            Item {  // a file it touched
                visible: row.kind === "file"
                x: 26
                width: row.width - 26
                height: row.height
                HoverHandler { id: fileHover }
                Rectangle { anchors.fill: parent; anchors.margins: 1; radius: 8; color: fileHover.hovered ? Theme.hover : "transparent" }
                Icon { x: 8; y: 13; name: "file"; size: 14; color: Theme.faint }
                Text {
                    x: 30
                    y: 4
                    width: fileUndo.x - x - 6
                    elide: Text.ElideMiddle
                    text: row.modelData.text || ""
                    color: Theme.cell
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Text {
                    x: 30
                    y: 22
                    width: fileUndo.x - x - 6
                    elide: Text.ElideRight
                    text: (row.modelData.fields || "") + (row.modelData.folder ? " · " + row.modelData.folder : "")
                    color: Theme.faint
                    font { family: Theme.sans; pixelSize: 11 }
                }
                Item {
                    id: fileUndo
                    objectName: "undoFile"
                    x: parent.width - 36
                    y: 5
                    width: 32
                    height: 32
                    Accessible.role: Accessible.Button
                    Accessible.name: qsTr("Undo") + " " + (row.modelData.text || "")
                    Rectangle { anchors.fill: parent; radius: 8; color: undoHover.hovered ? Theme.raised : "transparent" }
                    Icon { anchors.centerIn: parent; name: "undo"; size: 15; color: undoHover.hovered ? Theme.accentHi : Theme.muted }
                    HoverHandler { id: undoHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { enabled: !panel.history.busy; onTapped: panel.history.undoFile(row.modelData.name, row.modelData.position) }
                    ToolTip.visible: undoHover.hovered
                    ToolTip.text: qsTr("Undo this file only")
                    ToolTip.delay: 400
                }
            }

            Text {  // the files not listed yet
                visible: row.kind === "more"
                objectName: "moreFiles"
                x: 56
                height: row.height
                verticalAlignment: Text.AlignVCenter
                text: row.modelData.text || ""
                color: Theme.accentHi
                font { family: Theme.sans; pixelSize: 12; weight: Font.DemiBold }
                Accessible.role: Accessible.Button
                Accessible.name: text
                HoverHandler { enabled: row.kind === "more"; cursorShape: Qt.PointingHandCursor }
                TapHandler { enabled: row.kind === "more"; onTapped: panel.history.expand(row.modelData.name) }
            }
        }
    }
}
