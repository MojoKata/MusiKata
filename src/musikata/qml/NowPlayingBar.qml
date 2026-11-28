import QtQuick
import QtQuick.Controls.Basic
import MusiKata
import "."

// The now-playing bar (R6.5, L01-albums), the full width along the bottom: on the left the song's
// cover, title, artist and album and its rating, set by its stars (R10.2); in the centre
// shuffle, previous, play/pause, next and repeat (R7.3), and under them the time played, the seek
// bar and the length (the song's waveform, R11.2: hovering shows the time under the pointer,
// clicking or dragging seeks there, R7.4, and it never takes the focus, so ← and → seek whatever
// has it but a list or a box that uses them); on the right the queue button, which opens Up next (R7.2), and the volume. The sleep
// timer's moon (R7.10), the mini player's button (R15) and Now Playing's (R11.4) take their places
// on the right with their slices. What each says is the player's.
Rectangle {
    id: bar
    required property var player
    property var ratings: null  // a star clicked rates the song shown (R10.2)
    property var dragging: null  // songs dropped on the queue button play next (R6.10, R7.2)
    property var waveforms: null  // the song's waveform (R11.1.1, waveforms.Waveforms)
    readonly property bool hasSong: player.path !== ""
    height: 88
    color: Theme.bar

    Rectangle { width: parent.width; height: 1; color: Theme.border }

    // a round button of the bar: an icon, lit when `on`, faded when it can't act
    component BarButton: Item {
        id: button
        signal clicked()
        property string icon
        property string name
        property bool on: false
        property bool active: true
        property string note: ""  // why it can't act now, its tooltip in place of its name
        property real iconSize: 17
        property color tint: Theme.text
        width: 32
        height: 32
        opacity: active ? 1 : 0.4
        Accessible.role: Accessible.Button
        Accessible.name: button.name
        Accessible.description: button.note
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: hover.hovered && button.active ? Theme.hover : "transparent"
        }
        Icon {
            anchors.centerIn: parent
            name: button.icon
            size: button.iconSize
            color: button.on ? Theme.accentHi : button.tint
        }
        HoverHandler { id: hover; cursorShape: button.active ? Qt.PointingHandCursor : Qt.ArrowCursor }
        TapHandler { enabled: button.active; onTapped: button.clicked() }
        ToolTip.visible: hover.hovered
        ToolTip.text: button.note || button.name
        ToolTip.delay: 600
    }

    // the song
    Cover {
        id: art
        objectName: "barCover"
        x: 16
        y: 14
        width: 60
        height: 60
        radius: 8
        matte: Theme.bar
        visible: bar.hasSong
        source: bar.player.cover
        sourceSide: 128
    }
    Column {
        x: art.x + art.width + 14
        y: 16
        width: Math.max(0, seek.x - 54 - 16 - x)
        spacing: 3
        Text {
            objectName: "barTitle"
            width: parent.width
            elide: Text.ElideRight
            text: bar.player.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
        }
        Text {
            objectName: "barLine"
            width: parent.width
            elide: Text.ElideRight
            text: bar.player.line
            color: bar.player.failed ? Theme.err : Theme.muted
            font { family: Theme.sans; pixelSize: 12 }
        }
        Item { width: 1; height: 5 }
        Stars {
            objectName: "barRating"
            visible: bar.hasSong && !bar.player.failed
            rating: bar.player.rating
            size: 11
            settable: bar.ratings !== null
            onClicked: (star) => bar.ratings.ratePlaying(bar.player, star)
        }
    }

    // shuffle, previous, play/pause, next, repeat (R7.3)
    Row {
        id: transport
        anchors.horizontalCenter: parent.horizontalCenter
        y: 10
        spacing: 14
        BarButton {
            objectName: "shuffle"
            anchors.verticalCenter: parent.verticalCenter
            icon: "shuffle"
            name: bar.player.shuffleName
            on: bar.player.shuffle
            tint: Theme.muted
            onClicked: bar.player.toggleShuffle()
        }
        BarButton {
            objectName: "previous"
            anchors.verticalCenter: parent.verticalCenter
            icon: "prev"
            name: qsTr("Previous")
            active: bar.hasSong
            onClicked: bar.player.previous()
        }
        Rectangle {
            id: playPause
            objectName: "playPause"
            width: 36
            height: 36
            radius: 18
            color: Theme.text
            opacity: bar.hasSong ? 1 : 0.4
            Accessible.role: Accessible.Button
            Accessible.name: bar.player.playing ? qsTr("Pause") : qsTr("Play")
            Icon {
                anchors.centerIn: parent
                anchors.horizontalCenterOffset: bar.player.playing ? 0 : 1
                name: bar.player.playing ? "pause" : "play"
                size: 16
                color: Theme.bar
            }
            HoverHandler { cursorShape: bar.hasSong ? Qt.PointingHandCursor : Qt.ArrowCursor }
            TapHandler { enabled: bar.hasSong; onTapped: bar.player.toggle() }
        }
        BarButton {
            objectName: "next"
            anchors.verticalCenter: parent.verticalCenter
            icon: "next"
            name: qsTr("Next")
            note: bar.player.nextNote  // the song after this one can't play now (R2.10)
            active: bar.hasSong && note === ""
            onClicked: bar.player.next()
        }
        BarButton {
            objectName: "repeat"
            anchors.verticalCenter: parent.verticalCenter
            icon: "repeat"
            name: bar.player.repeatName
            on: bar.player.repeat !== "off"
            tint: Theme.muted
            onClicked: bar.player.cycleRepeat()
            Rectangle {  // repeat One's mark
                visible: bar.player.repeat === "one"
                x: parent.width - 13
                y: 3
                width: 12
                height: 12
                radius: 6
                color: Theme.accentSoft
                Text {
                    anchors.centerIn: parent
                    text: "1"
                    color: Theme.accentHi
                    font { family: Theme.sans; pixelSize: 9; weight: Font.Bold }
                }
            }
        }
    }

    // the time played, the seek bar, the length
    Text {
        objectName: "barPosition"
        anchors.right: seek.left
        anchors.rightMargin: 10
        anchors.verticalCenter: seek.verticalCenter
        width: 44
        horizontalAlignment: Text.AlignRight
        text: bar.player.positionText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 11; features: { "tnum": 1 } }
    }
    // the waveform as the seek bar (R11.2, R11.1): the played part in the gradient, the rest grey,
    // the play head over it; hovering shows the time under the pointer, and clicking or dragging
    // seeks there (R7.4)
    Item {
        id: seek
        objectName: "seekBar"
        anchors.horizontalCenter: parent.horizontalCenter
        y: 51
        width: Math.min(460, Math.max(160, bar.width - 2 * 400))
        height: 26
        enabled: bar.player.seekable
        // worked out still: a flat line filling in (R11.1.1); the tour waits for it
        readonly property bool loading: bar.waveforms !== null && bar.waveforms.loading
        Accessible.role: Accessible.Slider
        Accessible.name: bar.player.timeName
        Waveform {
            objectName: "waveform"
            y: 3
            width: parent.width
            height: 20
            source: bar.waveforms
            progress: bar.player.progress
            barWidth: 2
            gap: 1.3
            playedFrom: Theme.cyan
            playedMid: Theme.accent
            playedTo: Theme.pink
            rest: Theme.borderStrong
        }
        Rectangle {  // the play head
            objectName: "playHead"
            visible: bar.hasSong
            x: Math.round(bar.player.progress * (seek.width - width))
            width: 2
            height: seek.height
            radius: 1
            color: Theme.text
        }
        MouseArea {
            id: pointer
            anchors.fill: parent
            hoverEnabled: true
            preventStealing: true
            cursorShape: seek.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onPressed: (mouse) => bar.player.seekTo(mouse.x / width)
            onPositionChanged: (mouse) => { if (pressed) bar.player.seekTo(mouse.x / width) }
        }
        Rectangle {  // the time under the pointer
            objectName: "hoverTime"
            visible: pointer.containsMouse && hoverText.text !== ""
            x: Math.max(-20, Math.min(seek.width + 20 - width, pointer.mouseX - width / 2))
            y: -height - 4
            width: hoverText.implicitWidth + 12
            height: 18
            radius: 4
            color: Theme.raised
            border.color: Theme.borderStrong
            Text {
                id: hoverText
                anchors.centerIn: parent
                text: bar.player.timeAt(pointer.mouseX / seek.width)
                color: Theme.text
                font { family: Theme.sans; pixelSize: 11; features: { "tnum": 1 } }
            }
        }
    }
    Text {
        objectName: "barLength"
        anchors.left: seek.right
        anchors.leftMargin: 10
        anchors.verticalCenter: seek.verticalCenter
        width: 44
        text: bar.player.lengthText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 11; features: { "tnum": 1 } }
    }

    // the queue and the volume
    Row {
        anchors.right: parent.right
        anchors.rightMargin: 112   // the mini player's and Now Playing's places (R15, R11.4)
        y: 25
        spacing: 8
        BarButton {
            objectName: "queueButton"
            icon: "queue"
            iconSize: 18
            name: qsTr("Up next")
            on: bar.player.upNextOpen
            tint: Theme.muted
            onClicked: bar.player.toggleUpNext()
            DropArea {  // songs dropped on it play next (R6.10, R7.2)
                objectName: "queueDrop"
                anchors.fill: parent
                enabled: bar.dragging !== null
                onEntered: (drag) => drag.accepted = bar.dragging.enter("queue", 0, drag.getDataAsString(bar.dragging.mime), drag.urls)
                onExited: bar.dragging.leave("queue", 0)
                onDropped: (drop) => { if (bar.dragging.drop("queue", 0, drop.getDataAsString(bar.dragging.mime), drop.urls)) drop.accept(Qt.CopyAction) }
            }
            Rectangle {  // a drag over it: outlined
                anchors.fill: parent
                radius: 8
                color: "transparent"
                border.color: Theme.accent
                border.width: 2
                visible: bar.dragging !== null && bar.dragging.target === "queue:0"
            }
        }
        Item {
            width: 24
            height: 32
            Icon { anchors.centerIn: parent; name: "volume"; size: 18; color: Theme.muted }
        }
        Slider {
            id: volume
            objectName: "volume"
            anchors.verticalCenter: parent.verticalCenter
            width: 96
            height: 24
            from: 0
            to: 1
            value: bar.player.volume
            onMoved: bar.player.setVolume(value)
            Accessible.name: qsTr("Volume")
            // focused, it keeps ← and → for itself rather than seek (R6.9)
            Keys.onShortcutOverride: (event) => event.accepted = event.key === Qt.Key_Left || event.key === Qt.Key_Right
            background: Item {
                x: volume.leftPadding
                width: volume.availableWidth
                height: volume.height
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width
                    height: 4
                    radius: 2
                    color: Theme.borderStrong
                }
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: volume.visualPosition * parent.width
                    height: 4
                    radius: 2
                    color: Theme.cell
                }
            }
            handle: Rectangle {
                x: volume.leftPadding + volume.visualPosition * (volume.availableWidth - width)
                anchors.verticalCenter: parent.verticalCenter
                width: 12
                height: 12
                radius: 6
                color: Theme.text
            }
        }
    }
}
