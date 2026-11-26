import QtQuick
import "."

// The main window (R6.1): the sidebar, and the open view. The now-playing bar (R6.5) comes with
// playback, the header's search and sort with slice 3.
Window {
    id: win
    required property var library
    property var tourStep: ({})         // what the tour shows (A1.6): {"view": "songs"}
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
    SongsView {
        anchors { left: sidebar.right; right: parent.right; top: parent.top; bottom: parent.bottom }
        library: win.library
    }
}
