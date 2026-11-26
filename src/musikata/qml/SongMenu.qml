import QtQuick
import QtQuick.Controls.Basic
import "."

// A song list's right-click menu (R7.2): Play next and Add to queue, for the row it was opened on
// (a folder's row stands for its songs), or in a list of songs for the whole selection when that
// row is in it (the model's songs_at decides); and Edit tags (R4.2, R2.9.6), the same way, when the
// view gives it the panel. The rest of R2.9.6's comes with the slices that build them.
Menu {
    id: menu
    required property var player
    property var edit: null           // the Edit tags panel's bridge
    property var songs                 // the list's model: what a row's songs are
    property int row: -1

    function openFor(songs, row) {
        menu.songs = songs
        menu.row = row
        menu.popup()
    }

    MenuItem {
        objectName: "playNext"
        text: qsTr("Play next")
        onTriggered: menu.player.playNext(menu.songs, menu.row)
    }
    MenuItem {
        objectName: "addToQueue"
        text: qsTr("Add to queue")
        onTriggered: menu.player.addToQueue(menu.songs, menu.row)
    }
    MenuItem {
        objectName: "editTags"
        text: qsTr("Edit tags")
        visible: menu.edit !== null
        height: visible ? implicitHeight : 0
        onTriggered: menu.edit.editRow(menu.songs, menu.row)
    }
}
