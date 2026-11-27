import QtQuick
import "."

// The card a drag shows (R6.10, P01-playlist-drag): the first song's cover, "3 songs" and the names
// after it, and the + that says it adds. Main keeps one off the window, which the drag bridge grabs
// as the platform's drag picture; a playlist in the sidebar shows one under it while the tour holds
// a drag still over it.
Item {
    id: card
    property var card: ({})       // the bridge's card: head, names, cover
    readonly property bool loading: art.loading  // its cover still to come: the grab waits for it
    width: 214
    height: 58
    Accessible.role: Accessible.StaticText
    Accessible.name: (card.card.head || "") + ", " + (card.card.names || "")

    Rectangle {
        x: 6
        y: 6
        width: card.width - 12
        height: card.height - 8
        radius: 10
        color: Theme.raised
        opacity: 0.6
    }
    Rectangle {
        id: face
        width: card.width - 10
        height: card.height - 10
        radius: 10
        color: Theme.raised
        border.color: Theme.accent
        border.width: 1.5
        Cover {
            id: art
            x: 9
            anchors.verticalCenter: parent.verticalCenter
            width: 34
            height: 34
            radius: 6
            sourceSide: 64
            matte: Theme.raised
            emptyText: ""
            source: card.card.cover || ""
        }
        Text {
            x: art.x + art.width + 10
            y: 7
            width: face.width - x - 14
            elide: Text.ElideRight
            text: card.card.head || ""
            color: Theme.text
            font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
        }
        Text {
            x: art.x + art.width + 10
            y: 26
            width: face.width - x - 14
            elide: Text.ElideRight
            text: card.card.names || ""
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 12 }
        }
    }
    Rectangle {  // the + of adding
        x: face.width - 12
        y: -6
        width: 18
        height: 18
        radius: 9
        color: Theme.accent
        Icon { anchors.centerIn: parent; name: "plus"; size: 12; color: Theme.bg }
    }
}
