import QtQuick
import QtQuick.Controls.Basic
import "."

// The sidebar (R6.3): the app's icon and name, the library's views (Albums, Artists, Songs,
// Genres, Folders, and Needs attention with its count, R2.8), and the music root's card at the
// bottom (R2.1.1): its path, its line, and its dot, red with the card when the root isn't there
// (R2.10).
Rectangle {
    id: side
    required property var library
    width: 232
    color: Theme.side

    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }

    Rectangle {
        id: logo
        x: 18
        y: 16
        width: 30
        height: 30
        radius: 9
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.cyan }
            GradientStop { position: 0.55; color: Theme.accent }
            GradientStop { position: 1; color: Theme.pink }
        }
        Repeater {
            model: [6, 12, 17, 10, 14, 7]
            Rectangle {
                required property int index
                required property int modelData
                x: 5.5 + index * 3.6
                y: 15 - modelData / 2
                width: 2
                height: modelData
                radius: 1
                color: "#ffffff"
            }
        }
    }
    Text {
        x: 58
        y: logo.y
        height: logo.height
        verticalAlignment: Text.AlignVCenter
        text: "MusiKata"
        color: Theme.text
        font { family: Theme.sans; pixelSize: 16; weight: Font.Bold }
    }

    Text {
        x: 22
        y: 66
        text: "LIBRARY"
        color: Theme.faint
        font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4 }
    }
    Repeater {
        model: [["albums", qsTr("Albums"), "album"], ["artists", qsTr("Artists"), "artist"],
                ["songs", qsTr("Songs"), "song"], ["genres", qsTr("Genres"), "genre"],
                ["folders", qsTr("Folders"), "folder"], ["attention", qsTr("Needs attention"), "attention"]]
        SideItem {
            required property int index
            required property var modelData
            objectName: "side-" + modelData[0]
            y: 90 + index * 36
            width: side.width
            label: modelData[1]
            icon: modelData[2]
            active: side.library.section === modelData[0]
            badge: modelData[0] === "attention" ? side.library.attentionCount : ""
            onClicked: side.library.show(modelData[0])
        }
    }

    Rectangle {
        id: card
        objectName: "rootCard"
        readonly property bool missing: side.library.dot === "missing"
        x: 12
        width: side.width - 24
        height: 62
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 14
        radius: 10
        color: card.missing ? Theme.errSoft : Theme.surface
        border.color: card.missing ? Qt.rgba(Theme.err.r, Theme.err.g, Theme.err.b, 0.5) : Theme.border
        Accessible.role: Accessible.StaticText
        Accessible.name: side.library.root + ", " + side.library.line
        Accessible.description: side.library.dotTip

        Icon { x: 12; y: 12; size: 16; name: "folder"; color: card.missing ? Theme.err : Theme.accentHi }
        Text {
            x: 36
            y: 8
            width: card.width - 36 - 28
            height: 24
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideMiddle
            text: side.library.root
            color: Theme.text
            font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
        }
        // the dot (R2.1.1): green when up to date, turning while a scan runs, amber when something
        // couldn't be read, red when the root isn't there (R2.10); its tooltip says which
        Item {
            id: dot
            objectName: "rootDot"
            x: card.width - 24
            y: 12
            width: 16
            height: 16
            Rectangle {
                anchors.centerIn: parent
                width: 8
                height: 8
                radius: 4
                visible: side.library.dot !== "scanning"
                color: side.library.dot === "missing" ? Theme.err
                     : side.library.dot === "warn" ? Theme.warn : Theme.ok
            }
            Rectangle {  // a ring with a gap, turning
                id: ring
                anchors.centerIn: parent
                width: 10
                height: 10
                radius: 5
                color: "transparent"
                border.width: 2
                border.color: Theme.accent
                visible: side.library.dot === "scanning"
                Rectangle { x: 6; y: -1; width: 5; height: 5; color: card.color }
                RotationAnimator on rotation {
                    running: ring.visible
                    from: 0
                    to: 360
                    duration: 900
                    loops: Animation.Infinite
                }
            }
            HoverHandler { id: dotHover }
            ToolTip.visible: dotHover.hovered && side.library.dotTip !== ""
            ToolTip.text: side.library.dotTip
            ToolTip.delay: 300
        }
        Text {
            x: 12
            y: 34
            width: card.width - 24
            height: 18
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: side.library.line
            color: card.missing ? Theme.err : Theme.muted
            font { family: Theme.sans; pixelSize: 11; weight: card.missing ? Font.DemiBold : Font.Normal }
        }
    }
}
