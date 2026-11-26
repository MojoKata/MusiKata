import QtQuick
import QtQuick.Controls.Basic
import "."

// Songs (R2.6): every song of the library, or those the header's search finds (R2.7), paged from the
// index as it scrolls (A1.5); a click on a column's header sorts by it, again the other way.
//
// Its rows are selected (L03-songs-bulk-edit) with a click, Ctrl/⌘-click, Shift-click and their
// checkboxes, the header's checkbox selecting all or none; with the keyboard, ↑ and ↓ (Page Up and
// Down, Home and End) move the current row, Shift extending the range, Ctrl+A (⌘A) selects all and
// Esc clears it; all of it forwarded to the model, which decides. A double click plays a song, Enter
// the selection from its first song, the rest of the list after it the queue (R7.1); a right click
// opens the menu, Play next and Add to queue, for the selection when the row is in it (R7.2); the
// selection bar counts it and offers Play next. The Edit tags panel comes with slice 5.
Item {
    id: view
    required property var library
    required property var player
    readonly property var songs: library.songs
    focus: true

    function tapped(index, modifiers) {
        view.forceActiveFocus()
        view.songs.click(index, (modifiers & Qt.ControlModifier) !== 0, (modifiers & Qt.ShiftModifier) !== 0)
    }
    Keys.onReturnPressed: view.player.playSelection(view.songs)
    Keys.onEnterPressed: view.player.playSelection(view.songs)
    Keys.onPressed: (event) => {
        const row = view.songs.press(event.key, event.modifiers, Math.max(1, Math.floor(list.height / 36)))
        event.accepted = row !== -2
        if (row >= 0)
            list.positionViewAtIndex(row, ListView.Contain)
    }

    Item {
        id: table
        x: 20
        y: 6
        width: view.width - 36
        height: view.height - y

        // [x, width] of each column after the checkbox: #, title, artist, album, genre, year,
        // rating, plays, time; the four of text share what the fixed ones leave
        readonly property real gap: 16
        readonly property real lead: 12 + 20 + 8  // the checkbox's
        readonly property var fixed: [28, 0, 0, 0, 0, 44, 70, 48, 44]
        readonly property var share: [0, 0.31, 0.22, 0.27, 0.20, 0, 0, 0, 0]
        readonly property real free: Math.max(0, width - lead - 12 - fixed.reduce((a, b) => a + b, 0) - gap * 8)
        readonly property var columns: {
            let x = lead, out = []
            for (let i = 0; i < fixed.length; i++) {
                const w = fixed[i] + share[i] * free
                out.push([x, w])
                x += w + gap
            }
            return out
        }

        Repeater {  // the columns' headers, each sorting by its column (R2.6)
            model: view.library.songHeaders
            Item {
                id: head
                required property int index
                required property var modelData
                readonly property bool atRight: index === 0 || index >= 7
                objectName: "head-" + modelData.sort
                x: table.columns[index][0]
                width: table.columns[index][1]
                height: 32
                Accessible.role: modelData.sort ? Accessible.ColumnHeader : Accessible.StaticText
                Accessible.name: modelData.label
                HoverHandler { id: headHover; enabled: head.modelData.sort !== ""; cursorShape: Qt.PointingHandCursor }
                TapHandler { enabled: head.modelData.sort !== ""; onTapped: view.library.sortSongs(head.modelData.sort) }
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: head.atRight ? parent.right : undefined
                    spacing: 3
                    layoutDirection: head.atRight ? Qt.RightToLeft : Qt.LeftToRight
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.min(implicitWidth, head.width - (arrow.visible ? 15 : 0))
                        elide: Text.ElideRight
                        text: head.modelData.label
                        color: head.modelData.order !== "" || headHover.hovered ? Theme.text : Theme.faint
                        font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4 }
                    }
                    Icon {
                        id: arrow
                        anchors.verticalCenter: parent.verticalCenter
                        visible: head.modelData.order !== ""
                        name: head.modelData.order === "down" ? "chevDown" : "chevUp"
                        size: 12
                        color: Theme.text
                    }
                }
            }
        }
        Check {  // all or none (R2.6)
            objectName: "selectAllSongs"
            x: 12
            y: 6
            mark: view.songs.selectionState
            Accessible.name: qsTr("Select all")
            onToggled: view.songs.toggleAll()
        }
        Rectangle { y: 32; width: table.width; height: 1; color: Theme.border }

        ListView {
            id: list
            objectName: "songs"
            y: 34
            width: table.width
            height: table.height - y
            clip: true
            reuseItems: true
            boundsBehavior: Flickable.StopAtBounds
            model: view.library.songs
            delegate: SongRow {
                required property int index
                width: list.width
                columns: table.columns
                focused: view.activeFocus
                onTapped: (modifiers) => view.tapped(index, modifiers)
                onToggled: view.songs.toggle(index)
                onActivated: view.player.playFrom(view.songs, index)
                onMenu: songMenu.openFor(view.songs, index)
            }
            ScrollBar.vertical: ScrollBar { }
        }
        SongMenu { id: songMenu; player: view.player }
        SelectionBar {
            objectName: "songsSelectionBar"
            text: view.songs.selectionText
            playLabel: qsTr("Play next")
            playObjectName: "playNextSelection"
            laterActions: view.songs.laterActions
            visible: view.songs.selectionCount > 0
            anchors.horizontalCenter: list.horizontalCenter
            anchors.bottom: list.bottom
            anchors.bottomMargin: 20
            onPlay: view.player.playNextSelection(view.songs)
            onClear: view.songs.clearSelection()
        }
        Text {
            anchors.centerIn: list
            visible: text !== ""
            text: view.library.emptyText
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }
    }
}
