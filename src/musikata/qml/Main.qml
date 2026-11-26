import QtQuick
import "."

// The main window (R6.1): the sidebar, and the open view or page (R2.6), as the library says. The
// now-playing bar (R6.5) comes with slice 4, the header's search and sort with slice 3.2.
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
    Loader {
        id: view
        objectName: "view"
        anchors { left: sidebar.right; right: parent.right; top: parent.top; bottom: parent.bottom }
        sourceComponent: ({
            albums: albums, album: album, artists: artists, artist: artist, songs: songs
        })[win.library.view]
    }
    Component { id: albums; AlbumsView { library: win.library; player: win.player } }
    Component { id: album; AlbumPage { library: win.library; player: win.player } }
    Component { id: artists; ArtistsView { library: win.library } }
    Component { id: artist; ArtistPage { library: win.library; player: win.player } }
    Component { id: songs; SongsView { library: win.library; player: win.player } }
}
