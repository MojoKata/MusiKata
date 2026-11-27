import QtQuick
import "."

// R2.11's question before copies go to the trash (R2.12, R6.8): "Move 2 songs to the trash?",
// naming the files, what the kept copies take and what Undo can't do, with Cancel and Move to
// trash; over the window, or over the Review… dialog it was asked from. Esc cancels. What it says
// is musikata.duplicates'.
Item {
    id: ask
    required property var copies
    readonly property var question: ask.copies.question
    visible: ask.question.title !== undefined
    onVisibleChanged: if (visible) card.forceActiveFocus()

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        TapHandler { }
        WheelHandler { }
    }
    FocusScope {
        id: card
        objectName: "copiesQuestion"
        width: Math.min(parent.width - 96, 560)
        height: detail.y + detail.height + 96
        anchors.centerIn: parent
        Accessible.role: Accessible.AlertMessage
        Accessible.name: ask.question.title || ""
        Keys.onEscapePressed: ask.copies.answer(false)

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: heading
            objectName: "questionTitle"
            x: 28
            y: 26
            width: parent.width - 56
            wrapMode: Text.WordWrap
            text: ask.question.title || ""
            color: Theme.text
            font { family: Theme.sans; pixelSize: 20; weight: Font.Bold }
        }
        Text {
            id: detail
            objectName: "questionDetail"
            x: 28
            anchors.top: heading.bottom
            anchors.topMargin: 10
            width: parent.width - 56
            wrapMode: Text.WordWrap
            text: ask.question.detail || ""
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 14 }
        }
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 28
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 24
            spacing: 12
            Btn {
                objectName: "cancelQuestion"
                minWidth: 110
                label: qsTr("Cancel")
                height: 40
                onClicked: ask.copies.answer(false)
            }
            Btn {
                objectName: "answerMove"
                minWidth: 150
                label: ask.question.yes || ""
                primary: true
                height: 40
                onClicked: ask.copies.answer(true)
            }
        }
    }
}
