import QtQuick
import QtQuick.Controls.Basic
import "."

// A genre's ⋯ menu (R9.4, G01-genres), on its tile and on its page: Play all, from its first song
// in its page's order (R7.1); Rename… and Merge into…, each opening its dialog over the window with
// the preview of the files that change (musikata.genres); and Select its songs, its page with every
// song of it selected. Drawn as the mockup draws it: each item its icon and its label.
Menu {
    id: menu
    required property var library
    required property var player
    required property var genres
    property string genre: ""
    signal shut()

    function openFor(name, parent, x, y) {
        menu.genre = name
        menu.popup(parent, x, y)
    }
    onClosed: menu.shut()

    background: Rectangle {
        implicitWidth: 220
        radius: 10
        color: Theme.raised
        border.color: Theme.borderStrong
    }
    topPadding: 6
    bottomPadding: 6

    component Entry: MenuItem {
        id: item
        required property string iconName
        leftPadding: 16
        rightPadding: 16
        implicitHeight: 36
        contentItem: Row {
            spacing: 12
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                name: item.iconName
                size: 15
                color: Theme.muted
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: item.text
                color: item.enabled ? Theme.text : Theme.faint
                font { family: Theme.sans; pixelSize: 13 }
            }
        }
        background: Rectangle {
            x: 6
            width: item.width - 12
            radius: 7
            color: item.highlighted ? Theme.hover : "transparent"
        }
    }

    Entry {
        objectName: "genrePlayAll"
        text: qsTr("Play all")
        iconName: "play"
        enabled: menu.library.playNote === ""  // the root isn't there (R2.10)
        onTriggered: menu.player.playGenre(menu.genre)
    }
    Entry {
        objectName: "genreRename"
        text: qsTr("Rename…")
        iconName: "genre"
        enabled: menu.library.available
        onTriggered: menu.genres.rename(menu.genre)
    }
    Entry {
        objectName: "genreMerge"
        text: qsTr("Merge into…")
        iconName: "merge"
        enabled: menu.library.available
        onTriggered: menu.genres.mergeInto(menu.genre)
    }
    Entry {
        objectName: "genreSelect"
        text: qsTr("Select its songs")
        iconName: "check"
        onTriggered: menu.library.selectGenre(menu.genre)
    }
}
