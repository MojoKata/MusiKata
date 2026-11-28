import QtQuick
import QtQuick.Controls.Basic
import "."

// The song's lyrics in Now Playing (R17.2, R17.3, N04-now-playing-lyrics), in place of Up next with
// Waveform and of the queue with No visualization: "Lyrics" and where they come from ("Timed · from
// 04 - Signal Fires.lrc"), Find online… (R17.4, a later slice's, faded) and Edit…; timed lyrics
// followed as the song plays, the lines sung dimmed, the current one large and bright, the next ones
// muted, scrolled smoothly to keep the current line a third of the way down, a line under the pointer
// showing the time a click seeks to (R7.4); plain lyrics as text that scrolls by hand; "Instrumental";
// and a song with none, "No lyrics for this song" with Add… (R17.3.1). What each says and does is
// musikata.lyrics'.
Rectangle {
    id: panel
    required property var lyrics
    readonly property string state_: panel.lyrics.state
    readonly property bool loading: panel.state_ === "loading"  // the tour waits for it
    readonly property real pad: 24
    radius: 16
    color: Qt.rgba(Theme.surface.r, Theme.surface.g, Theme.surface.b, 0.6)
    border.color: Theme.border
    Accessible.role: Accessible.Pane
    Accessible.name: qsTr("Lyrics")

    Text {
        id: heading
        objectName: "lyricsHeading"
        x: panel.pad
        y: 20
        text: qsTr("Lyrics")
        color: Theme.text
        font { family: Theme.sans; pixelSize: 20; weight: Font.Bold }
    }
    Rectangle {  // where they come from
        objectName: "lyricsSource"
        x: panel.pad
        y: Math.max(heading.y + heading.height + 6, buttons.y + buttons.height + 2)
        width: Math.min(source.width + 22, panel.width - 2 * panel.pad)
        height: 24
        radius: 12
        visible: panel.lyrics.source !== ""
        color: Theme.raised
        Accessible.role: Accessible.StaticText
        Accessible.name: panel.lyrics.source
        Row {
            id: source
            x: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Icon { anchors.verticalCenter: parent.verticalCenter; name: "check"; size: 11; color: Theme.muted; lineWidth: 2 }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, panel.width - 2 * panel.pad - 40)
                elide: Text.ElideRight
                text: panel.lyrics.source
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 12; weight: Font.Medium }
            }
        }
    }
    Row {
        id: buttons
        x: panel.width - width - panel.pad + 6
        y: 18
        spacing: 12
        Btn {
            objectName: "findLyrics"
            quiet: true
            icon: "globe"
            label: qsTr("Find online…")
            later: panel.lyrics.findLater
        }
        Btn {
            objectName: "editLyrics"
            visible: panel.lyrics.canEdit
            minWidth: 96
            label: panel.state_ === "missing" ? qsTr("Add…") : qsTr("Edit…")
            onClicked: panel.state_ === "missing" ? panel.lyrics.add() : panel.lyrics.edit()
        }
    }

    Item {
        id: body
        x: 0
        y: 104
        width: panel.width
        height: panel.height - y - 12
        clip: true

        ListView {  // timed lyrics, followed (R17.2)
            id: lines
            objectName: "lyricsLines"
            anchors.fill: parent
            anchors.leftMargin: 6
            anchors.rightMargin: 6
            visible: panel.state_ === "timed"
            model: visible ? panel.lyrics.lines : []
            // read again once the rows are made: a new model sets it back to its first row
            currentIndex: lines.count > 0 ? panel.lyrics.current : -1
            boundsBehavior: Flickable.StopAtBounds
            highlightRangeMode: ListView.ApplyRange
            preferredHighlightBegin: Math.max(0, height / 3 - 30)
            preferredHighlightEnd: preferredHighlightBegin + 60
            // smooth as the song plays; at once for new lyrics, which open at the line sung
            property bool shown: false
            onModelChanged: { lines.shown = false; Qt.callLater(() => lines.shown = true) }
            highlightMoveDuration: lines.shown ? 450 : 0
            highlightFollowsCurrentItem: true
            highlight: Item { }
            Accessible.role: Accessible.List
            Accessible.name: qsTr("Lyrics")
            delegate: Item {
                id: row
                required property var modelData
                required property int index
                readonly property bool now: row.index === panel.lyrics.current
                readonly property bool past: row.index < panel.lyrics.current
                readonly property bool near: row.index <= panel.lyrics.near  // the verse sung
                width: lines.width
                height: row.modelData.gap ? 18 : words.height + (row.now ? 22 : 14)
                Accessible.role: Accessible.ListItem
                Accessible.name: row.modelData.text
                Accessible.selected: row.now
                Rectangle {
                    anchors.fill: parent
                    anchors.topMargin: 1
                    anchors.bottomMargin: 1
                    radius: 8
                    visible: lineHover.hovered && !row.modelData.gap
                    color: Theme.hover
                }
                Text {
                    id: words
                    x: panel.pad - 6
                    width: time.x - x - 12
                    anchors.verticalCenter: parent.verticalCenter
                    wrapMode: Text.WordWrap
                    text: row.modelData.text
                    color: row.now ? Theme.text : row.past ? Theme.faint : row.near ? Theme.cell : Theme.muted
                    opacity: row.past ? 0.75 : 1
                    font { family: Theme.sans; pixelSize: row.now ? 28 : 20; weight: row.now ? Font.ExtraBold : Font.Normal }
                }
                Text {
                    id: time
                    x: row.width - width - 18
                    anchors.verticalCenter: parent.verticalCenter
                    visible: lineHover.hovered && !row.modelData.gap
                    text: row.modelData.timeText
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 12; weight: Font.DemiBold; features: { "tnum": 1 } }
                }
                HoverHandler { id: lineHover; enabled: !row.modelData.gap; cursorShape: Qt.PointingHandCursor }
                TapHandler { enabled: !row.modelData.gap; onTapped: panel.lyrics.seekLine(row.index) }
            }
        }

        Flickable {  // plain lyrics, scrolled by hand (R17.2)
            objectName: "lyricsPlain"
            anchors.fill: parent
            visible: panel.state_ === "plain"
            contentHeight: plain.height + 24
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { }
            Text {
                id: plain
                x: panel.pad
                width: panel.width - 2 * panel.pad
                wrapMode: Text.WordWrap
                lineHeight: 1.35
                text: panel.lyrics.plainText
                color: Theme.cell
                font { family: Theme.sans; pixelSize: 18 }
                Accessible.role: Accessible.StaticText
                Accessible.name: plain.text
            }
        }

        Text {  // "Instrumental", or none for this song (R17.3.1)
            objectName: "lyricsSaid"
            anchors.centerIn: parent
            width: parent.width - 2 * panel.pad
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            visible: panel.state_ === "instrumental" || panel.state_ === "missing"
            text: panel.state_ === "instrumental" ? panel.lyrics.instrumentalText : panel.lyrics.missingText
            color: panel.state_ === "instrumental" ? Theme.cell : Theme.muted
            font { family: Theme.sans; pixelSize: panel.state_ === "instrumental" ? 26 : 16; weight: panel.state_ === "instrumental" ? Font.Bold : Font.Normal }
        }
    }
}
