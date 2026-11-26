import QtQuick
import "."

// The sidebar (R6.3): the app's icon and name, the library's views as they are built (Albums,
// Artists and Songs; Genres, Folders and Needs attention with slices 3 to 6, DEVELOP.md), and the
// music root's card at the bottom (R2.1.1).
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
                ["songs", qsTr("Songs"), "song"]]
        SideItem {
            required property int index
            required property var modelData
            objectName: "side-" + modelData[0]
            y: 90 + index * 36
            width: side.width
            label: modelData[1]
            icon: modelData[2]
            active: side.library.section === modelData[0]
            onClicked: side.library.show(modelData[0])
        }
    }

    Rectangle {
        id: card
        objectName: "rootCard"
        x: 12
        width: side.width - 24
        height: 62
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 14
        radius: 10
        color: Theme.surface
        border.color: Theme.border

        Icon { x: 12; y: 12; size: 16; name: "folder"; color: Theme.accentHi }
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
        Rectangle {
            x: card.width - 20
            y: 16
            width: 8
            height: 8
            radius: 4
            color: side.library.scanning ? Theme.accent : Theme.ok
        }
        Text {
            x: 12
            y: 34
            width: card.width - 24
            height: 18
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: side.library.line
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 11 }
        }
    }
}
