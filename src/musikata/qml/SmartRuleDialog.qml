import QtQuick
import QtQuick.Controls.Basic
import "."

// New smart playlist… and Edit rule (R8.9), over the window, drawn after Export…'s dialog: its
// title; each condition with its box, its label and its value (the stars of a rating, a genre's or
// an artist's name, two years, a number of days or of plays), a value typed ticking its box; the
// limit, with its box and its number of songs; the order, one of its chips chosen; and the footer
// with how many songs the rule matches as it changes, or why it can't be saved yet, Cancel and
// Save. Esc cancels too. Every condition ticked must hold. What it says and does is musikata.smart's.
Item {
    id: dialog
    required property var smart
    readonly property real pad: 28
    readonly property var conditions: dialog.smart.conditions
    visible: dialog.smart.opened
    onVisibleChanged: if (visible) card.forceActiveFocus()

    component Field: TextField {  // a value typed: a name, a year, a number
        id: field
        property string name
        height: 34
        leftPadding: 10
        rightPadding: 10
        color: Theme.text
        selectionColor: Theme.accentSoft
        selectedTextColor: Theme.text
        selectByMouse: true
        font { family: Theme.sans; pixelSize: 13 }
        onTextEdited: dialog.smart.setValue(field.name, text)
        background: Rectangle {
            radius: 7
            color: Theme.input
            border.color: field.activeFocus ? Theme.accent : Theme.borderStrong
        }
    }
    component Condition: Item {  // a condition: its box, its label, its value, its unit
        id: cond
        required property int index
        readonly property var c: dialog.conditions[cond.index] || ({})
        width: parent.width
        height: 38
        Accessible.role: Accessible.Grouping
        Accessible.name: cond.c.label || ""
        Check {
            id: box
            objectName: "smartOn-" + cond.c.name
            anchors.verticalCenter: parent.verticalCenter
            mark: cond.c.on ? "all" : "none"
            Accessible.name: cond.c.label || ""
            onToggled: dialog.smart.setOn(cond.c.name, !cond.c.on)
        }
        Text {
            id: label
            x: 32
            width: 150
            height: parent.height
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: cond.c.label || ""
            color: cond.c.on ? Theme.text : Theme.muted
            font { family: Theme.sans; pixelSize: 13 }
            TapHandler { onTapped: dialog.smart.setOn(cond.c.name, !cond.c.on) }
        }
        Row {
            x: label.x + label.width + 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            Stars {  // a rating's stars (R10): a click sets the least it may be
                objectName: "smartStars"
                anchors.verticalCenter: parent.verticalCenter
                visible: cond.c.name === "rating"
                rating: Number(cond.c.value || 0)
                size: 18
                spacing: 4
                settable: true
                onClicked: (star) => dialog.smart.setValue("rating", String(star))
            }
            Field {
                objectName: "smartValue-" + cond.c.name
                visible: cond.c.name !== "rating"
                name: cond.c.name || ""
                width: cond.c.name === "genre" || cond.c.name === "artist" ? 260 : 80
                text: cond.c.value || ""
                Accessible.name: cond.c.label || ""
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: text !== ""
                text: cond.c.unit || ""
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13 }
            }
            Field {  // the year the years run to
                objectName: "smartValue-to"
                visible: cond.c.name === "years"
                name: "to"
                width: 80
                text: cond.c.to || ""
                Accessible.name: qsTr("To the year")
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
        TapHandler { }
        WheelHandler { }
    }
    FocusScope {
        id: card
        objectName: "smartDialog"
        width: Math.min(parent.width - 96, 620)
        height: orders.y + orders.height + 24 + foot.height
        anchors.centerIn: parent
        Accessible.role: Accessible.Dialog
        Accessible.name: dialog.smart.title
        Keys.onEscapePressed: dialog.smart.cancel()

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: Theme.side
            border.color: Theme.borderStrong
        }
        Text {
            id: title
            objectName: "smartTitle"
            x: dialog.pad
            y: 24
            width: parent.width - 2 * dialog.pad
            elide: Text.ElideRight
            text: dialog.smart.title
            color: Theme.text
            font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
        }
        Text {
            id: lead
            x: dialog.pad
            anchors.top: title.bottom
            anchors.topMargin: 6
            width: parent.width - 2 * dialog.pad
            wrapMode: Text.Wrap
            text: qsTr("Its songs are those that meet every condition ticked, kept current as the library changes.")
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 13 }
        }
        Column {
            id: rows
            x: dialog.pad
            anchors.top: lead.bottom
            anchors.topMargin: 14
            width: parent.width - 2 * dialog.pad
            spacing: 4
            Condition { index: 0 }
            Condition { index: 1 }
            Condition { index: 2 }
            Condition { index: 3 }
            Condition { index: 4 }
            Condition { index: 5 }
            Rectangle { width: parent.width; height: 1; color: Theme.border }
            Item {  // the limit: the first N songs in its order, or every one
                width: parent.width
                height: 38
                Check {
                    objectName: "smartOn-limit"
                    anchors.verticalCenter: parent.verticalCenter
                    mark: dialog.smart.limitOn ? "all" : "none"
                    Accessible.name: qsTr("Limit to")
                    onToggled: dialog.smart.setOn("limit", !dialog.smart.limitOn)
                }
                Text {
                    id: limitLabel
                    x: 32
                    width: 150
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("Limit to")
                    color: dialog.smart.limitOn ? Theme.text : Theme.muted
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Row {
                    x: limitLabel.x + limitLabel.width + 8
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Field {
                        objectName: "smartValue-limit"
                        name: "limit"
                        width: 80
                        text: dialog.smart.limit
                        Accessible.name: qsTr("Limit to")
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("songs")
                        color: Theme.muted
                        font { family: Theme.sans; pixelSize: 13 }
                    }
                }
            }
        }
        Text {
            id: orderLabel
            x: dialog.pad
            anchors.top: rows.bottom
            anchors.topMargin: 12
            text: qsTr("Order")
            color: Theme.muted
            font { family: Theme.sans; pixelSize: 13 }
        }
        Flow {
            id: orders
            x: dialog.pad
            anchors.top: orderLabel.bottom
            anchors.topMargin: 8
            width: parent.width - 2 * dialog.pad
            spacing: 8
            Repeater {
                model: dialog.smart.orders
                Chip {
                    required property var modelData
                    objectName: "smartOrder-" + modelData.order
                    label: modelData.label
                    chosen: modelData.chosen
                    onClicked: dialog.smart.setOrder(modelData.order)
                }
            }
        }
        Item {
            id: foot
            width: parent.width
            height: 76
            anchors.bottom: parent.bottom
            Text {
                objectName: "smartMatches"
                x: dialog.pad
                width: buttons.x - x - 16
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                text: dialog.smart.matchText
                color: dialog.smart.saveLater ? Theme.warn : Theme.muted
                font { family: Theme.sans; pixelSize: 13 }
            }
            Row {
                id: buttons
                x: parent.width - width - dialog.pad
                anchors.verticalCenter: parent.verticalCenter
                spacing: 12
                Btn {
                    objectName: "cancelSmart"
                    minWidth: 110
                    height: 40
                    label: qsTr("Cancel")
                    onClicked: dialog.smart.cancel()
                }
                Btn {
                    objectName: "saveSmart"
                    minWidth: 110
                    height: 40
                    primary: true
                    label: qsTr("Save")
                    later: dialog.smart.saveLater
                    onClicked: dialog.smart.save()
                }
            }
        }
    }
}
