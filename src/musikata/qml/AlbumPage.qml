import QtQuick
import QtQuick.Controls.Basic
import "."

// An album's page (R2.6, L02-album), under the header (R6.4) with its way back and the search box,
// which filters its songs (R2.7): the cover, the line over the title, the title,
// the artist (a click opens their page), songs, length and format; Play and Shuffle, and Edit tags
// and Album art, which come with later slices (the Edit tags panel, album art); the album's state
// chips; and its songs. Play plays the album from its first song, Shuffle from one at random, the
// rest shuffled (R7.1, R7.3); a song's double click plays it and the rest after it, its right click
// opens its menu (R7.2).
Item {
    id: page
    required property var library
    required property var player
    readonly property var album: library.album
    readonly property bool loading: art.loading

    Cover {
        id: art
        x: 28
        y: 8
        width: 220
        height: 220
        radius: 12
        sourceSide: 512
        source: page.album.cover
    }

    Item {
        id: about
        x: art.x + art.width + 32
        y: art.y
        width: page.width - x - 28
        height: art.height

        Text {
            id: kicker
            y: 18
            width: about.width
            elide: Text.ElideRight
            text: page.album.kicker
            color: Theme.cell
            font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.6; capitalization: Font.AllUppercase }
        }
        Text {
            id: title
            anchors.top: kicker.bottom
            anchors.topMargin: 4
            width: about.width
            elide: Text.ElideRight
            text: page.album.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: 36; weight: Font.Bold }
        }
        Text {
            id: artist
            objectName: "artistName"
            anchors.top: title.bottom
            width: Math.min(implicitWidth, about.width)
            elide: Text.ElideRight
            text: page.album.artist
            color: artistHover.hovered ? Theme.accentHi : Theme.text
            font { family: Theme.sans; pixelSize: 17; weight: Font.DemiBold }
            Accessible.role: Accessible.Link
            Accessible.name: text
            HoverHandler { id: artistHover; cursorShape: Qt.PointingHandCursor; enabled: page.album.artistId >= 0 }
            TapHandler { enabled: page.album.artistId >= 0; onTapped: page.library.openArtist(page.album.artistId) }
        }
        Text {
            id: detail
            anchors.top: artist.bottom
            anchors.topMargin: 4
            width: about.width
            elide: Text.ElideRight
            text: page.album.detail
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 13 }
        }
        Row {
            id: buttons
            anchors.top: detail.bottom
            anchors.topMargin: 18
            spacing: 10
            Btn {
                objectName: "play"
                label: qsTr("Play")
                icon: "play"
                primary: true
                later: page.library.playNote  // the root isn't there (R2.10)
                onClicked: page.player.playAlbum(page.album.id)
            }
            Btn {
                objectName: "shuffleAlbum"
                label: qsTr("Shuffle")
                icon: "shuffle"
                later: page.library.playNote
                onClicked: page.player.shuffleAlbum(page.album.id)
            }
            Btn { label: qsTr("Edit tags"); icon: "genre"; later: qsTr("Editing tags comes in a later version") }
            Btn { label: qsTr("Album art"); icon: "image"; later: qsTr("Album art comes in a later version") }
        }
        Row {
            anchors.top: buttons.bottom
            anchors.topMargin: 14
            spacing: 8
            Repeater {
                model: page.album.chips
                Chip {
                    required property var modelData
                    label: modelData.text
                    tone: modelData.tone
                }
            }
        }
    }

    Item {
        id: table
        x: 20
        y: art.y + art.height + 24
        width: page.width - 36
        height: page.height - y

        // [x, width] of each column: #, title, (unused), rating, time
        readonly property real gap: 16
        readonly property var columns: [
            [12, 28],
            [56, Math.max(0, width - 56 - 16 - 90 - 16 - 56 - 12)],
            [0, 0],
            [width - 12 - 56 - 16 - 90, 90],
            [width - 12 - 56, 56],
        ]

        Repeater {
            model: [["#", 0], [qsTr("TITLE"), 1], [qsTr("RATING"), 3], [qsTr("TIME"), 4]]
            Text {
                required property var modelData
                x: table.columns[modelData[1]][0]
                width: table.columns[modelData[1]][1]
                height: 32
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: modelData[1] === 0 || modelData[1] === 4 ? Text.AlignRight : Text.AlignLeft
                text: modelData[0]
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4 }
            }
        }
        Rectangle { y: 32; width: table.width; height: 1; color: Theme.border }

        ListView {
            id: songs
            objectName: "albumSongs"
            y: 38
            width: table.width
            height: table.height - y
            clip: true
            reuseItems: true
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            model: page.album.songs
            delegate: TrackRow {
                required property int index
                width: songs.width
                columns: table.columns
                onActivated: page.player.playFrom(page.album.songs, index)
                onMenu: songMenu.openFor(page.album.songs, index)
            }
            ScrollBar.vertical: ScrollBar { }
        }
        Text {  // a search that found none of its songs (R2.7)
            objectName: "empty"
            anchors.horizontalCenter: parent.horizontalCenter
            y: songs.y + 40
            width: Math.min(implicitWidth, table.width - 56)
            elide: Text.ElideRight
            visible: text !== ""
            text: page.library.emptyText
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }
    }
    SongMenu { id: songMenu; player: page.player }
}
