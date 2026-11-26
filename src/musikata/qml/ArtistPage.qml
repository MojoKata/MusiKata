import QtQuick
import QtQuick.Controls.Basic
import "."

// An artist's page (R2.6, L11-artist), under the header (R6.4) with its way back and the search box,
// which filters their albums and songs (R2.7): their mosaic, name, albums and songs; their albums,
// by year; then their songs on others' albums and on none.
Item {
    id: page
    required property var library
    required property var player
    readonly property var artist: library.artist

    // [x, width] of the song columns: #, title, album, rating, time
    readonly property var columns: {
        const w = list.width
        const free = Math.max(0, w - 12 - 28 - 16 - 16 - 90 - 16 - 56 - 12 - 16)
        return [[12, 28], [56, free * 0.55], [56 + free * 0.55 + 16, free * 0.45],
                [w - 12 - 56 - 16 - 90, 90], [w - 12 - 56, 56]]
    }

    ListView {
        id: list
        objectName: "artistSongs"
        x: 20
        width: page.width - 36
        height: page.height
        clip: true
        reuseItems: true
        spacing: 2
        boundsBehavior: Flickable.StopAtBounds
        model: page.artist.others
        header: Item {
            id: head
            width: list.width
            height: albumsFlow.y + albumsFlow.height + (page.artist.othersTitle ? 76 : 24)

            Mosaic {
                id: art
                x: 8
                y: 8
                width: 160
                height: 160
                tiles: page.artist.tiles
            }
            Text {
                id: kicker
                x: art.x + art.width + 28
                y: art.y + 34
                text: qsTr("Artist")
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
                text: page.artist.name
                color: Theme.text
                font { family: Theme.sans; pixelSize: 36; weight: Font.Bold }
            }
            Text {
                x: kicker.x
                anchors.top: name.bottom
                anchors.topMargin: 2
                width: head.width - x - 12
                elide: Text.ElideRight
                text: page.artist.detail
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13 }
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
                    model: page.artist.albums
                    delegate: AlbumTile {
                        required property int albumId
                        width: 150
                        onOpen: page.library.openAlbum(albumId)
                        onPlay: page.player.playAlbum(albumId)
                    }
                }
            }
            Text {
                id: othersTitle
                x: 8
                y: albumsFlow.y + albumsFlow.height + 24
                visible: text !== ""
                text: page.artist.othersTitle
                color: Theme.text
                font { family: Theme.sans; pixelSize: 17; weight: Font.Bold }
            }
            Repeater {
                model: page.artist.othersTitle ? [["#", 0], [qsTr("TITLE"), 1], [qsTr("ALBUM"), 2], [qsTr("RATING"), 3], [qsTr("TIME"), 4]] : []
                Text {
                    required property var modelData
                    x: page.columns[modelData[1]][0]
                    y: othersTitle.y + othersTitle.height + 10
                    width: page.columns[modelData[1]][1]
                    height: 22
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: modelData[1] === 0 || modelData[1] === 4 ? Text.AlignRight : Text.AlignLeft
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
            onActivated: page.player.playFrom(page.artist.others, index)
            onMenu: songMenu.openFor(page.artist.others, index)
        }
        ScrollBar.vertical: ScrollBar { }
    }
    Text {  // a search that found none of their albums or songs (R2.7)
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
    SongMenu { id: songMenu; player: page.player }
}
