import QtQuick
import QtQuick.Controls.Basic
import "."

// The Edit tags panel (R4.2 to R4.4, R4.6 to R4.8; L03-songs-bulk-edit), docked on the right: its
// heading and ×, the cover with what is edited ("Tide Tables", "Lumen Drift · 4 songs") and its
// art's chip, a click on the cover, or an image dropped on it, opening Album art (R5.2, R5.4); a field for each tag (TagField: shared, or mixed with the values in use), the rating
// set by its stars (R10.2), and **More fields** (Composer, Comment, the sort names,
// Compilation), closed until opened and open from then on. For one song, its file and the tags kept
// without showing (R4.8), read only. At its foot: R4.2's question when the selection changes, or it
// closes, with changes not saved; a save's progress with Cancel (R4.7); the files that failed with
// why, Retry and Dismiss; "3 fields will change on 4 songs", **Revert** and **Save to 4 files**.
// The ⋯ menu holds the bulk tools of R4.5 (`tools`), each opening its dialog (ToolDialog; Infer from
// path, R3's own, InferDialog); one that can't be used now is faded and says why in its tooltip.
// Esc or the × closes it. What it shows and does is the bridge's (musikata.edittags).
Rectangle {
    id: panel
    required property var edit
    property var art: null  // the Album art dialog (R5.2)
    property bool loading: panel.edit.loading  // the tour waits while its songs are read
    readonly property real pad: 24
    readonly property real inner: width - 2 * pad
    color: Theme.side
    Accessible.role: Accessible.Pane
    Accessible.name: qsTr("Edit tags")
    Keys.onEscapePressed: panel.edit.hide()

    TapHandler { }  // a click inside the panel stays in it
    Rectangle { width: 1; height: parent.height; color: Theme.border }

    Text {
        objectName: "editHeading"
        x: panel.pad
        y: 26
        width: tools.x - x - 8
        elide: Text.ElideRight
        text: panel.edit.heading
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13; weight: Font.Bold; letterSpacing: 0.5; capitalization: Font.AllUppercase }
    }
    Item {  // ⋯: R4.5's bulk tools
        id: tools
        objectName: "editTools"
        x: close.x - (visible ? width + 4 : 0)
        y: 18
        width: 32
        height: 32
        visible: panel.edit.tools.length > 0 && panel.edit.count > 0
        Accessible.role: Accessible.ButtonMenu
        Accessible.name: qsTr("More tools")
        Rectangle { anchors.fill: parent; radius: 16; color: toolsHover.hovered ? Theme.hover : "transparent" }
        Icon { anchors.centerIn: parent; name: "more"; size: 16; color: Theme.muted }
        HoverHandler { id: toolsHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: toolMenu.popup(tools, 0, tools.height) }
        Menu {
            id: toolMenu
            objectName: "toolMenu"
            Repeater {
                model: panel.edit.tools
                MenuItem {
                    required property var modelData
                    objectName: "tool-" + modelData.name
                    text: modelData.label
                    opacity: modelData.later === "" ? 1 : 0.45
                    Accessible.description: modelData.later
                    ToolTip.visible: hovered && modelData.later !== ""
                    ToolTip.text: modelData.later
                    ToolTip.delay: 400
                    onTriggered: if (modelData.later === "") panel.edit.runTool(modelData.name)
                }
            }
        }
    }
    Item {
        id: close
        objectName: "closeEdit"
        x: parent.width - 48
        y: 18
        width: 32
        height: 32
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Close Edit tags")
        Rectangle { anchors.fill: parent; radius: 16; color: closeHover.hovered ? Theme.hover : "transparent" }
        Icon { anchors.centerIn: parent; name: "close"; size: 16; color: Theme.muted }
        HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: panel.edit.hide() }
    }

    Text {
        objectName: "editEmpty"
        x: panel.pad
        y: 72
        width: panel.inner
        visible: text !== ""
        wrapMode: Text.WordWrap
        text: panel.edit.emptyText
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }

    Flickable {
        id: scroll
        objectName: "editFields"
        y: 80
        width: parent.width
        height: foot.y - y - 8
        visible: panel.edit.count > 0
        clip: true
        contentHeight: body.height + 12
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { }

        Column {
            id: body
            x: panel.pad
            width: panel.inner
            spacing: 8

            Item {  // the cover and what is edited (R4.2)
                width: parent.width
                height: 92
                Cover {
                    id: art
                    width: 76
                    height: 76
                    radius: 8
                    matte: Theme.side
                    source: panel.edit.cover
                    sourceSide: 128
                    emptyText: ""
                    takesImages: panel.art !== null
                    Accessible.role: Accessible.Button
                    Accessible.name: qsTr("Album art")
                    onImageDropped: (urls) => panel.art.dropOnSongs(panel.edit.ids, panel.edit.title, urls)
                    HoverHandler { enabled: panel.art !== null; cursorShape: Qt.PointingHandCursor }
                    TapHandler { enabled: panel.art !== null; onTapped: panel.art.openSongs(panel.edit.ids, panel.edit.title) }
                }
                Text {
                    id: editTitle
                    objectName: "editTitle"
                    x: 92
                    y: 2
                    width: parent.width - x
                    elide: Text.ElideRight
                    text: panel.edit.title
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 17; weight: Font.Bold }
                }
                Text {
                    id: editLine
                    objectName: "editLine"
                    x: 92
                    anchors.top: editTitle.bottom
                    anchors.topMargin: 1
                    width: parent.width - x
                    elide: Text.ElideRight
                    text: panel.edit.line
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Chip {
                    x: 92
                    anchors.top: editLine.bottom
                    anchors.topMargin: 8
                    visible: (panel.edit.artChip.text || "") !== ""
                    label: panel.edit.artChip.text || ""
                    tone: panel.edit.artChip.tone || "ok"
                    tip: panel.edit.artChip.tip || ""
                }
            }

            TagField { width: parent.width; edit: panel.edit; name: "artist" }
            TagField { width: parent.width; edit: panel.edit; name: "album" }
            Row {
                spacing: 16
                TagField { width: (body.width - 16) * 0.64; edit: panel.edit; name: "genres" }
                TagField { width: (body.width - 16) * 0.36; edit: panel.edit; name: "year" }
            }
            Row {
                spacing: 16
                TagField { width: (body.width - 16) / 2; edit: panel.edit; name: "albumartist" }
                TagField { width: (body.width - 16) / 2; edit: panel.edit; name: "disc" }
            }
            Row {
                spacing: 16
                TagField { width: (body.width - 16) * 0.75; edit: panel.edit; name: "title" }
                TagField { width: (body.width - 16) * 0.25; edit: panel.edit; name: "track" }
            }
            Item {  // the rating, set by its stars (R10.2): the current star again clears it
                objectName: "editRating"
                width: parent.width
                height: 54
                Accessible.role: Accessible.Grouping
                Accessible.name: qsTr("Rating") + ": " + (panel.edit.rating.mixed ? qsTr("Mixed: keep each song's own") : panel.edit.rating.stars)
                Text {
                    text: qsTr("Rating")
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Rectangle {
                    y: 20
                    width: parent.width
                    height: 34
                    radius: 8
                    color: Theme.input
                    border.color: panel.edit.rating.changed ? Theme.accent : Theme.border
                    border.width: panel.edit.rating.changed ? 1.5 : 1
                    Stars {
                        id: editStars
                        objectName: "editStars"
                        x: 12
                        anchors.verticalCenter: parent.verticalCenter
                        rating: panel.edit.rating.stars || 0
                        size: 14
                        settable: true
                        onClicked: (star) => panel.edit.rate(star)
                    }
                    Text {  // mixed (R4.3): each song keeps its own until a star is clicked
                        x: editStars.x + editStars.width + 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - x - 24
                        elide: Text.ElideRight
                        visible: panel.edit.rating.mixed === true
                        text: qsTr("Mixed: keep each song's own")
                        color: Theme.faint
                        font { family: Theme.sans; pixelSize: 14 }
                    }
                    Rectangle {  // changed (R4.4)
                        visible: panel.edit.rating.changed === true
                        width: 7
                        height: 7
                        radius: 3.5
                        color: Theme.accent
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                    }
                }
            }

            Item {  // More fields (R4.2): closed until opened, open from then on
                objectName: "moreFields"
                width: parent.width
                height: 36
                visible: !panel.edit.more
                Accessible.role: Accessible.Button
                Accessible.name: qsTr("More fields")
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Icon { anchors.verticalCenter: parent.verticalCenter; name: "chevDown"; size: 14; color: Theme.muted; rotation: -90 }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("More fields")
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.min(implicitWidth, body.width - 140)
                        elide: Text.ElideRight
                        text: qsTr("Composer, Comment, sort names")
                        color: Theme.faint
                        font { family: Theme.sans; pixelSize: 12 }
                    }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: panel.edit.openMore() }
            }
            Column {
                width: parent.width
                spacing: 8
                visible: panel.edit.more
                TagField { width: parent.width; edit: panel.edit; name: "composer" }
                TagField { width: parent.width; edit: panel.edit; name: "comment" }
                TagField { width: parent.width; edit: panel.edit; name: "artistsort" }
                TagField { width: parent.width; edit: panel.edit; name: "albumartistsort" }
                TagField { width: parent.width; edit: panel.edit; name: "albumsort" }
                Row {  // Compilation (R2.5.3): yes, no, or mixed
                    objectName: "compilation"
                    spacing: 10
                    readonly property var field: panel.edit.fields.compilation || ({})
                    Check {
                        anchors.verticalCenter: parent.verticalCenter
                        mark: parent.field.mixed && parent.field.text === "" ? "some" : parent.field.text === "Yes" ? "all" : "none"
                        Accessible.name: qsTr("Compilation")
                        onToggled: panel.edit.setText("compilation", parent.field.text === "Yes" ? "No" : "Yes")
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("Compilation (various artists)")
                        color: Theme.text
                        font { family: Theme.sans; pixelSize: 14 }
                    }
                }
            }

            Column {  // one song's file (R4.8), read only
                objectName: "fileDetails"
                width: parent.width
                spacing: 6
                visible: panel.edit.details.length > 0
                Text {
                    topPadding: 6
                    text: qsTr("File")
                    color: Theme.faint
                    font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4; capitalization: Font.AllUppercase }
                }
                Repeater {
                    model: panel.edit.details
                    Row {
                        required property var modelData
                        spacing: 10
                        Accessible.role: Accessible.StaticText
                        Accessible.name: modelData.label + ": " + modelData.value
                        Text {
                            width: 92
                            text: modelData.label
                            color: Theme.muted
                            font { family: Theme.sans; pixelSize: 13 }
                        }
                        Text {
                            width: body.width - 102
                            wrapMode: Text.WrapAnywhere
                            text: modelData.value
                            color: Theme.cell
                            font { family: Theme.sans; pixelSize: 13 }
                        }
                    }
                }
                Text {
                    topPadding: 10
                    text: qsTr("Kept as they are")
                    color: Theme.faint
                    font { family: Theme.sans; pixelSize: 11; weight: Font.Bold; letterSpacing: 0.4; capitalization: Font.AllUppercase }
                }
                Text {
                    objectName: "keptNote"
                    width: body.width
                    visible: text !== ""
                    wrapMode: Text.WordWrap
                    text: panel.edit.keptNote
                    color: Theme.muted
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Repeater {
                    model: panel.edit.kept
                    Row {
                        required property var modelData
                        spacing: 10
                        Accessible.role: Accessible.StaticText
                        Accessible.name: modelData.label + ": " + modelData.value
                        Text {
                            width: 132
                            elide: Text.ElideRight
                            text: modelData.label
                            color: Theme.muted
                            font { family: Theme.sans; pixelSize: 13 }
                        }
                        Text {
                            width: body.width - 142
                            wrapMode: Text.WrapAnywhere
                            maximumLineCount: 3
                            elide: Text.ElideRight
                            text: modelData.value
                            color: Theme.cell
                            font { family: Theme.sans; pixelSize: 13 }
                        }
                    }
                }
            }
        }
    }

    Column {  // the foot: the question, the save going on, what failed, what will change
        id: foot
        x: panel.pad
        y: parent.height - height - 16
        width: panel.inner
        spacing: 10
        visible: panel.edit.count > 0 || (panel.edit.failed.title || "") !== ""

        Rectangle {  // R4.2: changes not saved, and the selection changed or the panel closes
            objectName: "editQuestion"
            width: parent.width
            height: visible ? askColumn.height + 24 : 0
            visible: (panel.edit.question.text || "") !== ""
            radius: 12
            color: Theme.warnSoft
            border.color: Qt.rgba(Theme.warn.r, Theme.warn.g, Theme.warn.b, 0.45)
            Accessible.role: Accessible.AlertMessage
            Accessible.name: panel.edit.question.text || ""
            Column {
                id: askColumn
                x: 12
                y: 12
                width: parent.width - 24
                spacing: 10
                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: panel.edit.question.text || ""
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
                }
                Row {
                    spacing: 8
                    Btn { objectName: "saveFirst"; label: qsTr("Save"); icon: "check"; height: 32; onClicked: panel.edit.answer("save") }
                    Btn { objectName: "discard"; label: qsTr("Discard"); quiet: true; height: 32; onClicked: panel.edit.answer("discard") }
                }
            }
        }

        Rectangle {  // R4.7: a save of more than a few files, and Cancel
            objectName: "editProgress"
            width: parent.width
            height: visible ? 64 : 0
            visible: (panel.edit.progress.text || "") !== ""
            radius: 12
            color: Theme.surface
            Accessible.role: Accessible.ProgressBar
            Accessible.name: panel.edit.progress.text || ""
            Text {
                x: 12
                y: 10
                width: cancel.x - x - 8
                elide: Text.ElideRight
                text: panel.edit.progress.text || ""
                color: Theme.text
                font { family: Theme.sans; pixelSize: 13 }
            }
            Rectangle {
                x: 12
                y: 42
                width: cancel.x - x - 8
                height: 4
                radius: 2
                color: Theme.border
                Rectangle {
                    width: parent.width * (panel.edit.progress.fraction || 0)
                    height: parent.height
                    radius: 2
                    color: Theme.accent
                }
            }
            Btn {
                id: cancel
                objectName: "cancelSave"
                x: parent.width - width - 10
                anchors.verticalCenter: parent.verticalCenter
                label: qsTr("Cancel")
                height: 32
                onClicked: panel.edit.cancel()
            }
        }

        Rectangle {  // R4.7: the files that failed, with why, and Retry
            objectName: "editFailed"
            width: parent.width
            height: visible ? failedColumn.height + 24 : 0
            visible: (panel.edit.failed.title || "") !== ""
            radius: 12
            color: Theme.errSoft
            border.color: Qt.rgba(Theme.err.r, Theme.err.g, Theme.err.b, 0.45)
            Accessible.role: Accessible.AlertMessage
            Accessible.name: panel.edit.failed.title || ""
            Column {
                id: failedColumn
                x: 12
                y: 12
                width: parent.width - 24
                spacing: 6
                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: panel.edit.failed.title || ""
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 13; weight: Font.DemiBold }
                }
                ListView {
                    width: parent.width
                    height: Math.min(contentHeight, 3 * 40)
                    clip: true
                    model: panel.edit.failed.rows || []
                    delegate: Column {
                        required property var modelData
                        width: ListView.view.width
                        bottomPadding: 4
                        Text {
                            width: parent.width
                            elide: Text.ElideMiddle
                            text: modelData.file
                            color: Theme.text
                            font { family: Theme.sans; pixelSize: 12; weight: Font.DemiBold }
                        }
                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            text: modelData.why
                            color: Theme.cell
                            font { family: Theme.sans; pixelSize: 12 }
                        }
                    }
                }
                Row {
                    spacing: 8
                    Btn { objectName: "retrySave"; label: qsTr("Retry"); icon: "refresh"; height: 32; later: panel.edit.saveNote; onClicked: panel.edit.retry() }
                    Btn { objectName: "dismissFailed"; label: qsTr("Dismiss"); quiet: true; height: 32; onClicked: panel.edit.dismissFailed() }
                }
            }
        }

        Rectangle {  // R4.4: what will change
            objectName: "changeLine"
            width: parent.width
            height: visible ? 32 : 0
            visible: panel.edit.changeLine !== "" && panel.edit.count > 0
            radius: 8
            color: Theme.accentSoft
            Text {
                x: 12
                width: parent.width - 24
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideRight
                text: panel.edit.changeLine
                color: Theme.accentHi
                font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
            }
        }
        Row {
            spacing: 12
            visible: panel.edit.count > 0
            Btn {
                objectName: "revert"
                width: (panel.inner - 12) * 0.4
                label: qsTr("Revert")
                icon: "undo"
                height: 36
                later: panel.edit.canRevert ? "" : qsTr("Nothing to revert")
                onClicked: panel.edit.revert()
            }
            Btn {
                objectName: "saveTags"
                width: (panel.inner - 12) * 0.6
                label: panel.edit.saveLabel
                icon: "check"
                primary: true
                height: 36
                later: panel.edit.canSave ? "" : (panel.edit.saveNote || qsTr("Nothing to save"))
                onClicked: panel.edit.save()
            }
        }
    }
}
