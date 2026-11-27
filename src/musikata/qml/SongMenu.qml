import QtQuick
import QtQuick.Controls.Basic
import "."

// A song list's right-click menu (R7.2): Play next and Add to queue, for the row it was opened on
// (a folder's row stands for its songs), or in a list of songs for the whole selection when that
// row is in it (the model's songs_at decides); Edit tags (R4.2, R2.9.6), the same way, when the
// view gives it the panel; Infer from path (R3.1, R2.9.6), the same way, when the view gives it the
// dialog; and in Folders, Album art (R5.2, R2.9.6) when those songs are one album (the model's
// albumAt says which). The rest of R2.9.6's comes with the slices that build them.
Menu {
    id: menu
    required property var player
    property var edit: null           // the Edit tags panel's bridge
    property var infer: null          // Infer from path's dialog
    property var art: null            // the Album art dialog's bridge, in Folders
    property var songs                 // the list's model: what a row's songs are
    property int row: -1
    property int album: -1             // the album the row's songs are on, -1 for none

    function openFor(songs, row) {
        menu.songs = songs
        menu.row = row
        menu.album = menu.art !== null ? songs.albumAt(row) : -1
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
    MenuItem {
        objectName: "inferRow"
        text: qsTr("Infer from path")
        visible: menu.infer !== null
        height: visible ? implicitHeight : 0
        onTriggered: menu.infer.openRow(menu.songs, menu.row)
    }
    MenuItem {
        objectName: "albumArtRow"
        text: qsTr("Album art")
        visible: menu.album >= 0
        height: visible ? implicitHeight : 0
        onTriggered: menu.art.openAlbum(menu.album)
    }
}
