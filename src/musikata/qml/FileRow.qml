import QtQuick
import "."

// A file in Folders: in the image modes under "4 songs in this folder" (L05-folders-large: file,
// title, album, rating, time), or in a folder of songs (L08-folder-songs: file, track and title,
// artist, genre, year, a value that differs from the rest of the folder marked), as `columns` and
// `songs` say. Selected, it is highlighted; the song playing has its title in the accent. A click
// selects it (Ctrl/⌘ and Shift as everywhere), a double click plays it. Its path-match chip
// (R3.9) comes with slice 7.
Rectangle {
    id: row
    signal tapped(int modifiers)
    signal activated()
    required property var columns       // [x, width] of each column
    required property bool songs        // a folder of songs' columns
    required property string name
    required property string title
    required property string numbered
    required property string artist
    required property string genre
    required property string year
    required property string third      // the album, or while searching where it is
    required property int rating
    required property string time
    required property var odd           // the fields whose values differ from the folder's
    required property bool playing
    required property bool selected
    height: songs ? 40 : 36
    radius: 6
    color: row.selected ? Theme.sel : (hover.hovered ? Theme.hover : "transparent")
    Accessible.role: Accessible.ListItem
    Accessible.name: row.name
    Accessible.selected: row.selected

    HoverHandler { id: hover }
    TapHandler {
        id: tap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: row.tapped(tap.point.modifiers)
        onDoubleTapped: row.activated()
    }

    component Cell: Text {
        property int column
        x: row.columns[column][0]
        width: row.columns[column][1]
        height: row.height
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        color: Theme.cell
        font { family: Theme.sans; pixelSize: 13; features: { "tnum": 1 } }
    }

    Icon {
        x: row.columns[0][0]
        anchors.verticalCenter: parent.verticalCenter
        name: "file"
        size: 15
        color: Theme.muted
    }
    Cell {
        column: 0
        x: row.columns[0][0] + 26
        width: row.columns[0][1] - 26
        text: row.name
        color: row.playing ? Theme.accentHi : Theme.text
    }
    Cell { column: 1; text: row.songs ? row.numbered : row.title }
    Cell {
        column: 2
        text: row.songs ? row.artist : row.third
        color: row.songs && row.odd.indexOf("artist") >= 0 ? Theme.err : Theme.cell
    }
    Cell {
        column: 3
        visible: row.songs
        text: row.genre
        color: row.odd.indexOf("genre") >= 0 ? Theme.warn : Theme.cell
    }
    Cell {
        column: 4
        visible: row.songs
        text: row.year || "—"
        color: row.odd.indexOf("year") >= 0 ? Theme.warn : (row.year ? Theme.cell : Theme.faint)
    }
    Stars {
        x: row.columns[3][0]
        anchors.verticalCenter: parent.verticalCenter
        visible: !row.songs
        rating: row.rating
    }
    Cell { column: 4; visible: !row.songs; text: row.time; color: Theme.muted; horizontalAlignment: Text.AlignRight }
}
