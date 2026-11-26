import QtQuick
import QtQuick.Dialogs
import "."

// The main window (R6.1): the sidebar, and the open view or page (R2.6), as the library says, either
// under its header (R6.4); `/` opens the header's search (R2.7, R6.9). Over the view, the banner of
// a root or linked folder that isn't there (R2.10, X02-root-unavailable), with Try again and Choose
// another folder… (the platform's folder dialog), and the question of songs gone (R2.10.1). The
// title names a root given for this run only (R2.1.2). The now-playing bar (R6.5) runs along the
// bottom, and Up next (R7.2) opens over the view's right side above it. Space plays and pauses,
// Ctrl+→ and Ctrl+← (⌘ on macOS) go to the next song and the one before, and ← and → seek 5 seconds
// (R6.9, R7.4), unless what has the focus uses them: a text box, the Folders view's grid, the
// volume. ⋮ › Change history docks its panel on the right (R4.9), Ctrl+Z (⌘Z) undoes the most
// recent save unless a text box takes it, and the message that follows a save or an undo, with its
// Undo, shows at the foot of the view (R6.7). Edit tags (R4.2) docks its panel in the same place,
// under Change history while that is open; Ctrl+E (⌘E) opens it on the open view's selection, and
// the views open it from their buttons, selection bars and right-click menus.
Window {
    id: win
    required property var library
    required property var player
    required property var history
    required property var edit
    width: 1280
    height: 800
    minimumWidth: 960
    minimumHeight: 600
    title: win.library.windowTitle
    color: Theme.bg

    Sidebar {
        id: sidebar
        anchors { left: parent.left; top: parent.top; bottom: bar.top }
        library: win.library
    }
    ViewHeader {
        id: header
        objectName: "header"
        anchors { left: sidebar.right; right: dock.left; top: parent.top }
        visible: win.library.searchable
        library: win.library
        history: win.history
    }
    Item {  // the panel docked on the right: Change history over Edit tags
        id: dock
        anchors { right: parent.right; top: parent.top; bottom: bar.top }
        width: win.history.opened || win.edit.opened ? Math.min(380, Math.max(320, win.width * 0.3)) : 0
        EditTagsPanel {
            objectName: "editPanel"
            anchors.fill: parent
            visible: win.edit.opened && !win.history.opened
            focus: visible
            edit: win.edit
        }
        ChangeHistoryPanel {
            objectName: "historyPanel"
            anchors.fill: parent
            visible: win.history.opened
            history: win.history
        }
    }
    Column {
        id: banners
        anchors {
            left: sidebar.right; right: dock.left; leftMargin: 28; rightMargin: 28
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
            left: sidebar.right; right: dock.left; bottom: bar.top
            top: banners.bottom
            topMargin: banners.height > 0 ? 12 : 0
        }
        sourceComponent: ({
            albums: albums, album: album, artists: artists, artist: artist, songs: songs,
            folders: folders
        })[win.library.view]
    }
    Component { id: albums; AlbumsView { library: win.library; player: win.player } }
    Component { id: album; AlbumPage { library: win.library; player: win.player; edit: win.edit } }
    Component { id: artists; ArtistsView { library: win.library } }
    Component { id: artist; ArtistPage { library: win.library; player: win.player; edit: win.edit } }
    Component { id: songs; SongsView { library: win.library; player: win.player; edit: win.edit } }
    Component { id: folders; FoldersView { objectName: "foldersView"; library: win.library; player: win.player; edit: win.edit } }

    UpNext {
        objectName: "upNext"
        anchors { right: parent.right; bottom: bar.top; rightMargin: 16; bottomMargin: 12 }
        width: Math.min(420, win.width - sidebar.width - 32)
        height: Math.max(200, bar.y - 12 - 76)
        visible: win.player.upNextOpen
        player: win.player
    }
    MessageBar {
        objectName: "message"
        anchors { horizontalCenter: view.horizontalCenter; bottom: bar.top; bottomMargin: 16 }
        maxWidth: view.width - 48
        history: win.history
    }
    NowPlayingBar {
        id: bar
        objectName: "nowPlayingBar"
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        player: win.player
    }
    Shortcut {
        sequence: "Ctrl+E"
        onActivated: win.edit.editCurrent(win.library)
    }
    Shortcut {
        sequences: [StandardKey.Undo]
        onActivated: win.history.undoLast()
    }
    Shortcut {
        sequence: "Space"
        onActivated: win.player.toggle()
    }
    Shortcut {
        sequence: "Ctrl+Right"
        onActivated: win.player.next()
    }
    Shortcut {
        sequence: "Ctrl+Left"
        onActivated: win.player.previous()
    }
    Shortcut {
        sequence: "Left"
        onActivated: win.player.seekBack()
    }
    Shortcut {
        sequence: "Right"
        onActivated: win.player.seekAhead()
    }
}
