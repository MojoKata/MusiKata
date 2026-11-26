import QtQuick
import QtQuick.Controls.Basic
import "."

// Songs (R2.6): every song of the library, paged from the index as it scrolls (A1.5). Its search,
// sort and selection come with slice 3, the Edit tags panel with slice 5 (L03-songs-bulk-edit).
Item {
    id: view
    required property var library

    Text {
        id: title
        x: 28
        y: 14
        height: 36
        verticalAlignment: Text.AlignVCenter
        text: "Songs"
        color: Theme.text
        font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
    }
    Text {
        anchors.left: title.right
        anchors.leftMargin: 14
        anchors.baseline: title.baseline
        text: view.library.countText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }

    Item {
        id: table
        x: 20
        y: 70
        width: view.width - 36
        height: view.height - y

        // [x, width] of each column: #, title, artist, album, genre, year, rating, time; the four
        // of text share what the fixed ones leave
        readonly property real gap: 16
        readonly property var fixed: [28, 0, 0, 0, 0, 44, 70, 44]
        readonly property var share: [0, 0.31, 0.22, 0.27, 0.20, 0, 0, 0]
        readonly property real free: Math.max(0, width - 12 - 12 - fixed.reduce((a, b) => a + b, 0) - gap * 7)
        readonly property var columns: {
            let x = 12, out = []
            for (let i = 0; i < fixed.length; i++) {
                const w = fixed[i] + share[i] * free
                out.push([x, w])
                x += w + gap
            }
            return out
        }

        Repeater {
            model: ["#", "TITLE", "ARTIST", "ALBUM", "GENRE", "YEAR", "RATING", "TIME"]
            Text {
                required property int index
                required property string modelData
                x: table.columns[index][0]
                width: table.columns[index][1]
                height: 32
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: index === 0 || index === 7 ? Text.AlignRight : Text.AlignLeft
                text: modelData
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4 }
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
            delegate: SongRow { width: list.width; columns: table.columns }
            ScrollBar.vertical: ScrollBar { }
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
