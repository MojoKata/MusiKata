import QtQuick
import QtQuick.Controls.Basic
import "."

// Add to playlist (R2.9.6, L03, L07): a menu of the playlists, by name, and New playlist…; each adds
// the songs the list's selection stands for (`row` -1), or the row right-clicked (its own row, or
// the selection when the row is in it), at the playlist's end; New playlist… makes one holding them,
// its name selected for editing in the sidebar (R8.3). A smart playlist is listed faded: its rule
// chooses its songs (R8.9). Its own menu, or a submenu of SongMenu.
Menu {
    id: menu
    required property var playlists   // the bridge that changes them (musikata.playlists)
    required property var list        // the sidebar's list of them (library.playlists)
    property var songs: null           // the list's model
    property int row: -1
    title: qsTr("Add to playlist")

    function openFor(songs, row, parent, x, y) {
        menu.songs = songs
        menu.row = row
        menu.popup(parent, x, y)
    }

    Instantiator {
        model: menu.list
        delegate: MenuItem {
            required property int playlistId
            required property string name
            required property bool smart
            objectName: "addTo-" + name
            text: name
            enabled: !smart
            onTriggered: menu.playlists.addTo(playlistId, menu.songs, menu.row)
        }
        onObjectAdded: (index, object) => menu.insertItem(index, object)
        onObjectRemoved: (index, object) => menu.removeItem(object)
    }
    MenuSeparator { visible: menu.list !== null && menu.list.count > 0 }
    MenuItem {
        objectName: "addToNew"
        text: qsTr("New playlist…")
        onTriggered: menu.playlists.createFrom(menu.songs, menu.row)
    }
}
