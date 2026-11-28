import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Shapes
import MusiKata
import "."

// Now Playing (R11.4), over everything above the now-playing bar, the sidebar and the header
// included; the view it was opened from stays underneath. Its top row: ‹ Library on the left, the
// visualization picker (R11.4.5), the Lyrics switch (R17.3, a later slice's) and the Equalizer button
// (R19.2, a later slice's) in the middle; the window buttons are the system's, as for the rest of the
// window. Esc or ‹ Library closes it (R11.4.4), as the bar's Now Playing button does. Its background
// is tinted with the cover's colour (R6.2.2).
//
// With Waveform (R11.4.1, N01-now-playing-waveform): the cover large on the left, then "Now playing ·
// Track 4 of 10", the title, artist, album, year and genre, the rating (set by its stars, R10.2),
// and the chips of the format, bit depth and sample rate, bit rate and ReplayGain; Up next on the
// right; and across the bottom the song's waveform, large, with the play head and its time, and the
// minute marks: clicking or dragging on it seeks there (R7.4).
//
// With No visualization (R11.4.3, N03-now-playing-queue): the cover with the song's spectrum over its
// lower part (CoverSpectrum, A5.6) and the progress line along its foot; under it the song's words,
// rating and format; and the queue at full size on the right (UpNext, `full`).
//
// With 3D analyzer (R11.4.2, N02-now-playing-3d-analyzer): the analyzer fills the view (Analyzer,
// analyzeritem.py), its octaves along the front, "now" under it and how long ago its back is at the
// horizon; the song's card in the top-left corner, and the gear in the top-right that sets its bands
// and speed (R11.3.1). Its background is N02's, not the cover's colour: each slice's fill must be the
// colour behind it to hide the slices behind. What every text says is the bridges'
// (nowplayingview.py, bridges.py).
Rectangle {
    id: np
    required property var now          // nowplayingview.NowPlayingView
    required property var player
    property var tints: null           // the cover's colour (R6.2.2)
    property var waveforms: null       // the song's waveform (R11.1.1)
    property var ratings: null         // a star clicked rates the song (R10.2)
    property var playlists: null       // the queue's Save as playlist… (R8.3)
    property var dragging: null        // songs dropped on the queue play next (R6.10)
    readonly property var song: now.details
    readonly property string cover: np.song.cover || np.player.cover
    readonly property string tintName: np.tints !== null ? (np.tints.revision, np.tints.of(np.cover)) : ""
    readonly property color tint: np.tintName !== "" ? np.tintName : Theme.bg
    readonly property real k: Math.max(0.6, Math.min(width / 1280, height / 712))  // the mockups' scale
    readonly property bool loading: np.now.mode === "waveform" && np.waveforms !== null && np.waveforms.loading
    color: Theme.bg
    focus: visible
    Keys.onEscapePressed: np.now.close()
    Accessible.role: Accessible.Pane
    Accessible.name: qsTr("Now Playing")

    TapHandler { }  // a click on it stays in it

    // the cover's colour, from behind the cover outwards (R6.2.2)
    Shape {
        id: backdrop
        objectName: "nowPlayingTint"
        anchors.fill: parent
        visible: np.tintName !== "" && np.now.mode !== "analyzer"
        readonly property real cx: np.now.mode === "none" ? noneCover.x + noneCover.width / 2 : waveCover.x + waveCover.width / 2
        readonly property real cy: np.now.mode === "none" ? noneCover.y + noneCover.height / 2 : waveCover.y + waveCover.height / 2
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: backdrop.cx; centerY: backdrop.cy; centerRadius: 720 * np.k
                focalX: backdrop.cx; focalY: backdrop.cy
                GradientStop { position: 0; color: Qt.rgba(np.tint.r, np.tint.g, np.tint.b, 0.85) }
                GradientStop { position: 0.6; color: Qt.rgba(Theme.accentSoft.r, Theme.accentSoft.g, Theme.accentSoft.b, 0.35) }
                GradientStop { position: 1; color: "transparent" }
            }
            PathRectangle { x: 0; y: 0; width: backdrop.width; height: backdrop.height }
        }
    }
    // ---------- 3D analyzer (R11.4.2, N02): under the top row, which it fills the view behind ----------

    Item {
        id: analyzerMode
        objectName: "analyzerMode"
        anchors.fill: parent
        visible: np.now.mode === "analyzer"
        // N02's background, darkest at the top; the slices' fills take its middle
        readonly property color ground: Qt.tint(Theme.bg, Qt.rgba(Theme.accentSoft.r, Theme.accentSoft.g, Theme.accentSoft.b, 0.12))
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0; color: Theme.bg }
                GradientStop { position: 1; color: Qt.tint(Theme.bg, Qt.rgba(Theme.accentSoft.r, Theme.accentSoft.g, Theme.accentSoft.b, 0.25)) }
            }
        }
        Analyzer {  // the landscape (R11.3)
            id: analyzer
            objectName: "analyzer"
            x: 70 * np.k
            y: 70 * np.k
            width: parent.width - 2 * x
            height: parent.height - y - 70 * np.k
            player: np.player
            playing: np.player.playing
            bands: np.now.analyzerBands
            seconds: np.now.analyzerSeconds
            front: Theme.cyan
            back: Theme.accent
            background: analyzerMode.ground
            Accessible.role: Accessible.Animation
            Accessible.name: qsTr("3D analyzer")
        }
        Repeater {  // the octaves along the front (R11.3.1)
            model: analyzer.labels
            Text {
                required property var modelData
                x: analyzer.x + modelData.at * analyzer.width - width / 2
                y: analyzer.y + analyzer.height + 10
                width: 60
                horizontalAlignment: Text.AlignHCenter
                text: modelData.text
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 11 }
            }
        }
        Text {
            objectName: "analyzerNow"
            x: analyzer.x
            y: analyzer.y + analyzer.height + 34
            text: qsTr("now")
            color: Theme.faint
            font { family: Theme.sans; pixelSize: 11 }
        }
        Text {
            objectName: "analyzerAgo"
            x: analyzer.x + analyzer.width - width
            y: analyzer.y + analyzer.horizon - 26
            text: np.now.analyzerAgo
            color: Theme.faint
            font { family: Theme.sans; pixelSize: 11 }
        }
        Rectangle {  // the song's card, top left
            objectName: "analyzerCard"
            x: 28
            y: 64
            width: 300
            height: 70
            radius: 12
            visible: np.player.path !== ""
            color: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.75)
            border.color: Theme.border
            Cover { x: 12; y: 12; width: 46; height: 46; radius: 6; matte: parent.color; source: np.cover; sourceSide: 128; emptyText: "" }
            Text {
                x: 70
                y: 14
                width: parent.width - x - 12
                elide: Text.ElideRight
                text: np.song.title || np.player.title
                color: Theme.text
                font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
            }
            Text {
                x: 70
                y: 36
                width: parent.width - x - 12
                elide: Text.ElideRight
                text: np.player.line
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 12 }
            }
        }
        Rectangle {  // the gear: its bands and speed, and the menu that sets them (R11.3.1)
            id: gear
            objectName: "analyzerGear"
            x: parent.width - width - 28
            y: 64
            width: Math.max(200, gearText.implicitWidth + 64)
            height: 34
            radius: 10
            color: gearMenu.visible ? Theme.accentSoft : (gearHover.hovered ? Theme.hover : Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.75))
            border.color: gearMenu.visible ? Theme.accent : Theme.border
            Accessible.role: Accessible.ButtonMenu
            Accessible.name: qsTr("Analyzer settings: %1").arg(np.now.analyzerText)
            HoverHandler { id: gearHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: gearMenu.popup(gear, gear.width - gearMenu.width, gear.height + 6) }
            Text {
                id: gearText
                x: 12
                width: parent.width - 52
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: np.now.analyzerText
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 12 }
            }
            Icon { x: parent.width - 33; anchors.verticalCenter: parent.verticalCenter; name: "gear"; size: 15; color: Theme.muted }
        }
        Menu {
            id: gearMenu
            objectName: "analyzerMenu"
            width: 200
            topPadding: 8
            bottomPadding: 8
            background: Rectangle { radius: 10; color: Theme.raised; border.color: Theme.borderStrong }
            component Heading: MenuItem {
                id: heading
                property string label
                enabled: false
                implicitHeight: 28
                leftPadding: 18
                contentItem: Text {
                    text: heading.label
                    color: Theme.faint
                    verticalAlignment: Text.AlignVCenter
                    font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4; capitalization: Font.AllUppercase }
                }
                background: Item { }
            }
            component Setting: MenuItem {
                id: setting
                property var choice: ({})     // a choice of nowplayingview's bandChoices or speedChoices
                text: setting.choice.text || ""
                implicitHeight: 34
                leftPadding: 18
                rightPadding: 18
                Accessible.role: Accessible.MenuItem
                Accessible.name: setting.choice.text || ""
                Accessible.checked: setting.choice.checked === true
                contentItem: Item {
                    implicitHeight: 34
                    Text {
                        width: parent.width - 26
                        anchors.verticalCenter: parent.verticalCenter
                        elide: Text.ElideRight
                        text: setting.choice.text || ""
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 13; weight: setting.choice.checked === true ? Font.DemiBold : Font.Normal }
                    }
                    Icon { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; visible: setting.choice.checked === true; name: "check"; size: 13; color: Theme.accentHi; lineWidth: 2 }
                }
                background: Rectangle { x: 6; width: setting.width - 12; radius: 7; color: setting.highlighted ? Theme.hover : "transparent" }
            }
            Heading { label: qsTr("Bands") }
            Setting { objectName: "bands48"; choice: np.now.bandChoices[0]; onTriggered: np.now.setBands(choice.value) }
            Setting { objectName: "bands96"; choice: np.now.bandChoices[1]; onTriggered: np.now.setBands(choice.value) }
            Setting { objectName: "bands128"; choice: np.now.bandChoices[2]; onTriggered: np.now.setBands(choice.value) }
            Heading { label: qsTr("Speed") }
            Setting { objectName: "speedSlow"; choice: np.now.speedChoices[0]; onTriggered: np.now.setSeconds(choice.value) }
            Setting { objectName: "speedNormal"; choice: np.now.speedChoices[1]; onTriggered: np.now.setSeconds(choice.value) }
            Setting { objectName: "speedFast"; choice: np.now.speedChoices[2]; onTriggered: np.now.setSeconds(choice.value) }
        }
    }

    // what the cover's rounded corners are drawn in: the tint near the cover
    readonly property color matte: Qt.tint(Theme.bg, Qt.rgba(np.tint.r, np.tint.g, np.tint.b, np.tintName !== "" ? 0.7 : 0))

    // ---------- the top row ----------

    component TopButton: Rectangle {
        id: top
        signal clicked()
        property string icon
        property string label
        property string name: label
        property string later: ""     // a later slice's: faded, saying so in its tooltip
        property bool open: false
        height: 34
        width: row.width + 36
        radius: 10
        color: top.open ? Theme.accentSoft : (hover.hovered && top.later === "" ? Theme.hover : Theme.surface)
        border.color: top.open ? Theme.accent : Theme.border
        opacity: top.later === "" ? 1 : 0.5
        Accessible.role: Accessible.Button
        Accessible.name: top.name
        Accessible.description: top.later
        HoverHandler { id: hover; cursorShape: top.later === "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
        TapHandler { enabled: top.later === ""; onTapped: top.clicked() }
        ToolTip.visible: hover.hovered && top.later !== ""
        ToolTip.text: top.later
        ToolTip.delay: 400
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 8
            Icon { anchors.verticalCenter: parent.verticalCenter; name: top.icon; size: 16; color: Theme.muted }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: top.label !== ""
                text: top.label
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
            }
        }
    }

    Item {  // ‹ Library: back to the view it was opened from (R11.4.4)
        objectName: "backToLibrary"
        x: 20
        y: 16
        width: back.width + 16
        height: 34
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Back to the library")
        Row {
            id: back
            x: 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            Icon { anchors.verticalCenter: parent.verticalCenter; name: "chevLeft"; size: 14; color: backHover.hovered ? Theme.text : Theme.muted }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("Library")
                color: backHover.hovered ? Theme.text : Theme.muted
                font { family: Theme.sans; pixelSize: 13; weight: Font.Medium }
            }
        }
        HoverHandler { id: backHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: np.now.close() }
    }

    Row {
        id: topRow
        anchors.horizontalCenter: parent.horizontalCenter
        y: 16
        spacing: 10
        Rectangle {  // the visualization picker (R11.4.5): its choice and icon, its menu below
            id: picker
            objectName: "visualizationPicker"
            width: 236
            height: 34
            radius: 10
            color: pickerMenu.visible ? Theme.accentSoft : (pickerHover.hovered ? Theme.hover : Theme.surface)
            border.color: pickerMenu.visible ? Theme.accent : Theme.border
            Accessible.role: Accessible.ComboBox
            Accessible.name: qsTr("Visualization: %1").arg(np.now.modeName)
            HoverHandler { id: pickerHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: pickerMenu.popup(picker, 0, picker.height + 6) }
            Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; name: np.now.modeIcon; size: 15; color: Theme.accentHi }
            Text {
                x: 40
                width: parent.width - 70
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: np.now.modeName
                color: Theme.text
                font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
            }
            Icon { x: parent.width - 27; anchors.verticalCenter: parent.verticalCenter; name: "chevDown"; size: 14; color: Theme.muted }
        }
        TopButton {
            objectName: "lyricsSwitch"
            icon: "lyrics"
            label: qsTr("Lyrics")
            width: 100
            later: np.now.lyricsLater
            Accessible.role: Accessible.CheckBox
        }
        TopButton {
            objectName: "equalizerButton"
            icon: "eq"
            label: ""
            name: qsTr("Equalizer")
            width: 40
            later: np.now.equalizerLater
        }
    }

    Menu {
        id: pickerMenu
        objectName: "visualizationMenu"
        width: picker.width
        topPadding: 8
        bottomPadding: 8
        background: Rectangle { radius: 10; color: Theme.raised; border.color: Theme.borderStrong }
        component Choice: MenuItem {
            id: choice
            property var mode: ({})       // a choice of nowplayingview's `modes`
            text: choice.mode.name || ""
            implicitHeight: 36
            leftPadding: 18
            rightPadding: 18
            Accessible.role: Accessible.MenuItem
            Accessible.name: choice.mode.name || ""
            Accessible.checked: choice.mode.checked === true
            contentItem: Item {
                implicitHeight: 36
                Icon { anchors.verticalCenter: parent.verticalCenter; name: choice.mode.icon || ""; size: 15; color: choice.mode.checked === true ? Theme.accentHi : Theme.muted }
                Text {
                    x: 26
                    width: parent.width - 52
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: choice.mode.name || ""
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 13; weight: choice.mode.checked === true ? Font.DemiBold : Font.Normal }
                }
                Icon { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; visible: choice.mode.checked === true; name: "check"; size: 13; color: Theme.accentHi; lineWidth: 2 }
            }
            background: Rectangle { x: 6; width: choice.width - 12; radius: 7; color: choice.highlighted ? Theme.hover : "transparent" }
        }
        Choice { objectName: "chooseWaveform"; mode: np.now.modes[0]; onTriggered: np.now.setMode(mode.mode) }
        Choice { objectName: "chooseAnalyzer"; mode: np.now.modes[1]; onTriggered: np.now.setMode(mode.mode) }
        Choice { objectName: "chooseNone"; mode: np.now.modes[2]; onTriggered: np.now.setMode(mode.mode) }
    }

    Text {  // nothing playing or cued
        anchors.centerIn: parent
        visible: np.now.emptyText !== ""
        text: np.now.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 14 }
    }

    // the song's words, as both modes set them out
    component Words: Column {
        id: words
        property real titleSize: 44
        property string kicker
        property string title
        property string artist
        property string line
        spacing: 0
        Text {
            objectName: "nowKicker"
            width: words.width
            elide: Text.ElideRight
            text: words.kicker
            color: Theme.cyan
            font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.6; capitalization: Font.AllUppercase }
        }
        Item { width: 1; height: 6 }
        Text {
            objectName: "nowTitle"
            width: words.width
            elide: Text.ElideRight
            text: words.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: words.titleSize; weight: Font.ExtraBold }
        }
        Text {
            objectName: "nowArtist"
            width: words.width
            elide: Text.ElideRight
            text: words.artist
            color: Theme.text
            font { family: Theme.sans; pixelSize: words.titleSize > 36 ? 19 : 17; weight: Font.DemiBold }
        }
        Item { width: 1; height: 6 }
        Text {
            objectName: "nowLine"
            width: words.width
            elide: Text.ElideRight
            text: words.line
            color: Theme.muted
            font { family: Theme.sans; pixelSize: words.titleSize > 36 ? 14 : 13 }
        }
    }

    // ---------- Waveform (R11.4.1, N01) ----------

    Item {
        id: waveMode
        objectName: "waveformMode"
        anchors.fill: parent
        visible: np.now.mode === "waveform" && np.now.emptyText === ""

        Cover {
            id: waveCover
            objectName: "nowCover"
            x: 96 * np.k
            y: 92 * np.k
            width: 330 * np.k
            height: width
            radius: 16
            sourceSide: 512
            matte: np.matte
            source: np.cover
            TapHandler { }  // the cover is a picture here, not a button
        }
        Column {
            id: about
            x: waveCover.x + waveCover.width + 50 * np.k
            y: waveCover.y + 28 * np.k
            width: upNext.x - x - 32
            spacing: 0
            Words { width: about.width; titleSize: 44; kicker: np.song.kicker || ""; title: np.song.title || np.player.title; artist: np.song.artist || ""; line: np.song.line || "" }
            Item { width: 1; height: 26 }
            Stars {
                objectName: "nowRating"
                rating: np.player.rating
                size: 16
                spacing: 5
                settable: np.ratings !== null
                onClicked: (star) => np.ratings.ratePlaying(np.player, star)
            }
            Item { width: 1; height: 14 }
            Flow {
                objectName: "nowChips"
                width: about.width
                spacing: 8
                Repeater {
                    model: np.song.chips || []
                    Rectangle {
                        required property string modelData
                        width: chipText.implicitWidth + 24
                        height: 24
                        radius: 12
                        color: Theme.raised
                        Accessible.role: Accessible.StaticText
                        Accessible.name: modelData
                        Text {
                            id: chipText
                            anchors.centerIn: parent
                            text: parent.modelData
                            color: Theme.muted
                            font { family: Theme.sans; pixelSize: 11; weight: Font.Medium }
                        }
                    }
                }
            }
        }
        Column {  // Up next (N01): the songs to come, first few
            id: upNext
            objectName: "nowUpNext"
            x: parent.width - width - 40 * np.k
            y: waveCover.y
            width: 260
            spacing: 12
            Text {
                text: qsTr("Up next")
                visible: np.now.upNext.length > 0
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4; capitalization: Font.AllUppercase }
            }
            Repeater {
                model: np.now.upNext
                Item {
                    id: next
                    required property var modelData
                    width: upNext.width
                    height: 40
                    Accessible.role: Accessible.ListItem
                    Accessible.name: next.modelData.title
                    Cover { width: 40; height: 40; radius: 6; matte: np.matte; source: next.modelData.cover; sourceSide: 128; emptyText: "" }
                    Text {
                        x: 52
                        y: 1
                        width: next.width - x
                        elide: Text.ElideRight
                        text: next.modelData.title
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 13; weight: Font.Medium }
                    }
                    Text {
                        x: 52
                        y: 21
                        width: next.width - x
                        elide: Text.ElideRight
                        text: next.modelData.line
                        color: Theme.muted
                        font { family: Theme.sans; pixelSize: 12 }
                    }
                }
            }
        }

        // the song's waveform, large, with the play head, its time and the minute marks; clicking or
        // dragging on it seeks there (R7.4)
        Rectangle {
            id: wavePanel
            objectName: "nowWaveformPanel"
            x: 80 * np.k
            width: parent.width - 2 * x
            height: Math.max(120, 210 * np.k)
            y: Math.min(parent.height - height - 24, waveCover.y + waveCover.height + 24 * np.k)
            radius: 16
            color: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.6)
            border.color: Theme.border
            Item {
                id: bigWave
                objectName: "nowSeek"
                x: 16
                y: 26
                width: parent.width - 32
                height: parent.height - 60
                enabled: np.player.seekable
                readonly property bool loading: np.loading  // the tour waits for it
                Accessible.role: Accessible.Slider
                Accessible.name: np.player.timeName
                Waveform {
                    objectName: "nowWaveform"
                    anchors.fill: parent
                    source: np.waveforms
                    progress: np.player.progress
                    barWidth: 3
                    gap: 1.6
                    playedFrom: Theme.cyan
                    playedMid: Theme.accent
                    playedTo: Theme.pink
                    rest: Theme.borderStrong
                }
                Rectangle {  // the play head
                    objectName: "nowPlayHead"
                    visible: np.player.path !== ""
                    x: Math.round(np.player.progress * (bigWave.width - width))
                    y: -12
                    width: 2
                    height: bigWave.height + 24
                    radius: 1
                    color: Theme.text
                }
                Rectangle {  // its time
                    objectName: "nowPlayTime"
                    visible: np.player.path !== ""
                    x: Math.max(-12, Math.min(bigWave.width + 12 - width, np.player.progress * bigWave.width - width / 2))
                    y: -30
                    width: Math.max(52, timeText.implicitWidth + 16)
                    height: 20
                    radius: 6
                    color: Theme.text
                    Text {
                        id: timeText
                        anchors.centerIn: parent
                        text: np.player.positionText
                        color: Theme.bar
                        font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; features: { "tnum": 1 } }
                    }
                }
                Repeater {  // the minute marks
                    model: np.now.marks
                    Item {
                        id: mark
                        required property var modelData
                        x: mark.modelData.at * bigWave.width
                        y: bigWave.height + 4
                        width: 40
                        height: 18
                        Rectangle { width: 1; height: 18; color: Theme.borderStrong }
                        Text {
                            x: 4
                            y: 3
                            text: mark.modelData.text
                            color: Theme.faint
                            font { family: Theme.sans; pixelSize: 11; weight: Font.DemiBold; features: { "tnum": 1 } }
                        }
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    preventStealing: true
                    cursorShape: bigWave.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onPressed: (mouse) => np.player.seekTo(mouse.x / width)
                    onPositionChanged: (mouse) => { if (pressed) np.player.seekTo(mouse.x / width) }
                }
            }
        }
    }

    // ---------- No visualization (R11.4.3, N03) ----------

    Item {
        id: noneMode
        objectName: "queueMode"
        anchors.fill: parent
        visible: np.now.mode === "none"

        Cover {
            id: noneCover
            objectName: "nowQueueCover"
            x: 80 * np.k
            y: 82 * np.k
            width: 340 * np.k
            height: width
            radius: 16
            sourceSide: 512
            matte: np.matte
            source: np.cover
            visible: np.now.emptyText === ""
            Rectangle {  // the lower part darkened under the bars
                anchors.bottom: parent.bottom
                width: parent.width
                height: parent.height * 0.45
                radius: parent.radius
                gradient: Gradient {
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 1; color: "#59000000" }
                }
            }
            CoverSpectrum {  // the song's spectrum, 32 bars (A5.6)
                objectName: "coverSpectrum"
                width: parent.width
                height: parent.height * 0.42
                y: parent.height - 10 - height
                player: np.player
                playing: np.player.playing
            }
            Item {  // the progress line along its foot (R11.4.3), within its rounded corners
                objectName: "progressLine"
                anchors.fill: parent
                Item {
                    y: parent.height - 3
                    width: parent.width
                    height: 3
                    clip: true
                    Rectangle { y: -(noneCover.height - 3); width: noneCover.width; height: noneCover.height; radius: noneCover.radius; color: "#73000000" }
                }
                Item {
                    objectName: "progressDone"
                    y: parent.height - 3
                    width: parent.width * np.player.progress
                    height: 3
                    clip: true
                    Rectangle { y: -(noneCover.height - 3); width: noneCover.width; height: noneCover.height; radius: noneCover.radius; color: Theme.progress }
                }
            }
        }
        Column {
            x: noneCover.x
            y: noneCover.y + noneCover.height + 22
            width: noneCover.width
            visible: np.now.emptyText === ""
            Words { width: parent.width; titleSize: 30; kicker: np.song.kicker || ""; title: np.song.title || np.player.title; artist: np.song.artist || ""; line: np.song.line || "" }
            Item { width: 1; height: 18 }
            Row {
                spacing: 16
                Stars {
                    anchors.verticalCenter: parent.verticalCenter
                    rating: np.player.rating
                    size: 14
                    spacing: 5
                    settable: np.ratings !== null
                    onClicked: (star) => np.ratings.ratePlaying(np.player, star)
                }
                Rectangle {
                    objectName: "nowFormat"
                    anchors.verticalCenter: parent.verticalCenter
                    visible: (np.song.format || "") !== ""
                    width: formatText.implicitWidth + 24
                    height: 22
                    radius: 11
                    color: Theme.raised
                    Accessible.role: Accessible.StaticText
                    Accessible.name: formatText.text
                    Text {
                        id: formatText
                        anchors.centerIn: parent
                        text: np.song.format || ""
                        color: Theme.muted
                        font { family: Theme.sans; pixelSize: 11; weight: Font.Medium }
                    }
                }
            }
        }
        UpNext {  // the queue at full size (R7.2, R11.4.3)
            objectName: "nowQueue"
            x: 480 * np.k
            y: 82 * np.k
            width: parent.width - x - 40 * np.k
            height: parent.height - y - 22
            full: true
            dropIndex: 2
            player: np.player
            model: np.player.queueList
            playlists: np.playlists
            dragging: np.dragging
            focus: noneMode.visible && np.visible
            onEscaped: np.now.close()
            onSavedAsPlaylist: np.now.close()  // its name is edited in the sidebar (R8.3)
        }
    }
}
