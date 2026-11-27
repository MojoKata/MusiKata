import QtQuick
import QtQuick.Controls.Basic
import "."

// A song list's right-click menu (R7.2): Play next and Add to queue, for the row it was opened on
// (a folder's row stands for its songs), or in a list of songs for the whole selection when that
// row is in it (the model's songs_at decides); Edit tags (R4.2, R2.9.6), the same way, when the
// view gives it the panel; Infer from path (R3.1, R2.9.6), the same way, when the view gives it the
// dialog; and in Folders, Album art (R5.2, R2.9.6) when those songs are one album (the model's
// albumAt says which). With `playlists` (R8): Add to playlist, its submenu of the playlists, and New
// playlist from selection (R8.3), the same way; on a playlist's page (`inPlaylist`), Remove from
// playlist (R8.6). Organize files… (R12.2, R2.9.6), the same way, when the view gives it the
// dialog; and in Folders, Show in file manager (R2.9.6), the row's folder or file shown there.
// Move to trash (R2.11), the same way, when the view gives it `removing`, asked first; and on a
// folder's row in Folders, Ignore this folder (R2.11.1).
Menu {
    id: menu
    required property var player
    property var edit: null           // the Edit tags panel's bridge
    property var infer: null          // Infer from path's dialog
    property var art: null            // the Album art dialog's bridge, in Folders
    property var organize: null       // Organize files' dialog (R12.2)
    property var reveal: null         // Show in file manager (R2.9.6): Needs attention's bridge
    property var removing: null       // Move to trash and Ignore this folder (R2.11, R2.11.1)
    property var playlists: null      // the playlists' bridge (musikata.playlists)
    property var playlistList: null   // the playlists Add to playlist lists (library.playlists)
    property bool inPlaylist: false   // a playlist's page: Remove from playlist (R8.6)
    property var songs                 // the list's model: what a row's songs are
    property int row: -1
    property int album: -1             // the album the row's songs are on, -1 for none
    property string folder: ""         // the folder the row is in Folders, "" for a file's

    function openFor(songs, row) {
        menu.songs = songs
        menu.row = row
        menu.album = menu.art !== null ? songs.albumAt(row) : -1
        menu.folder = menu.removing !== null ? menu.removing.folderAt(songs, row) : ""
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
    AddToPlaylistMenu {
        id: addMenu
        objectName: "addToPlaylist"
        enabled: menu.playlists !== null
        playlists: menu.playlists
        list: menu.playlistList
        songs: menu.songs
        row: menu.row
    }
    MenuItem {
        objectName: "newFromSelection"
        text: qsTr("New playlist from selection")
        visible: menu.playlists !== null
        height: visible ? implicitHeight : 0
        onTriggered: menu.playlists.createFrom(menu.songs, menu.row)
    }
    MenuItem {
        objectName: "removeFromPlaylist"
        text: qsTr("Remove from playlist")
        visible: menu.playlists !== null && menu.inPlaylist
        height: visible ? implicitHeight : 0
        onTriggered: menu.playlists.removeRow(menu.songs, menu.row)
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
        objectName: "organizeRow"
        text: qsTr("Organize files…")
        visible: menu.organize !== null
        height: visible ? implicitHeight : 0
        onTriggered: menu.organize.openRow(menu.songs, menu.row)
    }
    MenuItem {
        objectName: "showInFileManager"
        text: qsTr("Show in file manager")
        visible: menu.reveal !== null
        height: visible ? implicitHeight : 0
        onTriggered: menu.reveal.showRow(menu.songs, menu.row)
    }
    MenuItem {
        objectName: "albumArtRow"
        text: qsTr("Album art")
        visible: menu.album >= 0
        height: visible ? implicitHeight : 0
        onTriggered: menu.art.openAlbum(menu.album)
    }
    MenuItem {
        objectName: "ignoreFolderRow"
        text: qsTr("Ignore this folder")
        visible: menu.folder !== ""
        height: visible ? implicitHeight : 0
        onTriggered: menu.removing.ignoreFolder(menu.folder)
    }
    MenuItem {
        objectName: "trashRow"
        text: qsTr("Move to trash")
        visible: menu.removing !== null
        height: visible ? implicitHeight : 0
        onTriggered: menu.removing.askRow(menu.songs, menu.row)
    }
}
