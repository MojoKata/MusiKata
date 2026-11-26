import QtQuick
import QtQuick.Dialogs
import "."

// The main window (R6.1): the sidebar, and the open view or page (R2.6), as the library says, a view
// under its header (R6.4); `/` opens the header's search (R2.7, R6.9). Over the view, the banner of
// a root or linked folder that isn't there (R2.10, X02-root-unavailable), with Try again and Choose
// another folder… (the platform's folder dialog), and the question of songs gone (R2.10.1). The
// title names a root given for this run only (R2.1.2). The now-playing bar (R6.5) comes with
// slice 4.
Window {
    id: win
    required property var library
    required property var player
    width: 1280
    height: 800
    minimumWidth: 960
    minimumHeight: 600
    title: win.library.windowTitle
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
    Column {
        id: banners
        anchors {
            left: sidebar.right; right: parent.right; leftMargin: 28; rightMargin: 28
            top: win.library.searchable ? header.bottom : parent.top
            topMargin: banners.height > 0 ? 8 : 0
        }
        spacing: 8
        Banner {
            objectName: "rootBanner"
            width: banners.width
            visible: win.library.banner.title !== undefined
            tone: "err"
            title: win.library.banner.title || ""
            detail: win.library.banner.detail || ""
            Btn {
                objectName: "tryAgain"
                label: qsTr("Try again")
                icon: "refresh"
                height: 34
                onClicked: win.library.retry()
            }
            Btn {
                objectName: "chooseAnother"
                label: qsTr("Choose another folder…")
                icon: "folder"
                quiet: true
                height: 34
                visible: win.library.banner.choose === true
                onClicked: pick.open()
            }
        }
        Banner {
            objectName: "question"
            width: banners.width
            visible: win.library.question.text !== undefined
            tone: "warn"
            title: win.library.question.text || ""
            Btn {
                objectName: "keepMissing"
                label: win.library.question.keep || ""
                height: 34
                onClicked: win.library.keepMissing()
            }
            Btn {
                objectName: "removeMissing"
                label: win.library.question.remove || ""
                height: 34
                onClicked: win.library.removeMissing()
            }
        }
    }
    FolderDialog {
        id: pick
        title: qsTr("Choose your music folder")
        onAccepted: win.library.chooseRoot(selectedFolder.toString())
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
            top: banners.bottom
            topMargin: banners.height > 0 ? 12 : 0
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
