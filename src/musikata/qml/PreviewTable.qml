import QtQuick
import QtQuick.Controls.Basic
import "."

// The preview of a change to many files' tags before it is saved (R3.7; T01-infer-from-path), as
// the Edit tags panel's bulk tools show it (R4.5) and Infer from path does (R3): a row per file with
// the columns the change fills, and what the change notes under its name ("Doesn't fit the pattern",
// R3.4). A value that will change shows the old value struck through in red
// above the new one in green, "(empty)" in grey for none; each changed file has a checkbox, on at
// first, and unchecking it leaves the file alone; a file with no change is dimmed, unchecked. The
// unchanged files after the last change end in "+ 3 more files, unchanged". What it shows is the
// preview's (musikata.preview).
Rectangle {
    id: table
    required property var preview
    readonly property real fileWidth: Math.max(160, width * 0.26)
    readonly property real narrowWidth: 120  // a number's or a year's column
    readonly property int wide: table.preview.columns.filter(c => !c.narrow).length
    readonly property real wideWidth: (table.width - 72 - table.fileWidth - table.narrowWidth * (table.preview.columns.length - table.wide)) / Math.max(1, table.wide)
    function columnWidth(c) { return c.narrow ? table.narrowWidth : Math.max(120, table.wideWidth) }
    radius: 12
    color: Theme.surface
    border.color: Theme.border
    clip: true
    Accessible.role: Accessible.Table
    Accessible.name: qsTr("Preview")

    Row {  // the headings
        id: head
        x: 56
        height: 44
        Text {
            width: table.fileWidth
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            text: qsTr("File")
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.5; capitalization: Font.AllUppercase }
        }
        Repeater {
            model: table.preview.columns
            Text {
                required property var modelData
                width: table.columnWidth(modelData)
                height: head.height
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                text: modelData.label
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.5; capitalization: Font.AllUppercase }
            }
        }
    }
    Rectangle { y: head.height; width: parent.width; height: 1; color: Theme.border }

    ListView {
        id: list
        objectName: "previewRows"
        y: head.height + 1
        width: parent.width
        height: parent.height - y
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: table.preview.rows
        ScrollBar.vertical: ScrollBar { }
        delegate: Item {
            id: row
            required property int index
            required property string file
            required property string folder
            required property bool changed
            required property bool checked
            required property var cells
            required property string note
            width: list.width
            height: 50
            Accessible.role: Accessible.Row
            Accessible.name: row.file
            Rectangle { x: 8; y: parent.height - 1; width: parent.width - 16; height: 1; color: Theme.border }
            Check {
                objectName: "previewCheck"
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                mark: row.checked ? "all" : "none"
                opacity: row.changed ? 1 : 0.5
                Accessible.name: qsTr("Save %1").arg(row.file)
                onToggled: table.preview.toggle(row.index)
            }
            Row {
                x: 56
                height: parent.height
                opacity: row.changed ? 1 : 0.55
                Column {
                    width: table.fileWidth
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        width: parent.width
                        rightPadding: 12
                        elide: Text.ElideMiddle
                        text: row.file
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 14 }
                    }
                    Text {
                        objectName: "previewNote"
                        width: parent.width
                        rightPadding: 12
                        visible: row.note !== ""
                        elide: Text.ElideRight
                        text: row.note
                        color: Theme.warn
                        font { family: Theme.sans; pixelSize: 12 }
                    }
                }
                Repeater {
                    model: row.cells
                    Item {
                        id: cell
                        required property var modelData
                        required property int index
                        width: table.columnWidth(table.preview.columns[cell.index] || {})
                        height: row.height
                        Accessible.role: Accessible.Cell
                        Accessible.name: cell.modelData.changed ? qsTr("%1, was %2").arg(cell.modelData["new"]).arg(cell.modelData.old) : cell.modelData.old
                        Text {  // unchanged
                            visible: !cell.modelData.changed
                            width: parent.width - 12
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: cell.modelData.old
                            color: cell.modelData.oldEmpty ? Theme.faint : Theme.cell
                            font { family: Theme.sans; pixelSize: 14 }
                        }
                        Column {  // the old value struck through in red, the new one in green
                            visible: cell.modelData.changed === true
                            width: parent.width - 12
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                width: parent.width
                                elide: Text.ElideRight
                                text: cell.modelData.old
                                color: cell.modelData.oldEmpty ? Theme.muted : Theme.err
                                font { family: Theme.sans; pixelSize: 12; strikeout: !cell.modelData.oldEmpty }
                            }
                            Text {
                                width: parent.width
                                elide: Text.ElideRight
                                text: cell.modelData["new"]
                                color: cell.modelData.newEmpty ? Theme.muted : Theme.ok
                                font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                            }
                        }
                    }
                }
            }
        }
        footer: Text {
            objectName: "previewMore"
            x: 56
            width: list.width - 72
            height: visible ? 44 : 0
            visible: text !== ""
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: table.preview.more
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 13 }
        }
    }
}
