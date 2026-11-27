import QtQuick
import "."

// A song's rating, 0 to 5 stars (R10), filled up to it. Where it can be set (`settable`: a list's
// row, the Edit tags panel, the now-playing bar, R10.2) each star is a button that says which was
// clicked; what that does (sets it, or clears it when it is the rating shown) is the bridge's.
Row {
    id: stars
    property int rating
    property real size: 10
    property bool settable: false
    signal clicked(int star)
    spacing: 1.5
    Repeater {
        model: 5
        Item {
            id: star
            required property int index
            width: stars.size
            height: stars.size
            Accessible.role: stars.settable ? Accessible.Button : Accessible.Graphic
            Accessible.name: star.index === 0 ? qsTr("1 star") : qsTr("%1 stars").arg(star.index + 1)
            Icon {
                anchors.centerIn: parent
                name: star.index < stars.rating ? "star" : "starLine"
                color: star.index < stars.rating ? Theme.star
                     : (hover.hovered && stars.settable ? Theme.muted : Theme.borderStrong)
                size: stars.size
                lineWidth: 1.1
            }
            HoverHandler {
                id: hover
                enabled: stars.settable
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                enabled: stars.settable
                gesturePolicy: TapHandler.ReleaseWithinBounds
                onTapped: stars.clicked(star.index + 1)
            }
        }
    }
}
