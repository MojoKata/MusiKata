import QtQuick
import QtQuick.Controls.Basic
import "."

// Genres (R9.1, G01-genres): at the top, the banner of genres that look like one (R9.5), with
// Review…, the merge's preview with the most used name chosen, and Not now; then a tile per genre,
// by number of songs or by name as the header's sort says, worked out off the GUI thread
// (musikata.genres). A tile opens the genre's page; its ⋯ opens its menu (R9.4). `loading` is what
// the tour waits on: the banner still being worked out.
// A genre dragged carries its songs (R6.10, DragSource).
Item {
    id: view
    required property var library
    required property var player
    required property var genres
    property var dragging: null  // a genre dragged: its songs (R6.10)
    readonly property bool loading: view.genres.reading

    Banner {
        id: banner
        objectName: "genreBanner"
        x: 28
        y: 2
        width: view.width - 56
        height: visible ? 64 : 0
        visible: view.genres.banner.title !== undefined
        tone: "accent"
        icon: "merge"
        title: view.genres.banner.title || ""
        detail: view.genres.banner.detail || ""
        Btn {
            objectName: "genreNotNow"
            label: qsTr("Not now")
            quiet: true
            minWidth: 100
            height: 36
            onClicked: view.genres.notNow()
        }
        Btn {
            objectName: "genreReview"
            label: qsTr("Review…")
            icon: "merge"
            primary: true
            minWidth: 104
            height: 36
            later: view.library.available ? "" : view.library.playNote
            onClicked: view.genres.review()
        }
    }

    GridView {
        id: grid
        objectName: "genreTiles"
        readonly property int columns: Math.max(2, Math.floor((width + 16) / (220 + 16)))
        x: 28
        y: banner.visible ? banner.y + banner.height + 20 : 8
        width: view.width - 56 + 16
        height: view.height - y
        cellWidth: Math.floor(width / columns)
        cellHeight: 112 + 16
        clip: true
        reuseItems: true
        boundsBehavior: Flickable.StopAtBounds
        model: view.library.genreList
        delegate: Item {
            id: cell
            required property string name
            required property string line
            required property var covers
            required property int tone
            width: grid.cellWidth
            height: grid.cellHeight
            GenreTile {
                id: tile
                width: grid.cellWidth - 16
                name: cell.name
                line: cell.line
                covers: cell.covers
                tone: cell.tone
                menuOpen: genreMenu.opened && genreMenu.genre === cell.name
                onOpen: view.library.openGenre(cell.name)
                onMenu: (button) => genreMenu.openFor(cell.name, button, 0, button.height + 4)
                // the tour's (A1.6): the menu G01-genres draws open
                readonly property bool asked: view.genres.menuFor === cell.name
                onAskedChanged: if (asked) genreMenu.openFor(cell.name, tile, tile.width - 30, 36)
                Component.onCompleted: if (asked) genreMenu.openFor(cell.name, tile, tile.width - 30, 36)
                DragSource { dragging: view.dragging; onCarry: view.dragging.carryGenre(cell.name) }
            }
        }
        ScrollBar.vertical: ScrollBar { }
    }

    GenreMenu {
        id: genreMenu
        library: view.library
        player: view.player
        genres: view.genres
        onShut: view.genres.menuClosed()
    }

    Text {  // the library empty, or a search that found nothing (R2.7)
        objectName: "empty"
        anchors.horizontalCenter: parent.horizontalCenter
        y: grid.y + 72
        width: Math.min(implicitWidth, view.width - 56)
        elide: Text.ElideRight
        visible: text !== ""
        text: view.library.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 14 }
    }
}
