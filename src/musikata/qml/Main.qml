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
// the views open it from their buttons, selection bars and right-click menus. A bulk tool of its ⋯
// menu (R4.5) opens its dialog over the whole window, as Album art (R5.2) does from an album's page,
// the panel's cover or an image dropped on an album's cover (R5.4). While a modal dialog is open over
// the window (`modal`: a bulk tool's, Album art's), the window's shortcuts don't act on what is
// behind it, nor does a click reach it. A genre's Rename… and Merge into… (R9.4) open the same
// dialog as a bulk tool, over the whole window, as Needs attention's Merge of an artist's or an
// album's names does (R2.8). Needs attention's Review… of a song's copies opens its dialog over the
// whole window (R2.12), and moving copies to the trash asks first, over it (R2.11). Fix encoding…
// (R4.10), from Needs attention or the Edit tags panel's ⋯ menu, opens its dialog over the whole
// window too, as Infer from path (R3) does from Folders, an album's page, the selection bars, the
// right-click menus, the panel's ⋯ menu and Needs attention. A star clicked
// in a list's row or the bar sets that song's rating, and Ctrl+0 to Ctrl+5 (⌘ on macOS) the
// selection's (R10.2). A playlist of the sidebar opens its page (R8.2, P01-playlist-drag); Delete
// playlist asks first, over the window (R8.4, R6.8); Find (R8.7) and Export… (R8.8) open their
// dialogs over the whole window, as New smart playlist… and Edit rule (R8.9) do. Songs, albums,
// artists, genres, folders and a playlist's entries are dragged from every view (R6.10) onto a
// playlist in the sidebar, within a playlist's page, onto Up next or the queue button, and out of
// MusiKata as their files; the drag's picture is a card kept off the window (DragCard), and files
// from another app dropped anywhere else are brought into the library (R12.5). Organize files (R12)
// opens its dialog over the whole window, from the header's ⋮ menu in Folders and on an album's
// page, the selection bars and the right-click menus, and for files dropped from outside. Move to
// trash (R2.11), from the right-click menus, an album's ⋯ menu, Folders' ⋮ menu and Delete in the
// library views, asks first over the window; Ignore this folder (R2.11.1) doesn't.
Window {
    id: win
    required property var library
    required property var player
    required property var history
    required property var edit
    required property var ratings
    required property var art
    required property var genres
    required property var attention
    required property var names
    required property var copies
    required property var encodings
    required property var infer
    required property var playlists
    required property var dragging
    required property var smart
    required property var organize
    required property var removing
    width: 1280
    height: 800
    minimumWidth: 960
    minimumHeight: 600
    title: win.library.windowTitle
    color: Theme.bg
    // a modal dialog is open over the window: its shortcuts are the dialog's, not the window's
    readonly property bool modal: win.edit.tool.opened || win.art.opened || win.genres.opened
                                  || win.names.opened || win.copies.opened
                                  || win.copies.question.title !== undefined
                                  || win.encodings.opened || win.infer.opened
                                  || win.playlists.opened || win.smart.opened
                                  || win.organize.opened
                                  || win.removing.question.title !== undefined

    DropArea {  // files from another app dropped anywhere else (R6.10): into the library (R12.5)
        objectName: "windowDrop"
        anchors.fill: parent
        enabled: !win.modal
        onEntered: (drag) => drag.accepted = win.dragging.enter("window", -1, drag.getDataAsString(win.dragging.mime), drag.urls)
        onExited: win.dragging.leave("window", -1)
        onDropped: (drop) => { if (win.dragging.drop("window", -1, drop.getDataAsString(win.dragging.mime), drop.urls)) drop.accept(Qt.CopyAction) }
    }
    DragCard {  // the drag's picture (musikata.dragging grabs it), off the window
        id: dragCard
        objectName: "dragCard"
        x: -width - 40
        Accessible.ignored: true  // a picture for the platform's drag, never seen in the window
        card: win.dragging.card
        Component.onCompleted: win.dragging.setCard(dragCard)
    }
    Sidebar {
        enabled: !win.modal  // nothing behind a dialog takes a click
        id: sidebar
        anchors { left: parent.left; top: parent.top; bottom: bar.top }
        library: win.library
        playlists: win.playlists
        dragging: win.dragging
        smart: win.smart
    }
    ViewHeader {
        enabled: !win.modal  // nothing behind a dialog takes a click
        id: header
        objectName: "header"
        anchors { left: sidebar.right; right: dock.left; top: parent.top }
        visible: win.library.searchable
        library: win.library
        history: win.history
        organize: win.organize
        removing: win.removing
    }
    Item {  // the panel docked on the right: Change history over Edit tags
        enabled: !win.modal  // nothing behind a dialog takes a click
        id: dock
        anchors { right: parent.right; top: parent.top; bottom: bar.top }
        width: win.history.opened || win.edit.opened ? Math.min(380, Math.max(320, win.width * 0.3)) : 0
        EditTagsPanel {
            objectName: "editPanel"
            anchors.fill: parent
            visible: win.edit.opened && !win.history.opened
            focus: visible
            edit: win.edit
            art: win.art
        }
        ChangeHistoryPanel {
            objectName: "historyPanel"
            anchors.fill: parent
            visible: win.history.opened
            history: win.history
        }
    }
    Column {
        enabled: !win.modal  // nothing behind a dialog takes a click
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
        enabled: win.library.searchable && !win.modal
        onActivated: header.openSearch()
    }
    Loader {
        enabled: !win.modal  // nothing behind a dialog takes a click
        id: view
        objectName: "view"
        anchors {
            left: sidebar.right; right: dock.left; bottom: bar.top
            top: banners.bottom
            topMargin: banners.height > 0 ? 12 : 0
        }
        sourceComponent: ({
            albums: albums, album: album, artists: artists, artist: artist, songs: songs,
            genres: genreList, genre: genre, folders: folders, attention: needs,
            playlist: playlist
        })[win.library.view]
    }
    Component { id: albums; AlbumsView { library: win.library; player: win.player; art: win.art; dragging: win.dragging } }
    Component { id: album; AlbumPage { library: win.library; player: win.player; edit: win.edit; ratings: win.ratings; art: win.art; infer: win.infer; playlists: win.playlists; dragging: win.dragging; organize: win.organize; removing: win.removing } }
    Component { id: artists; ArtistsView { library: win.library; dragging: win.dragging } }
    Component { id: artist; ArtistPage { library: win.library; player: win.player; edit: win.edit; ratings: win.ratings; art: win.art; playlists: win.playlists; dragging: win.dragging; removing: win.removing } }
    Component { id: genreList; GenresView { library: win.library; player: win.player; genres: win.genres; dragging: win.dragging } }
    Component { id: genre; GenrePage { library: win.library; player: win.player; edit: win.edit; ratings: win.ratings; art: win.art; genres: win.genres; playlists: win.playlists; dragging: win.dragging; removing: win.removing } }
    Component { id: songs; SongsView { library: win.library; player: win.player; edit: win.edit; ratings: win.ratings; infer: win.infer; playlists: win.playlists; dragging: win.dragging; organize: win.organize; removing: win.removing } }
    Component { id: needs; AttentionView { library: win.library; attention: win.attention; copies: win.copies } }
    Component { id: folders; FoldersView { objectName: "foldersView"; library: win.library; player: win.player; edit: win.edit; ratings: win.ratings; art: win.art; infer: win.infer; playlists: win.playlists; dragging: win.dragging; organize: win.organize; attention: win.attention; removing: win.removing } }
    Component { id: playlist; PlaylistPage { objectName: "playlistPage"; library: win.library; player: win.player; edit: win.edit; ratings: win.ratings; infer: win.infer; playlists: win.playlists; dragging: win.dragging; smart: win.smart; removing: win.removing } }

    UpNext {
        enabled: !win.modal  // nothing behind a dialog takes a click
        objectName: "upNext"
        anchors { right: parent.right; bottom: bar.top; rightMargin: 16; bottomMargin: 12 }
        width: Math.min(420, win.width - sidebar.width - 32)
        height: Math.max(200, bar.y - 12 - 76)
        visible: win.player.upNextOpen
        player: win.player
        dragging: win.dragging
    }
    MessageBar {
        enabled: !win.modal  // nothing behind a dialog takes a click
        objectName: "message"
        anchors { horizontalCenter: view.horizontalCenter; bottom: bar.top; bottomMargin: 16 }
        maxWidth: view.width - 48
        history: win.history
    }
    NowPlayingBar {
        enabled: !win.modal  // nothing behind a dialog takes a click
        id: bar
        objectName: "nowPlayingBar"
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        player: win.player
        ratings: win.ratings
        dragging: win.dragging
    }
    ToolDialog {
        objectName: "toolOverlay"
        anchors.fill: parent
        tool: win.genres.opened ? win.genres : win.names.opened ? win.names : win.edit.tool  // never two: each is modal
    }
    AlbumArtDialog {
        objectName: "artOverlay"
        anchors.fill: parent
        art: win.art
    }
    ReviewDialog {
        objectName: "reviewOverlay"
        anchors.fill: parent
        copies: win.copies
    }
    CopiesQuestion {
        objectName: "questionOverlay"
        anchors.fill: parent
        copies: win.copies
    }
    FixEncodingDialog {
        objectName: "fixOverlay"
        anchors.fill: parent
        fix: win.encodings
    }
    InferDialog {
        objectName: "inferOverlay"
        anchors.fill: parent
        infer: win.infer
    }
    OrganizeDialog {
        objectName: "organizeOverlay"
        anchors.fill: parent
        organize: win.organize
    }
    FindDialog {
        objectName: "findOverlay"
        anchors.fill: parent
        playlists: win.playlists
    }
    ExportDialog {
        objectName: "exportOverlay"
        anchors.fill: parent
        playlists: win.playlists
    }
    SmartRuleDialog {  // New smart playlist… and Edit rule (R8.9)
        objectName: "smartOverlay"
        anchors.fill: parent
        smart: win.smart
    }
    CopiesQuestion {  // Delete playlist's question (R8.4, R6.8)
        objectName: "playlistQuestion"
        anchors.fill: parent
        copies: win.playlists
    }
    CopiesQuestion {  // Move to trash's question (R2.11, R6.8)
        objectName: "removingQuestion"
        anchors.fill: parent
        copies: win.removing
    }
    Shortcut {
        sequence: "Ctrl+E"
        enabled: !win.modal
        onActivated: win.edit.editCurrent(win.library)
    }
    Repeater {  // Ctrl+0 to Ctrl+5 (⌘ on macOS) rate the selection, Ctrl+0 clearing it (R10.2)
        model: 6
        Item {
            id: rateKey
            required property int index
            Shortcut {
                sequence: "Ctrl+" + rateKey.index
                enabled: !win.modal
                onActivated: win.ratings.rateSelection(win.library, rateKey.index)
            }
        }
    }
    Shortcut {
        sequences: [StandardKey.Undo]
        enabled: !win.modal
        onActivated: win.history.undoLast()
    }
    Shortcut {
        sequence: "Space"
        enabled: !win.modal
        onActivated: win.player.toggle()
    }
    Shortcut {
        sequence: "Ctrl+Right"
        enabled: !win.modal
        onActivated: win.player.next()
    }
    Shortcut {
        sequence: "Ctrl+Left"
        enabled: !win.modal
        onActivated: win.player.previous()
    }
    Shortcut {
        sequence: "Left"
        enabled: !win.modal
        onActivated: win.player.seekBack()
    }
    Shortcut {
        sequence: "Right"
        enabled: !win.modal
        onActivated: win.player.seekAhead()
    }
}
