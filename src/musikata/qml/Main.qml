import QtQuick
import "."

// The main window (R6.1): the sidebar, and the open view or page (R2.6), as the library says, a view
// under its header (R6.4); `/` opens the header's search (R2.7, R6.9). The now-playing bar (R6.5)
// comes with slice 4.
Window {
    id: win
    required property var library
    required property var player
    width: 1280
    height: 800
    minimumWidth: 960
    minimumHeight: 600
    title: "MusiKata"
    color: Theme.bg

    Sidebar {
        id: sidebar
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        library: win.library
    }
    ViewHeader {
        id: header
        objectName: "header"
        anchors { left: sidebar.right; right: parent.right; top: parent.top }
        visible: win.library.searchable
        library: win.library
    }
    Shortcut {
        sequence: "/"
        enabled: win.library.searchable
        onActivated: header.openSearch()
    }
    Loader {
        id: view
        objectName: "view"
        anchors {
            left: sidebar.right; right: parent.right; bottom: parent.bottom
            top: win.library.searchable ? header.bottom : parent.top
        }
        sourceComponent: ({
            albums: albums, album: album, artists: artists, artist: artist, songs: songs,
            folders: folders
        })[win.library.view]
    }
    Component { id: albums; AlbumsView { library: win.library; player: win.player } }
    Component { id: album; AlbumPage { library: win.library; player: win.player } }
    Component { id: artists; ArtistsView { library: win.library } }
    Component { id: artist; ArtistPage { library: win.library; player: win.player } }
    Component { id: songs; SongsView { library: win.library; player: win.player } }
    Component { id: folders; FoldersView { library: win.library } }
}
