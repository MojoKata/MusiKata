import QtQuick
import QtQuick.Controls.Basic
import "."

// Up next (R7.2), the panel the bar's queue button opens: where the queue plays from, how many songs
// are left and how long they take; then the song playing, the songs to come (those added with Play
// next or Add to queue first, "Next · added by you", then the rest of the list, "Next from Glass
// Harbor"), and the songs played, dimmed, the latest first; each with its cover, title, artist and
// album, and length, under its heading (N03-now-playing-queue's rows). A row under the pointer shows
// its drag handle, to reorder the songs to come, and its ×, to take it out; a double click plays it.
// Its rows are selected as every song list's are (R2.6), clicks and keys forwarded to the model:
// Enter plays the first song selected, Delete takes the selection out of the queue. Esc clears the
// selection, or with none closes it, as the × at the top does. Songs dragged onto it from the views,
// or files from a file manager, play next (R6.10), the panel outlined and saying so while they are
// over it; its own rows are still moved by their handles, within it.
Rectangle {
    id: panel
    required property var player
    readonly property var model: player.upNext
    property int dropRow: -1           // where a dragged row would land, while one is dragged
    property var dragging: null        // songs dragged from the views onto it (musikata.dragging)
    radius: 14
    color: Theme.surface
    border.color: Theme.borderStrong
    focus: visible
    Keys.onReturnPressed: panel.player.playSelected()
    Keys.onEnterPressed: panel.player.playSelected()
    Keys.onDeletePressed: panel.player.removeSelected()
    Keys.onPressed: (event) => {
        const row = panel.model.press(event.key, event.modifiers, Math.max(1, Math.floor(rows.height / 48)))
        if (row === -2 && event.key === Qt.Key_Escape)
            panel.player.closeUpNext()
        else
            event.accepted = row !== -2
        if (row >= 0)
            rows.positionViewAtIndex(row, ListView.Contain)
    }

    TapHandler { }  // a click inside the panel stays in it

    Text {
        id: heading
        x: 20
        y: 16
        width: parent.width - 76
        elide: Text.ElideRight
        text: qsTr("Up next")
        color: Theme.text
        font { family: Theme.sans; pixelSize: 18; weight: Font.Bold }
    }
    Text {
        objectName: "upNextLine"
        x: 20
        anchors.top: heading.bottom
        anchors.topMargin: 2
        width: parent.width - 40
        elide: Text.ElideRight
        text: panel.model.note || panel.model.line  // why the songs up next can't play (R2.10)
        color: panel.model.note ? Theme.err : Theme.muted
        font { family: Theme.sans; pixelSize: 12 }
    }
    Item {
        objectName: "closeUpNext"
        x: parent.width - 44
        y: 14
        width: 28
        height: 28
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Close Up next")
        Rectangle { anchors.fill: parent; radius: 14; color: closeHover.hovered ? Theme.hover : "transparent" }
        Icon { anchors.centerIn: parent; name: "close"; size: 14; color: Theme.muted }
        HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: panel.player.closeUpNext() }
    }

    ListView {
        id: rows
        objectName: "upNextRows"
        x: 10
        y: 72
        width: parent.width - 20
        height: parent.height - y - 10
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: panel.model
        delegate: Item {
            id: row
            required property int index
            required property string kind
            required property string section
            required property bool first
            required property string title
            required property string line
            required property string time
            required property string cover
            required property bool selected
            required property bool current
            readonly property real headed: first ? 28 : 0
            width: rows.width
            height: headed + 48
            Accessible.role: Accessible.ListItem
            Accessible.name: row.title
            Accessible.selected: row.selected

            Text {
                visible: row.first
                x: 10
                y: 8
                width: row.width - 20
                elide: Text.ElideRight
                text: row.section
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4; capitalization: Font.AllUppercase }
            }
            Rectangle {
                id: body
                y: row.headed
                width: row.width
                height: 46
                radius: 10
                color: row.selected ? Theme.sel : row.kind === "now" ? Theme.accentSoft : (hover.hovered ? Theme.hover : "transparent")
                border.color: Theme.accent
                border.width: row.current && panel.activeFocus ? 1.5 : 0
                opacity: row.kind === "played" ? 0.55 : 1

                HoverHandler { id: hover }
                TapHandler {
                    id: tap
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: {
                        panel.forceActiveFocus()
                        panel.model.click(row.index, (tap.point.modifiers & Qt.ControlModifier) !== 0, (tap.point.modifiers & Qt.ShiftModifier) !== 0)
                    }
                    onDoubleTapped: panel.player.playRow(row.index)
                }

                Item {  // the drag handle: a song to come is dropped where the line shows
                    objectName: "dragHandle"
                    x: 0
                    width: 22
                    height: body.height
                    visible: hover.hovered && row.kind === "next"
                    Accessible.role: Accessible.Button
                    Accessible.name: qsTr("Move %1").arg(row.title)
                    Icon { anchors.centerIn: parent; name: "drag"; size: 14; color: Theme.muted }
                    DragHandler {
                        id: drag
                        target: null
                        enabled: row.kind === "next"
                        yAxis.enabled: true
                        xAxis.enabled: false
                        onCentroidChanged: {
                            if (!active)
                                return
                            const at = body.mapToItem(rows.contentItem, 0, centroid.position.y)
                            const over = rows.indexAt(10, at.y)
                            panel.dropRow = over < 0 ? rows.count : over
                        }
                        onActiveChanged: {
                            if (!active && panel.dropRow >= 0) {
                                panel.player.moveRow(row.index, panel.dropRow)
                                panel.dropRow = -1
                            }
                        }
                    }
                }
                Cover {
                    x: 24
                    y: 6
                    width: 34
                    height: 34
                    radius: 6
                    matte: body.color.a > 0 ? body.color : Theme.surface
                    source: row.cover
                    sourceSide: 128
                }
                Icon {  // the song playing
                    x: 24 + 9
                    y: 6 + 9
                    visible: row.kind === "now"
                    name: "wave"
                    size: 16
                    color: Theme.text
                }
                Text {
                    x: 70
                    y: 5
                    width: body.width - x - 90
                    elide: Text.ElideRight
                    text: row.title
                    color: row.kind === "now" ? Theme.accentHi : Theme.text
                    font { family: Theme.sans; pixelSize: 14; weight: row.kind === "now" ? Font.DemiBold : Font.Medium }
                }
                Text {
                    x: 70
                    y: 24
                    width: body.width - x - 90
                    elide: Text.ElideRight
                    text: row.line
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 12 }
                }
                Text {
                    x: body.width - 82
                    width: 46
                    height: body.height
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignRight
                    text: row.time
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 13; features: { "tnum": 1 } }
                }
                Item {  // ×: out of the queue
                    objectName: "removeRow"
                    x: body.width - 30
                    width: 24
                    height: body.height
                    visible: hover.hovered && row.kind !== "now"
                    Accessible.role: Accessible.Button
                    Accessible.name: qsTr("Remove %1 from the queue").arg(row.title)
                    Icon { anchors.centerIn: parent; name: "close"; size: 13; color: Theme.muted }
                    TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: panel.player.removeRow(row.index) }
                }
            }
        }
        ScrollBar.vertical: ScrollBar { }
    }
    Rectangle {  // where a dragged song lands
        visible: panel.dropRow >= 0
        readonly property var target: rows.itemAtIndex(Math.min(panel.dropRow, rows.count - 1))
        x: rows.x + 10
        width: rows.width - 20
        height: 2
        color: Theme.accent
        y: target ? rows.y + target.y - rows.contentY + (panel.dropRow >= rows.count ? target.height : target.headed) : 0
    }
    DropArea {  // songs dragged from a view, or files from a file manager: played next (R6.10)
        objectName: "upNextDrop"
        anchors.fill: parent
        enabled: panel.dragging !== null
        onEntered: (drag) => drag.accepted = panel.dragging.enter("queue", 1, drag.getDataAsString(panel.dragging.mime), drag.urls)
        onExited: panel.dragging.leave("queue", 1)
        onDropped: (drop) => { if (panel.dragging.drop("queue", 1, drop.getDataAsString(panel.dragging.mime), drop.urls)) drop.accept(Qt.CopyAction) }
    }
    Rectangle {  // a drag over it: outlined, and named
        anchors.fill: parent
        radius: panel.radius
        color: "transparent"
        border.color: Theme.accent
        border.width: 2
        visible: panel.dragging !== null && panel.dragging.target === "queue:1"
        Rectangle {
            objectName: "upNextDropLabel"
            anchors.horizontalCenter: parent.horizontalCenter
            y: 76
            width: Math.min(dropLabel.implicitWidth + 24, parent.width - 40)
            height: 30
            radius: 6
            color: Theme.bar
            Text {
                id: dropLabel
                x: 12
                width: parent.width - 24
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: panel.dragging !== null ? panel.dragging.targetText : ""
                color: Theme.text
                font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
            }
        }
    }
    Text {
        anchors.centerIn: rows
        visible: text !== ""
        text: panel.model.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }
}
