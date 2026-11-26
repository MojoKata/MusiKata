import QtQuick
import "."

// A view's header (R6.4): its title and count. The search box and the sort come with slice 3.2;
// what a view adds on the right (the view-mode switch) goes in `right`.
Item {
    id: header
    property string title
    property string count
    default property alias tools: toolRow.data
    height: 64

    Text {
        id: titleText
        x: 28
        y: 14
        height: 36
        verticalAlignment: Text.AlignVCenter
        text: header.title
        color: Theme.text
        font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
    }
    Text {
        anchors.left: titleText.right
        anchors.leftMargin: 14
        anchors.baseline: titleText.baseline
        text: header.count
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }
    Row {
        id: toolRow
        anchors.right: parent.right
        anchors.rightMargin: 24
        anchors.verticalCenter: titleText.verticalCenter
        spacing: 8
    }
}
