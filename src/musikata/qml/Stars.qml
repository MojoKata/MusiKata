import QtQuick
import "."

// A song's rating, 0 to 5 stars (R10), filled up to it.
Row {
    id: stars
    property int rating
    property real size: 10
    spacing: 1.5
    Repeater {
        model: 5
        Icon {
            required property int index
            name: index < stars.rating ? "star" : "starLine"
            color: index < stars.rating ? Theme.star : Theme.borderStrong
            size: stars.size
            lineWidth: 1.1
        }
    }
}
