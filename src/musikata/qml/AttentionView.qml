import QtQuick
import QtQuick.Controls.Basic
import "."

// Needs attention (R2.8, L09-needs-attention): the chips across the top, All and a chip per group
// with its count; then each group, a line folded with its count and its first entries and the
// group's own action (Find covers online, a later version's), or open, its heading and note over
// its entries, each with the action that fixes it and Ignore. A group's line opens or folds it.
// A group of copies (R2.12, L09's Same song twice) is drawn whole: its cover, title, artist and
// lengths, Exact copies or Likely, Review… and Ignore, and a row per copy with Keep (a radio
// button), Trash (a checkbox), its format, path, plays and rating, and why the copy proposed is
// kept; the selection bar below counts the copies checked, with Move N to the trash, which asks
// first (musikata.duplicates), and ✕, which unchecks them.
// What each says and does is musikata.attention's; `loading` is what the tour waits on: the
// entries still being found.
Item {
    id: view
    required property var library
    required property var attention
    required property var copies
    readonly property var model: view.library.attention
    readonly property bool loading: view.model.loading

    Flow {
        id: chips
        objectName: "attentionChips"
        x: 28
        y: 2
        width: view.width - 56
        spacing: 8
        Repeater {
            model: view.model.chips
            Chip {
                required property var modelData
                objectName: "attentionChip-" + modelData.name
                label: modelData.label
                chosen: modelData.chosen
                onClicked: view.model.choose(modelData.name)
            }
        }
    }

    ListView {
        id: list
        objectName: "attentionList"
        x: 28
        y: chips.y + chips.height + 18
        width: view.width - 56
        height: view.height - y - (trashBar.visible ? trashBar.height + 24 : 0)
        clip: true
        spacing: 8
        reuseItems: true
        boundsBehavior: Flickable.StopAtBounds
        model: view.model
        delegate: Item {
            id: row
            required property int index
            required property string type
            required property string group
            required property string kind
            required property string badge
            required property var copies
            required property string title
            required property string detail
            required property string cover
            required property string icon
            required property var actions
            required property bool open
            required property string summary
            required property string note
            required property int count
            required property string tone
            readonly property bool same: row.type === "entry" && row.kind === "same-song"
            width: list.width
            height: row.same ? 72 + 52 * row.copies.length : row.type === "entry" ? 68 : row.open ? 40 : 64

            // an open group's heading and note (L09's SAME SONG MORE THAN ONCE)
            Item {
                anchors.fill: parent
                visible: row.type === "group" && row.open
                Accessible.role: Accessible.Button
                Accessible.name: row.title
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: view.model.toggle(row.group) }
                Icon {
                    id: openChev
                    y: 14
                    name: "chevDown"
                    size: 14
                    color: Theme.faint
                }
                Text {
                    id: heading
                    x: openChev.width + 8
                    y: 10
                    height: 22
                    verticalAlignment: Text.AlignVCenter
                    text: row.detail
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 12; weight: Font.Bold; letterSpacing: 0.4 }
                }
                Text {
                    x: heading.x + heading.implicitWidth + 24
                    y: 10
                    width: row.width - x
                    height: 22
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    text: row.note
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 13 }
                }
            }

            // a folded group's line (L09's Wrong encoding, Album in one file)
            Rectangle {
                anchors.fill: parent
                visible: row.type === "group" && !row.open
                radius: 12
                color: foldHover.hovered ? Theme.raised : Theme.surface
                border.color: Theme.border
                Accessible.role: Accessible.Button
                Accessible.name: row.title + ", " + row.summary
                HoverHandler { id: foldHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: view.model.toggle(row.group) }
                Icon {
                    id: chev
                    x: 18
                    anchors.verticalCenter: parent.verticalCenter
                    name: "chevDown"
                    rotation: -90
                    size: 14
                    color: Theme.muted
                }
                Text {
                    id: groupTitle
                    x: 44
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.title
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 15; weight: Font.DemiBold }
                }
                Text {
                    x: groupTitle.x + groupTitle.implicitWidth + 14
                    width: groupActions.x - 16 - x
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: row.summary
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Row {
                    id: groupActions
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Repeater {
                        model: row.type === "group" ? row.actions : []
                        Btn {
                            required property var modelData
                            objectName: "attentionGroup-" + modelData.name
                            label: modelData.label
                            later: modelData.later
                            height: 34
                        }
                    }
                }
            }

            // a group of copies (L09's Signal Fires and Moonpull)
            Rectangle {
                anchors.fill: parent
                visible: row.same
                radius: 12
                color: Theme.surface
                border.color: Theme.border
                Accessible.role: Accessible.Grouping
                Accessible.name: row.title + ", " + row.badge
                Cover {
                    x: 16
                    y: 14
                    width: 36
                    height: 36
                    radius: 6
                    sourceSide: 64
                    matte: Theme.surface
                    emptyText: ""
                    visible: row.same
                    source: row.same ? row.cover : ""
                }
                Text {
                    id: copiesTitle
                    x: 64
                    y: 14
                    width: Math.min(implicitWidth, copiesActions.x - 16 - x - copiesBadge.width - 24 - copiesDetail.implicitWidth)
                    height: 36
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    text: row.title
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 16; weight: Font.DemiBold }
                }
                Text {
                    id: copiesDetail
                    x: copiesTitle.x + copiesTitle.width + 12
                    y: 14
                    width: Math.max(0, Math.min(implicitWidth, copiesActions.x - 16 - x - copiesBadge.width - 12))
                    height: 36
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    text: row.detail
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Chip {
                    id: copiesBadge
                    objectName: "copiesBadge"
                    x: copiesDetail.x + copiesDetail.width + 12
                    y: 19
                    label: row.badge
                    tone: row.badge === "Likely" ? "warn" : "ok"
                }
                Row {
                    id: copiesActions
                    anchors.right: parent.right
                    anchors.rightMargin: 14
                    y: 16
                    spacing: 6
                    Repeater {
                        model: row.same ? row.actions : []
                        Btn {
                            required property var modelData
                            objectName: "attentionAction-" + modelData.name
                            label: modelData.label
                            quiet: modelData.name === "ignore"
                            later: modelData.later
                            height: 32
                            onClicked: view.attention.act(row.index, modelData.name)
                        }
                    }
                }
                Rectangle { x: 14; y: 63; width: parent.width - 28; height: 1; color: Theme.border }
                Column {
                    x: 14
                    y: 64
                    width: parent.width - 28
                    Repeater {
                        model: row.same ? row.copies : []
                        CopyRow {
                            required property var modelData
                            width: parent.width
                            copy: modelData
                            onKeep: view.model.keepCopy(row.index, modelData.song)
                            onToggle: view.model.toggleCopy(row.index, modelData.song)
                        }
                    }
                }
            }

            // an entry: its cover or icon, what it is, why, and its actions
            Rectangle {
                anchors.fill: parent
                visible: row.type === "entry" && !row.same
                radius: 12
                color: Theme.surface
                border.color: Theme.border
                Accessible.role: Accessible.ListItem
                Accessible.name: row.title + ", " + row.detail
                Cover {
                    id: art
                    x: 14
                    anchors.verticalCenter: parent.verticalCenter
                    width: 40
                    height: 40
                    radius: 6
                    sourceSide: 64
                    matte: Theme.surface
                    emptyText: ""
                    visible: row.type === "entry" && row.icon === "album"
                    source: row.cover
                }
                Rectangle {
                    x: 14
                    anchors.verticalCenter: parent.verticalCenter
                    width: 40
                    height: 40
                    radius: 8
                    visible: row.type === "entry" && row.icon !== "album"
                    color: row.tone === "err" ? Theme.errSoft : Theme.raised
                    Icon {
                        anchors.centerIn: parent
                        name: row.icon || "file"
                        size: 18
                        color: row.tone === "err" ? Theme.err : Theme.accentHi
                    }
                }
                Text {
                    id: entryTitle
                    x: 68
                    y: 13
                    width: entryActions.x - 16 - x
                    elide: Text.ElideRight
                    text: row.title
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                }
                Text {
                    x: 68
                    y: 36
                    width: entryTitle.width
                    elide: Text.ElideRight
                    text: row.detail
                    color: row.tone === "err" ? Theme.err : Theme.muted
                    font { family: Theme.sans; pixelSize: 12 }
                }
                Row {
                    id: entryActions
                    anchors.right: parent.right
                    anchors.rightMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6
                    Repeater {
                        model: row.type === "entry" && !row.same ? row.actions : []
                        Btn {
                            required property var modelData
                            objectName: "attentionAction-" + modelData.name
                            label: modelData.label
                            quiet: modelData.name === "ignore"
                            later: modelData.later
                            height: 32
                            onClicked: view.attention.act(row.index, modelData.name)
                        }
                    }
                }
            }
        }
        ScrollBar.vertical: ScrollBar { }
    }

    Rectangle {  // L09's selection bar: the copies checked for the trash, Move N to the trash, ✕
        id: trashBar
        objectName: "trashBar"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 16
        visible: view.model.checkedCount > 0 && !view.copies.moving
        width: Math.min(barRow.width + 40, view.width - 56)
        height: 50
        radius: 12
        color: Theme.raised
        border.color: Theme.borderStrong
        Accessible.role: Accessible.ToolBar
        Accessible.name: view.model.barText
        Row {
            id: barRow
            x: 20
            anchors.verticalCenter: parent.verticalCenter
            spacing: 16
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: view.model.barText
                color: Theme.text
                font { family: Theme.sans; pixelSize: 15; weight: Font.DemiBold }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("plays and rating go to the kept copy")
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 13 }
                visible: trashBar.width < view.width - 56
            }
            Btn {
                objectName: "moveChecked"
                anchors.verticalCenter: parent.verticalCenter
                label: view.model.moveLabel
                quiet: true
                height: 34
                onClicked: view.copies.moveChecked()
            }
            Item {
                objectName: "clearChecked"
                anchors.verticalCenter: parent.verticalCenter
                width: 28
                height: 28
                Accessible.role: Accessible.Button
                Accessible.name: qsTr("Uncheck the copies")
                Rectangle { anchors.fill: parent; radius: 14; color: clearHover.hovered ? Theme.hover : "transparent" }
                Icon { anchors.centerIn: parent; name: "close"; size: 14; color: Theme.muted }
                HoverHandler { id: clearHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: view.model.clearChecked() }
            }
        }
    }

    Text {  // nothing needs attention, or a search found nothing (R2.7)
        objectName: "empty"
        anchors.horizontalCenter: parent.horizontalCenter
        y: list.y + 72
        width: Math.min(implicitWidth, view.width - 56)
        elide: Text.ElideRight
        visible: text !== ""
        text: view.library.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 14 }
    }
}
