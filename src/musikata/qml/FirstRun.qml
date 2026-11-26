import QtQuick
import QtQuick.Dialogs
import QtQuick.Shapes
import "."

// The first start (R2.1, X01-first-run): no root configured and none given, so the window asks for
// the folder the music lives in, dropped anywhere onto it, chosen with the platform's folder dialog,
// or the platform's music folder; under it, the three things MusiKata does and the kinds it reads
// (R2.2). What it settles on, and what went wrong, are the FirstRun bridge's (firstrun.py).
Window {
    id: win
    required property var first
    width: 1280
    height: 800
    minimumWidth: 960
    minimumHeight: 600
    title: "MusiKata"
    color: Theme.bg

    Shape {  // the soft light behind the welcome
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: win.width / 2
                centerY: content.y + 158
                centerRadius: 520
                focalX: centerX
                focalY: centerY
                GradientStop { position: 0; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.16) }
                GradientStop { position: 1; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0) }
            }
            PathRectangle { x: 0; y: 0; width: win.width; height: win.height }
        }
    }

    DropArea {
        id: drop
        objectName: "dropArea"
        anchors.fill: parent
        keys: ["text/uri-list"]
        property bool folder: false
        onEntered: (drag) => { drop.folder = win.first.accepts(drag.urls); drag.accepted = drop.folder }
        onExited: drop.folder = false
        onDropped: (dropped) => { drop.folder = false; win.first.drop(dropped.urls) }
    }

    Item {
        id: content
        width: 900
        height: 590
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -18

        Rectangle {
            id: logo
            anchors.horizontalCenter: parent.horizontalCenter
            width: 68
            height: 68
            radius: 20
            gradient: Gradient {
                GradientStop { position: 0; color: Theme.cyan }
                GradientStop { position: 0.55; color: Theme.accent }
                GradientStop { position: 1; color: Theme.pink }
            }
            Repeater {
                model: [14, 28, 40, 22, 32, 16]
                Rectangle {
                    required property int index
                    required property int modelData
                    x: 34 - 22 + index * 8.4 - 2.2
                    y: 34 - modelData / 2
                    width: 4.4
                    height: modelData
                    radius: 2.2
                    color: "#ffffff"
                }
            }
        }
        Text {
            objectName: "welcome"
            y: 88
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: qsTr("Welcome to MusiKata")
            color: Theme.text
            font { family: Theme.sans; pixelSize: 30; weight: Font.Bold }
        }
        Text {
            y: 136
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: qsTr("Point it at the folder your music lives in. Nothing is changed until you say so.")
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 15 }
        }

        Item {
            id: box
            objectName: "dropBox"
            anchors.horizontalCenter: parent.horizontalCenter
            y: 188
            width: 660
            height: 190
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: Theme.accent
                    strokeWidth: 1.5
                    strokeStyle: drop.folder ? ShapePath.SolidLine : ShapePath.DashLine
                    dashPattern: [4, 2.7]
                    fillColor: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, drop.folder ? 0.16 : 0.06)
                    PathRectangle { x: 0.75; y: 0.75; width: box.width - 1.5; height: box.height - 1.5; radius: 18 }
                }
            }
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 32
                size: 40
                lineWidth: 1.5
                name: "folder"
                color: Theme.accentHi
            }
            Text {
                y: 80
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("Drop your music folder here")
                color: Theme.text
                font { family: Theme.sans; pixelSize: 17; weight: Font.DemiBold }
            }
            Text {
                y: 108
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("or")
                color: Theme.faint
                font { family: Theme.sans; pixelSize: 12 }
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 134
                spacing: 20
                Btn {
                    objectName: "chooseFolder"
                    label: qsTr("Choose folder…")
                    icon: "folder"
                    primary: true
                    minWidth: 150
                    height: 34
                    onClicked: pick.open()
                }
                Btn {
                    objectName: "useMusic"
                    label: win.first.musicText
                    minWidth: 150
                    height: 34
                    onClicked: win.first.useMusic()
                }
            }
        }
        Text {
            objectName: "firstError"
            y: box.y + box.height + 10
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            visible: text !== ""
            text: win.first.error
            color: Theme.err
            font { family: Theme.sans; pixelSize: 12; weight: Font.DemiBold }
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 420
            spacing: 18
            Repeater {
                model: [
                    ["wand", qsTr("Tags from paths"), qsTr("Artist/Album/01 - Title.mp3 becomes tags, shown before anything is written.")],
                    ["image", qsTr("Album art, sorted"), qsTr("Finds folder images and embedded art, and puts the same cover on every track.")],
                    ["playlist", qsTr("Plain playlists"), qsTr("M3U playlists with relative paths, readable by any other player.")]
                ]
                Rectangle {
                    required property var modelData
                    width: 288
                    height: 112
                    radius: 14
                    color: Theme.surface
                    border.color: Theme.border
                    Rectangle {
                        x: 18
                        y: 18
                        width: 34
                        height: 34
                        radius: 10
                        color: Theme.accentSoft
                        Icon { anchors.centerIn: parent; size: 18; name: modelData[0]; color: Theme.accentHi }
                    }
                    Text {
                        x: 64
                        y: 18
                        width: parent.width - 64 - 18
                        height: 34
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                        text: modelData[1]
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                    }
                    Text {
                        x: 18
                        y: 60
                        width: parent.width - 36
                        height: 44
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        text: modelData[2]
                        color: Theme.muted
                        font { family: Theme.sans; pixelSize: 12 }
                    }
                }
            }
        }
        Text {
            y: 568
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: qsTr("Supported: MP3, FLAC, M4A/AAC, Ogg Vorbis, Opus, WAV, AIFF")
            color: Theme.faint
            font { family: Theme.sans; pixelSize: 12 }
        }
    }

    FolderDialog {
        id: pick
        title: qsTr("Choose your music folder")
        onAccepted: win.first.choose(selectedFolder.toString())
    }
}
