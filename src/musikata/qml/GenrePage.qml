import QtQuick
import QtQuick.Controls.Basic
import "."

// A genre's page (R9.1), like an artist's (L11-artist): under the header (R6.4) with its way back and
// the search box, which filters its albums and songs (R2.7); a mosaic of its covers, its name, its
// albums and songs, Play all and its ⋯ menu (R9.4); the albums with a song of it; then its songs,
// selected as the Songs list's are (R2.6), clicks and keys forwarded to the model: Enter plays the
// selection from its first song, the rest of the list after it (R7.1), and the right-click menu acts
// on the selection when the row is in it. Select its songs selects them all, for Ctrl+E (R4.2) or a
// rating (R10.2) to act on.
// An album dragged carries its songs; a song, it or the selection it is in (R6.10).
Item {
    id: page
    required property var library
    required property var player
    property var playlists: null  // Add to playlist and New playlist from selection (R8)
    property var edit: null
    property var ratings: null  // a star clicked in a row rates its song (R10.2)
    property var art: null  // Album art (R5.4): an image dropped on an album's cover
    property var dragging: null  // an album or a song dragged (R6.10)
    property var removing: null  // Move to trash (R2.11): the menu's, and Delete's (R6.9)
    required property var genres
    readonly property var genre: library.genrePage
    readonly property var songs: genre.songs
    focus: true

    function tapped(index, modifiers) {
        page.forceActiveFocus()
        page.songs.click(index, (modifiers & Qt.ControlModifier) !== 0, (modifiers & Qt.ShiftModifier) !== 0)
    }
    Keys.onReturnPressed: page.player.playSelection(page.songs)
    Keys.onEnterPressed: page.player.playSelection(page.songs)
    Keys.onDeletePressed: if (page.removing !== null) page.removing.askSelection(page.songs)
    Keys.onPressed: (event) => {
        const row = page.songs.press(event.key, event.modifiers, Math.max(1, Math.floor(list.height / 42)))
        event.accepted = row !== -2
        if (row >= 0)
            list.positionViewAtIndex(row, ListView.Contain)
    }

    // [x, width] of the song columns: #, title, album, rating, plays, time
    readonly property var columns: {
        const w = list.width
        const free = Math.max(0, w - 12 - 28 - 16 - 16 - 90 - 16 - 56 - 16 - 56 - 12 - 16)
        return [[12, 28], [56, free * 0.55], [56 + free * 0.55 + 16, free * 0.45],
                [w - 12 - 56 - 16 - 56 - 16 - 90, 90], [w - 12 - 56 - 16 - 56, 56],
                [w - 12 - 56, 56]]
    }

    ListView {
        id: list
        objectName: "genreSongs"
        x: 20
        width: page.width - 36
        height: page.height
        clip: true
        reuseItems: true
        spacing: 2
        boundsBehavior: Flickable.StopAtBounds
        model: page.genre.songs
        header: Item {
            id: head
            width: list.width
            height: albumsFlow.y + albumsFlow.height + (page.genre.songsTitle ? 76 : 24)

            Mosaic {
                id: art
                x: 8
                y: 8
                width: 160
                height: 160
                tiles: page.genre.tiles
            }
            Text {
                id: kicker
                x: art.x + art.width + 28
                y: art.y + 18
                text: qsTr("Genre")
                color: Theme.cell
                font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.6; capitalization: Font.AllUppercase }
            }
            Text {
                id: name
                x: kicker.x
                anchors.top: kicker.bottom
                anchors.topMargin: 4
                width: head.width - x - 12
                elide: Text.ElideRight
                text: page.genre.name
                color: Theme.text
                font { family: Theme.sans; pixelSize: 36; weight: Font.Bold }
            }
            Text {
                id: genreDetail
                x: kicker.x
                anchors.top: name.bottom
                anchors.topMargin: 2
                width: Math.min(implicitWidth, head.width - x - 12 - (average.visible ? average.width + 12 : 0))
                elide: Text.ElideRight
                text: page.genre.detail
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13 }
            }
            Average {  // the average of its rated songs (R10.1)
                id: average
                objectName: "genreAverage"
                x: genreDetail.x + genreDetail.width + 12
                anchors.verticalCenter: genreDetail.verticalCenter
                value: page.genre.average
            }
            Row {
                id: buttons
                x: kicker.x
                anchors.top: genreDetail.bottom
                anchors.topMargin: 16
                spacing: 10
                Btn {
                    objectName: "genrePlay"
                    label: qsTr("Play all")
                    icon: "play"
                    primary: true
                    later: page.library.playNote  // the root isn't there (R2.10)
                    onClicked: page.player.playGenre(page.genre.name)
                }
                Btn {
                    id: genreMore
                    objectName: "genrePageMore"
                    width: 36
                    label: ""
                    icon: "more"
                    Accessible.name: qsTr("More for this genre")
                    onClicked: genreMenu.openFor(page.genre.name, genreMore, 0, genreMore.height)
                }
            }

            Text {
                id: albumsTitle
                x: 8
                y: art.y + art.height + 28
                visible: albumsRepeater.count > 0
                text: qsTr("Albums")
                color: Theme.text
                font { family: Theme.sans; pixelSize: 17; weight: Font.Bold }
            }
            Flow {
                id: albumsFlow
                x: 8
                y: albumsTitle.y + (albumsRepeater.count ? albumsTitle.height + 14 : 0)
                width: head.width - 16
                spacing: 22
                Repeater {
                    id: albumsRepeater
                    model: page.genre.albums
                    delegate: AlbumTile {
                        required property int albumId
                        width: 150
                        onOpen: page.library.openAlbum(albumId)
                        onPlay: page.player.playAlbum(albumId)
                        onImageDropped: (urls) => { if (page.art) page.art.dropOnAlbum(albumId, urls) }
                        DragSource { dragging: page.dragging; onCarry: page.dragging.carryAlbum(albumId) }
                    }
                }
            }
            Text {
                id: songsHeading
                x: 8
                y: albumsFlow.y + albumsFlow.height + 24
                visible: text !== ""
                text: page.genre.songsTitle
                color: Theme.text
                font { family: Theme.sans; pixelSize: 17; weight: Font.Bold }
            }
            Repeater {
                model: page.genre.songsTitle ? [["#", 0], [qsTr("TITLE"), 1], [qsTr("ALBUM"), 2], [qsTr("RATING"), 3], [qsTr("PLAYS"), 4], [qsTr("TIME"), 5]] : []
                Text {
                    required property var modelData
                    x: page.columns[modelData[1]][0]
                    y: songsHeading.y + songsHeading.height + 10
                    width: page.columns[modelData[1]][1]
                    height: 22
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: modelData[1] === 0 || modelData[1] >= 4 ? Text.AlignRight : Text.AlignLeft
                    text: modelData[0]
                    color: Theme.faint
                    font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4 }
                }
            }
        }
        delegate: TrackRow {
            required property int index
            width: list.width
            columns: page.columns
            showAlbum: true
            focused: page.activeFocus
            onTapped: (modifiers) => page.tapped(index, modifiers)
            onActivated: page.player.playFrom(page.songs, index)
            onMenu: songMenu.openFor(page.songs, index)
            onRated: (star) => { if (page.ratings) page.ratings.rateRow(page.songs, index, star) }
            DragSource { dragging: page.dragging; onCarry: page.dragging.carry(page.songs, index) }
        }
        ScrollBar.vertical: ScrollBar { }
    }
    Text {  // a search that found none of its albums or songs (R2.7)
        objectName: "empty"
        anchors.horizontalCenter: parent.horizontalCenter
        y: 260
        width: Math.min(implicitWidth, page.width - 56)
        elide: Text.ElideRight
        visible: text !== ""
        text: page.library.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 14 }
    }
    SongMenu { id: songMenu; player: page.player; edit: page.edit; removing: page.removing; playlists: page.playlists; playlistList: page.library.playlists }
    GenreMenu { id: genreMenu; library: page.library; player: page.player; genres: page.genres }
}
