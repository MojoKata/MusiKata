import QtQuick
import QtQuick.Controls.Basic
import "."

// The selection bar (R2.9.6, L06-folders-cards; L03-songs-bulk-edit): what is selected, "2 folders ·
// 21 songs selected", "4 selected"; its first action, Play in Folders (the songs selected, from the
// first, R7.1) or Play next in Songs (R7.2); Edit tags (R4.2) and Infer from path (R3.1), said by
// `act`, Edit tags left out while the panel already edits the selection (`editing`); Add to
// playlist, its menu of the playlists over the bar when the view gives it `playlists` (R8); the
// actions of later slices (Organize…) faded, saying so in their tooltips, those that don't fit left
// out from the last (L07-folders-list, the panel open beside it); and ✕, which clears it.
Rectangle {
    id: bar
    signal play()
    signal clear()
    signal act(string action)          // an action of `laterActions` that has one: "edit", "infer"
    required property string text
    property string playLabel: qsTr("Play")
    property string playObjectName: "playSelection"
    property var laterActions: []
    property bool editing: false       // the Edit tags panel is open
    property var playlists: null       // Add to playlist's bridge (musikata.playlists), and
    property var playlistList: null    // the playlists its menu lists (library.playlists),
    property var songs: null           // for the songs this list has selected
    readonly property real room: (parent ? parent.width - 32 : 100000) - 32
    // how many of `laterActions` fit, in order: the rest are left out
    readonly property int fits: {
        let used = said.width + playAction.width + clearButton.width + 2 * content.spacing
        let n = 0
        for (let i = 0; i < actions.count; i++) {
            const a = actions.itemAt(i)
            if (!a || a.byEdit)
                continue
            used += a.width + content.spacing
            if (used > bar.room)
                break
            n = i + 1
        }
        return n
    }
    width: Math.min(content.width + 32, parent ? parent.width - 32 : content.width + 32)
    height: 46
    radius: 12
    color: Theme.raised
    border.color: Theme.borderStrong
    property string playNote: ""  // why Play waits: the root isn't there (R2.10)
    Accessible.role: Accessible.ToolBar
    Accessible.name: bar.text

    component Action: Rectangle {
        id: action
        signal clicked()
        property string label
        property string icon
        property string later: ""
        readonly property bool available: later === ""
        width: actionRow.width + 16
        height: 32
        radius: 8
        color: actionHover.hovered && available ? Theme.hover : "transparent"
        opacity: available ? 1 : 0.45
        Accessible.role: Accessible.Button
        Accessible.name: label
        Accessible.description: later
        HoverHandler { id: actionHover; cursorShape: action.available ? Qt.PointingHandCursor : Qt.ArrowCursor }
        TapHandler { enabled: action.available; onTapped: action.clicked() }
        ToolTip.visible: actionHover.hovered && !available
        ToolTip.text: later
        ToolTip.delay: 400
        Row {
            id: actionRow
            anchors.centerIn: parent
            spacing: 6
            Icon { anchors.verticalCenter: parent.verticalCenter; name: action.icon; size: 15; color: Theme.accentHi }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: action.label
                color: Theme.accentHi
                font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
            }
        }
    }

    Row {
        id: content
        x: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6
        Text {
            id: said
            objectName: "selectionText"
            anchors.verticalCenter: parent.verticalCenter
            rightPadding: 10
            text: bar.text
            color: Theme.text
            font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
        }
        Action {
            id: playAction
            objectName: bar.playObjectName
            label: bar.playLabel
            icon: "play"
            later: bar.playNote
            onClicked: bar.play()
        }
        Repeater {
            id: actions
            model: bar.laterActions
            Action {
                id: barAction
                required property var modelData
                required property int index
                readonly property bool byEdit: modelData.action === "edit" && bar.editing
                objectName: modelData.action ? modelData.action + "Selection" : ""
                visible: !byEdit && index < bar.fits
                label: modelData.label
                icon: modelData.icon
                later: modelData.later
                onClicked: {
                    if (modelData.action === "playlist" && bar.playlists !== null)
                        addMenu.openFor(bar.songs, -1, barAction, 0, -addMenu.implicitHeight - 6)
                    else
                        bar.act(modelData.action || "")
                }
            }
        }
        Rectangle {
            id: clearButton
            objectName: "clearSelection"
            anchors.verticalCenter: parent.verticalCenter
            width: 28
            height: 28
            radius: 6
            color: clearHover.hovered ? Theme.hover : "transparent"
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("Clear the selection")
            HoverHandler { id: clearHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: bar.clear() }
            Icon { anchors.centerIn: parent; name: "close"; size: 14; color: Theme.muted }
        }
    }
    AddToPlaylistMenu {
        id: addMenu
        objectName: "addToPlaylistMenu"
        playlists: bar.playlists
        list: bar.playlistList
    }
}
