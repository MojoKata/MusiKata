import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Shapes
import MusiKata
import "."

// The mini player (R15, M01-mini-players, M02-mini-player-menu): a second top-level window from the
// main window's engine (A1.8), bound to the same Player bridge and models. Frameless, its rounded
// card drawn inside a margin that holds its own shadow, in the design tokens of R6.2; the layout
// chosen (R15.3) is a component loaded into it. It is moved by dragging anywhere that isn't a
// control (startSystemMove) and resized from its edges (startSystemResize) within its layout's
// limits; Stay on top is its pin (R15.2). Every layout has play/pause, previous, next, × and the
// pin; all but Strip and Remote the MusiKata icon in a corner, which is Show MusiKata; Cover's
// appear only under the pointer (R15.4). The wheel over it changes the volume; Space, ← / →,
// Ctrl+→ / Ctrl+← and Ctrl+Shift+M work while it has focus, and 1 to 7 choose a layout, as its
// right-click menu numbers them. Songs dropped onto it are added to the queue to play next, as on
// the bar's queue button (R7.2, R6.10). Its visuals are the main window's items at a smaller size
// (R15.5): they stop when it is hidden, minimized, covered as far as Qt can tell (`mini.exposed`),
// or paused. What every text says, where it is and what it keeps are miniplayer.py's.
Window {
    id: miniWin
    objectName: "miniPlayer"
    required property var mini         // miniplayer.MiniPlayer
    required property var player
    property var waveforms: null       // the Card's and Details' waveform (R11.2)
    property var tints: null           // the cover's colour (R6.2.2)
    property var ratings: null         // the Card's and Details' stars (R10.2)
    property var dragging: null        // songs dropped on it (R7.2)
    property var now: null             // the analyzer's bands and speed (R11.3.1)
    readonly property var words: mini.words
    readonly property bool hasSong: mini.hasSong
    readonly property string cover: words.cover || ""
    readonly property string tintName: tints !== null && cover !== "" ? (tints.revision, tints.of(cover)) : ""
    readonly property color tint: tintName !== "" ? tintName : Theme.surface
    readonly property bool drawing: player.playing && mini.exposed  // R15.5
    readonly property int m: mini.margin
    readonly property bool hovered: cardHover.hovered || mini.showControls
    transientParent: null
    title: qsTr("MusiKata mini player")
    flags: Qt.Window | Qt.FramelessWindowHint | (mini.stayOnTop ? Qt.WindowStaysOnTopHint : 0)
    color: "transparent"
    minimumWidth: mini.limits.minimumWidth
    minimumHeight: mini.limits.minimumHeight
    maximumWidth: mini.limits.maximumWidth
    maximumHeight: mini.limits.maximumHeight
    onVisibleChanged: if (!visible) menu.close()

    // ---------- the shadow, the card, and what every layout shares ----------

    Repeater {  // its own shadow (R15.2): soft rings under the card, a little below it
        model: 6
        Rectangle {
            required property int index
            x: miniWin.m - index * 2
            y: miniWin.m - index * 2 + 3
            width: card.width + index * 4
            height: card.height + index * 4
            radius: card.radius + index * 2
            color: "transparent"
            border.width: 2
            border.color: Qt.rgba(0, 0, 0, 0.11 - index * 0.016)
        }
    }

    Rectangle {
        id: card
        objectName: "miniCard"
        x: miniWin.m
        y: miniWin.m
        width: miniWin.width - 2 * miniWin.m
        height: miniWin.height - 2 * miniWin.m
        radius: mini.layout === "cover" ? width * 0.0533 : mini.radius
        color: ({ card: Theme.surface, details: Theme.surface, analyzer: Theme.bg, cover: Theme.surface })[mini.layout] || Theme.side
        border.color: miniWin.dragging !== null && miniWin.dragging.target === "queue:1" ? Theme.accent : Theme.borderStrong
        border.width: miniWin.dragging !== null && miniWin.dragging.target === "queue:1" ? 2 : 1
        Accessible.role: Accessible.Pane
        Accessible.name: qsTr("Mini player")
        HoverHandler { id: cardHover }

        MouseArea {  // anywhere not a control: moved by dragging, the menu, the volume (R15.2, R15.4)
            objectName: "miniGrip"
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onPressed: (mouse) => {
                if (mouse.button === Qt.RightButton)
                    menu.popup()
                else
                    miniWin.startSystemMove()
            }
            onWheel: (wheel) => miniWin.mini.wheel(wheel.angleDelta.y)
        }
        DropArea {  // songs dropped on it play next, as on the bar's queue button (R7.2)
            objectName: "miniDrop"
            anchors.fill: parent
            enabled: miniWin.dragging !== null
            onEntered: (drag) => drag.accepted = miniWin.dragging.enter("queue", 1, drag.getDataAsString(miniWin.dragging.mime), drag.urls)
            onExited: miniWin.dragging.leave("queue", 1)
            onDropped: (drop) => { if (miniWin.dragging.drop("queue", 1, drop.getDataAsString(miniWin.dragging.mime), drop.urls)) drop.accept(Qt.CopyAction) }
        }
        // each layout made the first time it is chosen and kept, shown while it is the one chosen:
        // a QML item of a Python type (the spectrum, the Disc, the waveform, the analyzer) is never
        // destroyed while its window lives, since PySide keeps its wrapper (A1.3)
        Repeater {
            model: [
                { name: "strip", layout: strip }, { name: "cover", layout: coverLayout },
                { name: "card", layout: cardLayout }, { name: "analyzer", layout: analyzerLayout },
                { name: "disc", layout: disc }, { name: "details", layout: details },
                { name: "remote", layout: remote }
            ]
            Loader {
                id: layoutLoader
                required property var modelData
                readonly property bool chosen: miniWin.mini.layout === modelData.name
                property bool made: false
                objectName: chosen ? "miniLayout" : ""
                anchors.fill: parent
                visible: chosen
                active: chosen || made
                onActiveChanged: if (active) made = true
                Component.onCompleted: if (active) made = true
                sourceComponent: modelData.layout
            }
        }
        Rectangle {  // the card's edge over what it holds
            anchors.fill: parent
            radius: card.radius
            color: "transparent"
            border.color: card.border.color
            border.width: card.border.width
        }
    }

    // resized from its edges within its layout's limits (R15.2): a grip straddling each edge and
    // corner, where the layout can change that way
    component Edge: MouseArea {
        property int edges
        property bool across: (edges & (Qt.LeftEdge | Qt.RightEdge)) !== 0
        property bool down: (edges & (Qt.TopEdge | Qt.BottomEdge)) !== 0
        enabled: (!across || miniWin.minimumWidth < miniWin.maximumWidth)
                 && (!down || miniWin.minimumHeight < miniWin.maximumHeight)
        cursorShape: across && down ? ((edges === (Qt.LeftEdge | Qt.TopEdge) || edges === (Qt.RightEdge | Qt.BottomEdge)) ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor)
                     : across ? Qt.SizeHorCursor : Qt.SizeVerCursor
        onPressed: miniWin.startSystemResize(edges)
    }
    Edge { edges: Qt.LeftEdge; x: miniWin.m - 5; y: miniWin.m + 10; width: 8; height: card.height - 20 }
    Edge { edges: Qt.RightEdge; x: miniWin.width - miniWin.m - 3; y: miniWin.m + 10; width: 8; height: card.height - 20 }
    Edge { edges: Qt.TopEdge; x: miniWin.m + 10; y: miniWin.m - 5; width: card.width - 20; height: 8 }
    Edge { edges: Qt.BottomEdge; x: miniWin.m + 10; y: miniWin.height - miniWin.m - 3; width: card.width - 20; height: 8 }
    Edge { edges: Qt.LeftEdge | Qt.TopEdge; x: miniWin.m - 5; y: miniWin.m - 5; width: 14; height: 14 }
    Edge { edges: Qt.RightEdge | Qt.TopEdge; x: miniWin.width - miniWin.m - 9; y: miniWin.m - 5; width: 14; height: 14 }
    Edge { edges: Qt.LeftEdge | Qt.BottomEdge; x: miniWin.m - 5; y: miniWin.height - miniWin.m - 9; width: 14; height: 14 }
    Edge { edges: Qt.RightEdge | Qt.BottomEdge; x: miniWin.width - miniWin.m - 9; y: miniWin.height - miniWin.m - 9; width: 14; height: 14 }

    // ---------- the parts ----------

    // an icon button: × and the pin, previous and next, shuffle and repeat
    component Button: Item {
        id: button
        signal clicked()
        property string icon
        property string name
        property real size: 15
        property color tint: Theme.text
        property bool on: false
        property bool active: true
        width: Math.max(24, size + 10)
        height: width
        opacity: active ? 1 : 0.4
        Accessible.role: Accessible.Button
        Accessible.name: button.name
        Rectangle { anchors.fill: parent; radius: width / 2; color: hover.hovered && button.active ? Theme.hover : "transparent"; opacity: 0.8 }
        Icon { anchors.centerIn: parent; name: button.icon; size: button.size; color: button.on ? Theme.accentHi : button.tint }
        HoverHandler { id: hover; cursorShape: button.active ? Qt.PointingHandCursor : Qt.ArrowCursor }
        TapHandler { enabled: button.active; onTapped: button.clicked() }
    }
    // play/pause: the light round button (M01)
    component PlayButton: Rectangle {
        id: play
        property real size: 34
        objectName: "miniPlayPause"
        width: size
        height: size
        radius: size / 2
        color: Theme.text
        opacity: miniWin.hasSong ? 1 : 0.4
        Accessible.role: Accessible.Button
        Accessible.name: miniWin.player.playing ? qsTr("Pause") : qsTr("Play")
        Icon {
            anchors.centerIn: parent
            anchors.horizontalCenterOffset: miniWin.player.playing ? 0 : 1
            name: miniWin.player.playing ? "pause" : "play"
            size: play.size * 0.44
            color: Theme.bar
        }
        HoverHandler { cursorShape: miniWin.hasSong ? Qt.PointingHandCursor : Qt.ArrowCursor }
        TapHandler { enabled: miniWin.hasSong; onTapped: miniWin.mini.playPause() }
    }
    // previous, play/pause and next, centred on `centre`
    component Transport: Item {
        id: transport
        property real play: 34
        property real step: 40       // from play/pause's centre to previous's and next's
        property real iconSize: 15
        property color tint: Theme.text
        width: 2 * step + 30
        height: play
        Button {
            objectName: "miniPrevious"
            anchors.verticalCenter: parent.verticalCenter
            x: parent.width / 2 - transport.step - width / 2
            icon: "prev"
            name: qsTr("Previous")
            size: transport.iconSize
            tint: transport.tint
            active: miniWin.hasSong
            onClicked: miniWin.player.previous()
        }
        PlayButton { size: transport.play; anchors.centerIn: parent }
        Button {
            objectName: "miniNext"
            anchors.verticalCenter: parent.verticalCenter
            x: parent.width / 2 + transport.step - width / 2
            icon: "next"
            name: qsTr("Next")
            size: transport.iconSize
            tint: transport.tint
            active: miniWin.player.path !== "" && miniWin.player.nextNote === ""
            onClicked: miniWin.player.next()
        }
    }
    component Pin: Button {
        objectName: "miniPin"
        icon: "pin"
        name: qsTr("Stay on top")
        size: 13
        tint: Theme.muted
        on: miniWin.mini.stayOnTop
        Accessible.checkable: true
        Accessible.checked: miniWin.mini.stayOnTop
        onClicked: miniWin.mini.toggleStayOnTop()
    }
    component Close: Button {
        objectName: "miniClose"
        icon: "close"
        name: qsTr("Close mini player")
        size: 11
        tint: Theme.muted
        onClicked: miniWin.mini.close()
    }
    // the MusiKata icon (R15.4): Show MusiKata
    component Logo: Rectangle {
        id: logo
        property real size: 18
        objectName: "miniLogo"
        width: size
        height: size
        radius: size * 0.3
        visible: miniWin.mini.logo
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.cyan }
            GradientStop { position: 0.55; color: Theme.accent }
            GradientStop { position: 1; color: Theme.pink }
        }
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Show MusiKata")
        Repeater {
            model: [0.35, 0.65, 0.45]
            Rectangle {
                required property int index
                required property real modelData
                x: logo.size * (0.25 + index * 0.2)
                y: logo.size * (0.5 - modelData / 2)
                width: Math.max(1.5, logo.size * 0.1)
                height: logo.size * modelData
                radius: width / 2
                color: Theme.text
            }
        }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: miniWin.mini.close() }
    }
    // the progress as a line along the card's foot, inside its rounded corners
    component Progress: Item {
        id: line
        property real thick: 3
        property bool green: false
        objectName: "miniProgress"
        anchors.fill: parent
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: "transparent"
                fillColor: Qt.rgba(0, 0, 0, 0.4)
                PathSvg { path: miniWin.mini.progressPath(line.width, line.height, card.radius, line.thick, 1) }
            }
            ShapePath {
                strokeColor: "transparent"
                fillColor: line.green ? Theme.progress : "transparent"
                fillGradient: line.green ? null : sweep
                PathSvg { path: miniWin.mini.progressPath(line.width, line.height, card.radius, line.thick, miniWin.player.progress) }
            }
            LinearGradient {
                id: sweep
                x1: 0; y1: 0; x2: Math.max(1, line.width * miniWin.player.progress); y2: 0
                GradientStop { position: 0; color: Theme.cyan }
                GradientStop { position: 0.6; color: Theme.accent }
                GradientStop { position: 1; color: Theme.pink }
            }
        }
    }
    // the ten-bar spectrum (R15.3: R11.3's bands gathered into ten), a quiet bar a dot
    component Bars: CoverSpectrum {
        objectName: "miniSpectrum"
        width: 48
        height: 24
        bars: 10
        pad: 0
        gap: 2
        least: 4
        colours: [Theme.cyan, Theme.accent, Theme.pink]
        player: miniWin.player
        playing: miniWin.drawing
        Accessible.role: Accessible.Animation
        Accessible.name: qsTr("Spectrum")
    }
    component Time: Text {
        objectName: "miniTime"
        text: miniWin.player.positionText
        color: Theme.muted
        font { family: Theme.mono; pixelSize: 11; features: { "tnum": 1 } }
    }
    // a cover with its corners rounded by the cover provider (covers.py: the window's corners have
    // nothing behind them for Cover.qml's matte), or the empty tile
    component Art: Item {
        id: art
        property real share: 0.05
        property int sourceSide: 256
        readonly property bool loading: image.status === Image.Loading
        Image {
            id: image
            anchors.fill: parent
            source: miniWin.cover !== "" ? miniWin.cover + "?round=" + art.share : ""
            sourceSize: Qt.size(art.sourceSide, art.sourceSide)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            smooth: true
        }
        Rectangle {
            anchors.fill: parent
            visible: image.status !== Image.Ready && !art.loading
            radius: art.share * Math.min(width, height)
            color: Theme.raised
            border.color: Theme.borderStrong
            Icon { anchors.centerIn: parent; name: "album"; size: Math.min(28, art.width / 3); color: Theme.faint }
        }
    }
    component Title: Text {
        elide: Text.ElideRight
        color: Theme.text
        text: miniWin.words.title || ""
        font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
    }
    component Line: Text {
        elide: Text.ElideRight
        color: Theme.muted
        text: miniWin.words.line || ""
        font { family: Theme.sans; pixelSize: 12 }
    }

    // ---------- the right half of the Strip, and the Remote (R15.3: 1, 7) ----------

    component RightHalf: Item {
        width: 232
        height: 76
        Bars { x: 0; y: 16 }
        Time { x: 0; y: 44 }
        Transport { x: 128 - width / 2; y: 38 - height / 2; play: 34; step: 40 }
        Close { x: 212 - width / 2; y: 20 - height / 2 }
        Pin { x: 212 - width / 2; y: 54 - height / 2 }
    }
    Component {
        id: strip
        Item {
            objectName: "miniStrip"
            Cover { x: 10; y: 10; width: 56; height: 56; radius: 9; matte: card.color; source: miniWin.cover; sourceSide: 128; emptyText: "" }
            Title { objectName: "miniTitle"; x: 78; y: 15; width: right.x - 16 - x }
            Line { objectName: "miniLine"; x: 78; y: 37; width: right.x - 16 - x }
            RightHalf { id: right; x: parent.width - width }
            Progress { }
        }
    }
    Component {
        id: remote
        Item {
            objectName: "miniRemote"
            RightHalf { x: parent.width - width }
            Progress { }
            HoverHandler { id: remoteHover }
            ToolTip {  // the song it doesn't name (M02)
                objectName: "miniTooltip"
                popupType: Popup.Window
                visible: remoteHover.hovered && text !== ""
                delay: 600
                x: -width - 12
                y: 22
                text: miniWin.words.tooltip || ""
            }
        }
    }

    // ---------- Cover (R15.3: 2) ----------

    Component {
        id: coverLayout
        Item {
            id: coverItem
            objectName: "miniCoverLayout"
            readonly property real s: width
            Art { anchors.fill: parent; share: 0.0533; sourceSide: 512 }
            Rectangle {  // the dark gradient its words and controls show over, under the pointer
                y: parent.height * 0.4
                width: parent.width
                height: parent.height * 0.6
                radius: card.radius
                visible: miniWin.hovered
                gradient: Gradient {
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.82) }
                }
            }
            CoverSpectrum {  // translucent bars over its lower part (as R11.4.3)
                objectName: "miniCoverSpectrum"
                width: parent.width
                height: parent.height * 0.3
                y: parent.height - 8 - height
                player: miniWin.player
                playing: miniWin.drawing
            }
            Progress { green: true }
            Item {  // its controls, only under the pointer (R15.4)
                objectName: "miniCoverControls"
                anchors.fill: parent
                visible: miniWin.hovered
                Logo { x: 10; y: 10; size: 20 }
                Rectangle {
                    x: parent.width - 66
                    y: 8
                    width: 58
                    height: 24
                    radius: 12
                    color: Qt.rgba(0, 0, 0, 0.45)
                    Pin { anchors.verticalCenter: parent.verticalCenter; x: 16 - width / 2; tint: Theme.text }
                    Close { anchors.verticalCenter: parent.verticalCenter; x: 42 - width / 2; tint: Theme.text }
                }
                Text {
                    objectName: "miniTitle"
                    x: 18
                    y: parent.height - 84
                    width: parent.width - 140
                    elide: Text.ElideRight
                    text: miniWin.words.title || ""
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 18; weight: Font.Bold }
                }
                Text {
                    objectName: "miniLine"
                    x: 18
                    y: parent.height - 58
                    width: parent.width - 140
                    elide: Text.ElideRight
                    text: miniWin.words.line || ""
                    color: Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, 0.72)
                    font { family: Theme.sans; pixelSize: 12 }
                }
                Transport { x: parent.width - 62 - width / 2; y: parent.height - 60; play: 36; step: 38 }
            }
        }
    }

    // ---------- Card and Details (R15.3: 3, 6) ----------

    component Upright: Item {
        id: upright
        property bool art: true       // the Card's cover
        property bool upNext: true    // the Card's next song
        readonly property real side: Math.max(120, Math.min(width - 32, height - 314))
        readonly property real wordsTop: art ? 44 + side + 14 : 44
        Rectangle {  // the cover's colour from the top (R6.2.2)
            anchors.fill: parent
            radius: card.radius
            visible: miniWin.tintName !== ""
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.rgba(miniWin.tint.r, miniWin.tint.g, miniWin.tint.b, 0.32) }
                GradientStop { position: 0.7; color: "transparent" }
            }
        }
        Logo { x: 12; y: 10 }
        Pin { x: parent.width - 46 - width / 2; y: 19 - height / 2 }
        Close { x: parent.width - 20 - width / 2; y: 19 - height / 2 }
        Art { objectName: "miniArt"; visible: upright.art; x: (parent.width - width) / 2; y: 44; width: upright.side; height: upright.side; share: 12 / 268; sourceSide: 512 }
        Text {
            objectName: "miniKicker"
            x: 16
            y: upright.wordsTop
            width: parent.width - 32
            elide: Text.ElideRight
            text: miniWin.words.kicker || ""
            color: Qt.tint(Theme.text, Qt.rgba(Theme.cyan.r, Theme.cyan.g, Theme.cyan.b, 0.3))
            font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; capitalization: Font.AllUppercase; letterSpacing: 0.3 }
        }
        Text {
            objectName: "miniTitle"
            x: 16
            y: upright.wordsTop + 16
            width: parent.width - 32 - 80
            elide: Text.ElideRight
            text: miniWin.words.title || ""
            color: Theme.text
            font { family: Theme.sans; pixelSize: 21; weight: Font.ExtraBold }
        }
        Stars {
            objectName: "miniRating"
            x: parent.width - 16 - width
            y: upright.wordsTop + 24
            visible: miniWin.hasSong
            rating: miniWin.player.rating
            size: 11
            spacing: 2.5
            settable: miniWin.ratings !== null && miniWin.player.path !== ""
            onClicked: (star) => miniWin.ratings.ratePlaying(miniWin.player, star)
        }
        Text {
            objectName: "miniDetails"
            x: 16
            y: upright.wordsTop + 48
            width: parent.width - 32
            elide: Text.ElideRight
            text: miniWin.words.details || ""
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 12 }
        }
        Item {  // the waveform as the seek bar (R11.2)
            id: seek
            objectName: "miniSeek"
            x: 16
            y: upright.wordsTop + 78
            width: parent.width - 32
            height: 34
            enabled: miniWin.player.seekable
            readonly property bool loading: miniWin.waveforms !== null && miniWin.waveforms.loading
            Accessible.role: Accessible.Slider
            Accessible.name: miniWin.player.timeName
            Waveform {
                objectName: "miniWaveform"
                y: 4
                width: parent.width
                height: 26
                source: miniWin.waveforms
                progress: miniWin.player.progress
                barWidth: 2
                gap: 1.2
                playedFrom: Theme.cyan
                playedMid: Theme.accent
                playedTo: Theme.pink
                rest: Theme.borderStrong
            }
            Rectangle {
                visible: miniWin.player.path !== ""
                x: Math.round(miniWin.player.progress * (seek.width - width))
                width: 2
                height: seek.height
                radius: 1
                color: Theme.text
            }
            MouseArea {
                anchors.fill: parent
                preventStealing: true
                cursorShape: seek.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onPressed: (mouse) => miniWin.player.seekTo(mouse.x / width)
                onPositionChanged: (mouse) => { if (pressed) miniWin.player.seekTo(mouse.x / width) }
            }
        }
        Time { x: 16; y: upright.wordsTop + 114 }
        Text {
            objectName: "miniLength"
            x: parent.width - 16 - width
            y: upright.wordsTop + 114
            text: miniWin.player.lengthText
            color: Theme.muted
            font { family: Theme.mono; pixelSize: 11; features: { "tnum": 1 } }
        }
        Item {  // shuffle, previous, play/pause, next, repeat
            x: 0
            y: upright.wordsTop + 132
            width: parent.width
            height: 40
            Button {
                objectName: "miniShuffle"
                anchors.verticalCenter: parent.verticalCenter
                x: parent.width / 2 - 92 - width / 2
                icon: "shuffle"
                name: miniWin.player.shuffleName
                size: 16
                tint: Theme.muted
                on: miniWin.player.shuffle
                onClicked: miniWin.player.toggleShuffle()
            }
            Transport { anchors.centerIn: parent; play: 40; step: 46; iconSize: 17 }
            Button {
                objectName: "miniRepeat"
                anchors.verticalCenter: parent.verticalCenter
                x: parent.width / 2 + 92 - width / 2
                icon: "repeat"
                name: miniWin.player.repeatName
                size: 16
                tint: Theme.muted
                on: miniWin.player.repeat !== "off"
                onClicked: miniWin.player.cycleRepeat()
            }
        }
        Item {  // the next song in the queue
            objectName: "miniUpNext"
            visible: upright.upNext && (miniWin.mini.upNext.line || "") !== ""
            x: 16
            y: parent.height - 54
            width: parent.width - 32
            height: 44
            Rectangle { width: parent.width; height: 1; color: Theme.border }
            Cover { x: 0; y: 10; width: 28; height: 28; radius: 5; matte: card.color; source: miniWin.mini.upNext.cover || ""; sourceSide: 128; emptyText: "" }
            Text {
                x: 38
                y: 10
                text: qsTr("Up next")
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 10; weight: Font.Bold; capitalization: Font.AllUppercase }
            }
            Text {
                objectName: "miniUpNextLine"
                x: 38
                y: 23
                width: parent.width - 38 - 50
                elide: Text.ElideRight
                text: miniWin.mini.upNext.line || ""
                color: Theme.cell
                font { family: Theme.sans; pixelSize: 12 }
            }
            Text {
                x: parent.width - width
                y: 16
                text: miniWin.mini.upNext.length || ""
                color: Theme.muted
                font { family: Theme.mono; pixelSize: 11; features: { "tnum": 1 } }
            }
        }
    }
    Component { id: cardLayout; Upright { objectName: "miniCardLayout" } }
    Component { id: details; Upright { objectName: "miniDetailsLayout"; art: false; upNext: false } }

    // ---------- Analyzer (R15.3: 4) ----------

    Component {
        id: analyzerLayout
        Item {
            id: an
            objectName: "miniAnalyzerLayout"
            readonly property color ground: Qt.tint(Theme.bg, Qt.rgba(Theme.accentSoft.r, Theme.accentSoft.g, Theme.accentSoft.b, 0.12))
            Rectangle {
                anchors.fill: parent
                radius: card.radius
                gradient: Gradient {
                    GradientStop { position: 0; color: Theme.bg }
                    GradientStop { position: 1; color: Qt.tint(Theme.bg, Qt.rgba(Theme.accentSoft.r, Theme.accentSoft.g, Theme.accentSoft.b, 0.25)) }
                }
            }
            Analyzer {  // a small 3D analyzer (R11.3)
                objectName: "miniAnalyzer"
                x: 12
                y: 14
                width: parent.width - 24
                height: parent.height - 24
                player: miniWin.player
                playing: miniWin.drawing
                bands: miniWin.now !== null ? miniWin.now.analyzerBands : 96
                seconds: miniWin.now !== null ? miniWin.now.analyzerSeconds : 3
                front: Theme.cyan
                back: Theme.accent
                background: an.ground
                Accessible.role: Accessible.Animation
                Accessible.name: qsTr("3D analyzer")
            }
            Rectangle {  // the song's card, top left
                x: 10
                y: 10
                width: Math.min(236, parent.width - 90)
                height: 50
                radius: 12
                color: Qt.rgba(Theme.bar.r, Theme.bar.g, Theme.bar.b, 0.72)
                border.color: Theme.border
                Cover { x: 7; y: 7; width: 36; height: 36; radius: 6; matte: parent.color; source: miniWin.cover; sourceSide: 128; emptyText: "" }
                Text {
                    objectName: "miniTitle"
                    x: 52
                    y: 7
                    width: parent.width - x - 10
                    elide: Text.ElideRight
                    text: miniWin.words.title || ""
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
                }
                Text {
                    objectName: "miniLine"
                    x: 52
                    y: 26
                    width: parent.width - x - 10
                    elide: Text.ElideRight
                    text: miniWin.words.line || ""
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 11 }
                }
            }
            Pin { x: parent.width - 46 - width / 2; y: 20 - height / 2 }
            Close { x: parent.width - 20 - width / 2; y: 20 - height / 2 }
            Logo { x: 12; y: parent.height - 34 }
            Rectangle {  // the controls in a pill, bottom right
                x: parent.width - 128
                y: parent.height - 52
                width: 116
                height: 40
                radius: 20
                color: Qt.rgba(Theme.bar.r, Theme.bar.g, Theme.bar.b, 0.72)
                border.color: Theme.border
                Transport { anchors.centerIn: parent; play: 30; step: 33; iconSize: 14 }
            }
            Progress { thick: 2 }
        }
    }

    // ---------- Disc (R15.3: 5) ----------

    Component {
        id: disc
        Item {
            objectName: "miniDiscLayout"
            Item {  // M01's 240 × 320, scaled to the card
                width: 240
                height: 320
                scale: Math.min(parent.width / 240, parent.height / 320)
                transformOrigin: Item.Top
                x: (parent.width - width) / 2
                Disc {  // the progress ring and the spectrum's rays
                    objectName: "miniDisc"
                    x: 120 - 106
                    y: 116 - 106
                    width: 212
                    height: 212
                    player: miniWin.player
                    playing: miniWin.drawing
                    progress: miniWin.player.progress
                    colours: [Theme.cyan, Theme.accent, Theme.pink]
                    track: Theme.borderStrong
                    done: Theme.progress
                    Accessible.role: Accessible.ProgressBar
                    Accessible.name: miniWin.player.timeName
                }
                Art { objectName: "miniArt"; x: 120 - 74; y: 116 - 74; width: 148; height: 148; share: 0.5; sourceSide: 256 }
                Repeater {  // the disc's grooves
                    model: [0.55, 0.69, 0.83]
                    Rectangle {
                        required property real modelData
                        visible: miniWin.cover !== ""
                        x: 120 - width / 2
                        y: 116 - height / 2
                        width: 148 * modelData
                        height: width
                        radius: width / 2
                        color: "transparent"
                        border.color: Qt.rgba(0, 0, 0, 0.18)
                    }
                }
                Rectangle { x: 105; y: 101; width: 30; height: 30; radius: 15; color: Qt.rgba(0, 0, 0, 0.35) }
                Rectangle { x: 114; y: 110; width: 12; height: 12; radius: 6; color: Theme.side }
                Logo { x: 12; y: 11 }
                Pin { x: 240 - 46 - width / 2; y: 20 - height / 2 }
                Close { x: 240 - 20 - width / 2; y: 20 - height / 2 }
                Text {
                    objectName: "miniTitle"
                    x: 12
                    y: 216
                    width: 216
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: miniWin.words.title || ""
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 16; weight: Font.Bold }
                }
                Text {
                    objectName: "miniLine"
                    x: 12
                    y: 242
                    width: 216
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: miniWin.words.line || ""
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 12 }
                }
                Transport { x: 120 - width / 2; y: 270; play: 36; step: 46 }
            }
        }
    }

    // ---------- the right-click menu (R15.4, M02) ----------

    Menu {
        id: menu
        objectName: "miniMenu"
        popupType: Popup.Window
        width: 236
        topPadding: 8
        bottomPadding: 8
        background: Rectangle { radius: 10; color: Theme.raised; border.color: Theme.borderStrong }
        component Entry: MenuItem {
            id: entry
            property string label
            property string note           // what it shows on the right: its number, its keys
            property string mark           // its icon on the left: the check, the moon
            property bool mono: false
            property string later: ""      // a later slice's: faded, saying so in its tooltip
            text: entry.label
            implicitHeight: 30
            leftPadding: 14
            rightPadding: 14
            enabled: later === ""
            Accessible.role: Accessible.MenuItem
            Accessible.name: entry.label
            Accessible.description: entry.later
            contentItem: Item {
                implicitHeight: 30
                opacity: entry.later === "" ? 1 : 0.5
                Icon { anchors.verticalCenter: parent.verticalCenter; x: 1; visible: entry.mark !== ""; name: entry.mark; size: 13; color: Theme.accentHi; lineWidth: entry.mark === "check" ? 2 : 1.7 }
                Text {
                    x: 26
                    width: parent.width - 26 - noteText.implicitWidth - 8
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: entry.label
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Text {
                    id: noteText
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: entry.note
                    color: Theme.faint
                    font { family: entry.mono ? Theme.mono : Theme.sans; pixelSize: 11 }
                }
            }
            background: Rectangle { x: 6; width: entry.width - 12; radius: 7; color: entry.highlighted ? Theme.hover : "transparent" }
            HoverHandler { id: entryHover; enabled: entry.later !== "" }
            ToolTip {
                popupType: Popup.Window
                visible: entryHover.hovered
                delay: 400
                text: entry.later
            }
        }
        MenuItem {
            enabled: false
            implicitHeight: 22
            leftPadding: 14
            contentItem: Text {
                text: qsTr("Layout")
                color: Theme.faint
                verticalAlignment: Text.AlignVCenter
                font { family: Theme.sans; pixelSize: 10; weight: Font.Bold; letterSpacing: 0.4; capitalization: Font.AllUppercase }
            }
            background: Item { }
        }
        Entry {
            readonly property var layout: miniWin.mini.layouts[0]
            objectName: "miniLayout_" + layout.name
            label: layout.title
            note: layout.number
            mono: true
            mark: layout.checked ? "check" : ""
            Accessible.checkable: true
            Accessible.checked: layout.checked
            onTriggered: miniWin.mini.setLayout(layout.name)
        }
        Entry {
            readonly property var layout: miniWin.mini.layouts[1]
            objectName: "miniLayout_" + layout.name
            label: layout.title
            note: layout.number
            mono: true
            mark: layout.checked ? "check" : ""
            Accessible.checkable: true
            Accessible.checked: layout.checked
            onTriggered: miniWin.mini.setLayout(layout.name)
        }
        Entry {
            readonly property var layout: miniWin.mini.layouts[2]
            objectName: "miniLayout_" + layout.name
            label: layout.title
            note: layout.number
            mono: true
            mark: layout.checked ? "check" : ""
            Accessible.checkable: true
            Accessible.checked: layout.checked
            onTriggered: miniWin.mini.setLayout(layout.name)
        }
        Entry {
            readonly property var layout: miniWin.mini.layouts[3]
            objectName: "miniLayout_" + layout.name
            label: layout.title
            note: layout.number
            mono: true
            mark: layout.checked ? "check" : ""
            Accessible.checkable: true
            Accessible.checked: layout.checked
            onTriggered: miniWin.mini.setLayout(layout.name)
        }
        Entry {
            readonly property var layout: miniWin.mini.layouts[4]
            objectName: "miniLayout_" + layout.name
            label: layout.title
            note: layout.number
            mono: true
            mark: layout.checked ? "check" : ""
            Accessible.checkable: true
            Accessible.checked: layout.checked
            onTriggered: miniWin.mini.setLayout(layout.name)
        }
        Entry {
            readonly property var layout: miniWin.mini.layouts[5]
            objectName: "miniLayout_" + layout.name
            label: layout.title
            note: layout.number
            mono: true
            mark: layout.checked ? "check" : ""
            Accessible.checkable: true
            Accessible.checked: layout.checked
            onTriggered: miniWin.mini.setLayout(layout.name)
        }
        Entry {
            readonly property var layout: miniWin.mini.layouts[6]
            objectName: "miniLayout_" + layout.name
            label: layout.title
            note: layout.number
            mono: true
            mark: layout.checked ? "check" : ""
            Accessible.checkable: true
            Accessible.checked: layout.checked
            onTriggered: miniWin.mini.setLayout(layout.name)
        }
        MenuSeparator {
            contentItem: Rectangle { implicitHeight: 1; color: Theme.borderStrong }
        }
        Entry {  // R7.10: slice 9's
            objectName: "miniSleep"
            label: qsTr("Sleep timer")
            mark: "moon"
            later: miniWin.mini.sleepLater
        }
        Entry {
            objectName: "miniStayOnTop"
            label: qsTr("Stay on top")
            mark: miniWin.mini.stayOnTop ? "check" : ""
            Accessible.checkable: true
            Accessible.checked: miniWin.mini.stayOnTop
            onTriggered: miniWin.mini.toggleStayOnTop()
        }
        Entry {
            objectName: "miniShowMain"
            label: qsTr("Show MusiKata")
            note: miniWin.mini.shortcut
            onTriggered: miniWin.mini.close()
        }
        Entry {
            objectName: "miniCloseEntry"
            label: qsTr("Close mini player")
            onTriggered: miniWin.mini.close()
        }
    }
    Connections {  // the tour's M02
        target: miniWin.mini
        function onMenuRequested() { menu.popup(card, card.width - menu.width - 6, -menu.implicitHeight - 8) }
    }

    // ---------- the keys while it has focus (R15.4, R6.9) ----------

    Shortcut { sequence: "Space"; onActivated: miniWin.mini.playPause() }
    Shortcut { sequence: "Ctrl+Right"; onActivated: miniWin.player.next() }
    Shortcut { sequence: "Ctrl+Left"; onActivated: miniWin.player.previous() }
    Shortcut { sequence: "Left"; onActivated: miniWin.player.seekBack() }
    Shortcut { sequence: "Right"; onActivated: miniWin.player.seekAhead() }
    Shortcut { sequence: "Ctrl+Shift+M"; onActivated: miniWin.mini.close() }
    Repeater {
        model: 7
        Item {
            id: layoutKey
            required property int index
            Shortcut { sequence: String(layoutKey.index + 1); onActivated: miniWin.mini.setLayoutNumber(layoutKey.index + 1) }
        }
    }
}
