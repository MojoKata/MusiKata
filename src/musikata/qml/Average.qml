import QtQuick
import "."

// An album's or artist's rating on its page (R10.1): the average of its rated songs, as stars and
// in words ("4.3 average of 9 rated songs"); hidden when none is rated. The bridge works it out.
Row {
    id: average
    required property var value
    visible: average.value.text !== undefined
    spacing: 6
    Accessible.role: Accessible.StaticText
    Accessible.name: average.value.text || ""
    Stars {
        anchors.verticalCenter: parent.verticalCenter
        rating: average.value.stars || 0
        size: 12
    }
    Text {
        anchors.verticalCenter: parent.verticalCenter
        text: average.value.text || ""
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }
}
