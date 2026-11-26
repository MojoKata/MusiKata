import QtQuick
import QtQuick.Controls.Basic
import "."

// Songs (R2.6): every song of the library, or those the header's search finds (R2.7), paged from the
// index as it scrolls (A1.5); a click on a column's header sorts by it, again the other way; a double
// click plays a song, the rest of the list after it its queue (R7.1), and a right click opens its
// menu, Play next and Add to queue (R7.2). Its selection and the Edit tags panel come with slice 5
// (L03-songs-bulk-edit).
Item {
    id: view
    required property var library
    required property var player

    Item {
        id: table
        x: 20
        y: 6
        width: view.width - 36
        height: view.height - y

        // [x, width] of each column: #, title, artist, album, genre, year, rating, plays, time;
        // the four of text share what the fixed ones leave
        readonly property real gap: 16
        readonly property var fixed: [28, 0, 0, 0, 0, 44, 70, 48, 44]
        readonly property var share: [0, 0.31, 0.22, 0.27, 0.20, 0, 0, 0, 0]
        readonly property real free: Math.max(0, width - 12 - 12 - fixed.reduce((a, b) => a + b, 0) - gap * 8)
        readonly property var columns: {
            let x = 12, out = []
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
                onActivated: view.player.playFrom(view.library.songs, index)
                onMenu: songMenu.openFor(view.library.songs, index)
            }
            ScrollBar.vertical: ScrollBar { }
        }
        SongMenu { id: songMenu; player: view.player }
        Text {
            anchors.centerIn: list
            visible: text !== ""
            text: view.library.emptyText
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }
    }
}
