import QtQuick
import QtQuick.Controls.Basic
import "."

// The header of a library view (R6.4, L01-albums, L03-songs-bulk-edit): the view's title and count,
// the search box (R2.7; `/` focuses it, Esc clears it), the view-mode switch where the view has more
// than one mode, the sort, and the ⋮ menu. When the header is too narrow for everything, the search
// box becomes its icon, which opens it over the title. In Folders the title is the open folder's
// path, a crumb per folder, each opening its folder; when they don't fit, the middle ones become …,
// a menu of them (R2.9.1, L05, L08). Over a page (an album's, an artist's: L02-album, L11-artist)
// the way back stands in the title's place, the count says what a search leaves of the page, and
// the search filters the page (R2.7). What each says is the library's.
Item {
    id: header
    required property var library
    property var history: null
    property bool open: false           // the search box opened from its icon on a narrow header
    readonly property real fieldMax: 250
    readonly property real fieldMin: 180
    // the room left for the search box between the count and the tools
    readonly property real room: tools.x - 8 - (count.x + count.implicitWidth + 24)
    readonly property bool narrow: room < fieldMin
    readonly property bool overTitle: narrow && (open || field.activeFocus || header.library.search !== "")
    // the tour waits on what is `loading`: here, the rows of a search or a long list still to come
    readonly property bool loading: header.library.searching
    height: 64

    function openSearch() {
        header.open = true
        field.forceActiveFocus()
        field.selectAll()
    }

    Text {
        id: title
        x: 28
        y: 14
        height: 36
        visible: !header.overTitle && !crumbs.visible && !back.visible
        verticalAlignment: Text.AlignVCenter
        text: header.library.title
        color: Theme.text
        font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
    }
    // the crumbs (R2.9.1): the first, then … for those folded, then the rest; the last in the
    // title's weight
    readonly property var crumbList: header.library.crumbs
    readonly property real crumbGap: 26     // a separator and the space around it
    readonly property var crumbWidths: {
        const out = []
        for (let i = 0; i < measure.count; i++)
            out.push(measure.itemAt(i) ? measure.itemAt(i).implicitWidth : 0)
        return out
    }
    // the room the crumbs may take: what is left with the search as its icon, beside the count
    readonly property real crumbRoom: tools.x - 8 - 34 - 24 - count.implicitWidth - 14 - 28
    readonly property int folded: crumbList.length && measure.count === crumbList.length
        ? header.library.folders.foldCrumbs(crumbWidths, crumbRoom, ellipsisMeasure.implicitWidth, crumbGap) : 0
    readonly property var shownCrumbs: {
        if (!folded)
            return crumbList.map((c, i) => ({ name: c.name, path: c.path, index: i }))
        return [{ name: crumbList[0].name, path: crumbList[0].path, index: 0 },
                { name: "…", path: "", index: -1 }]
            .concat(crumbList.slice(1 + folded).map((c, i) => ({ name: c.name, path: c.path, index: 1 + folded + i })))
    }
    Repeater {
        id: measure
        model: header.crumbList
        Text {
            required property int index
            required property var modelData
            visible: false
            text: modelData.name
            font { family: Theme.sans; pixelSize: 22; weight: index === header.crumbList.length - 1 ? Font.Bold : Font.Normal }
        }
    }
    Text { id: ellipsisMeasure; visible: false; text: "…"; font { family: Theme.sans; pixelSize: 22 } }

    Row {
        id: crumbs
        objectName: "crumbs"
        x: 28
        y: 14
        height: 36
        spacing: 8
        visible: header.crumbList.length > 0 && !header.overTitle
        Repeater {
            model: header.shownCrumbs
            Row {
                id: crumb
                required property int index
                required property var modelData
                readonly property bool last: modelData.index === header.crumbList.length - 1
                height: 36
                spacing: 8
                Text {
                    objectName: "crumb"
                    anchors.verticalCenter: parent.verticalCenter
                    width: crumb.last ? Math.min(implicitWidth, Math.max(40, header.crumbRoom - crumb.x)) : implicitWidth
                    elide: Text.ElideRight
                    text: crumb.modelData.name
                    color: crumb.last ? Theme.text : (crumbHover.hovered ? Theme.cell : Theme.muted)
                    font { family: Theme.sans; pixelSize: 22; weight: crumb.last ? Font.Bold : Font.Normal }
                    Accessible.role: crumb.last ? Accessible.StaticText : Accessible.Link
                    Accessible.name: crumb.modelData.index < 0 ? qsTr("More folders") : text
                    HoverHandler { id: crumbHover; enabled: !crumb.last; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        enabled: !crumb.last
                        onTapped: crumb.modelData.index < 0
                            ? foldedMenu.popup(parent, 0, parent.height + 4)
                            : header.library.folders.open(crumb.modelData.path)
                    }
                }
                Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !crumb.last
                    name: "chevLeft"
                    rotation: 180
                    size: 16
                    color: Theme.faint
                }
            }
        }
    }
    Menu {
        id: foldedMenu
        Repeater {
            model: header.crumbList.slice(1, 1 + header.folded)
            MenuItem {
                required property var modelData
                text: modelData.name
                onTriggered: header.library.folders.open(modelData.path)
            }
        }
    }

    Item {  // a page's way back, where a view's title is: its chevron and the view or page it goes to
        id: back
        objectName: "back"
        visible: header.library.onPage && !header.overTitle
        x: 24
        anchors.verticalCenter: title.verticalCenter
        width: backLabel.x + backLabel.width + 4 - x
        height: 28
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Back to %1").arg(header.library.backText)
        HoverHandler { id: backHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: header.library.back() }
    }
    Icon {
        id: backIcon
        visible: back.visible
        x: back.x + 4
        anchors.verticalCenter: back.verticalCenter
        name: "chevLeft"
        size: 14
        color: Theme.muted
    }
    Text {  // the count's sibling, so the count sits on its line
        id: backLabel
        visible: back.visible
        x: backIcon.x + backIcon.width + 4
        anchors.verticalCenter: back.verticalCenter
        text: header.library.backText
        color: backHover.hovered ? Theme.text : Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }

    Text {
        id: count
        objectName: "viewCount"
        anchors.left: crumbs.visible ? crumbs.right : back.visible ? backLabel.right : title.right
        anchors.leftMargin: 14
        anchors.baseline: back.visible ? backLabel.baseline : title.baseline
        visible: !header.overTitle
        text: header.library.viewCount
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 13 }
    }

    TextField {
        id: field
        objectName: "search"
        visible: !header.narrow || header.overTitle
        x: header.overTitle ? 20 : tools.x - 8 - width
        width: header.overTitle ? tools.x - 8 - 20 : Math.min(header.fieldMax, header.room)
        height: 34
        anchors.verticalCenter: title.verticalCenter
        leftPadding: 36
        rightPadding: hint.visible ? 36 : 12
        text: header.library.search
        placeholderText: header.library.searchHint
        placeholderTextColor: Theme.faint
        color: Theme.text
        selectionColor: Theme.accentSoft
        selectedTextColor: Theme.text
        font { family: Theme.sans; pixelSize: 13 }
        Accessible.name: qsTr("Search")
        background: Rectangle {
            radius: 10
            color: Theme.input
            border.color: field.activeFocus ? Theme.accent : Theme.border
        }
        onTextEdited: header.library.setSearch(text)
        Keys.onEscapePressed: {
            if (text !== "") {
                header.library.setSearch("")
            } else {
                header.open = false
                field.focus = false
            }
        }
        onActiveFocusChanged: if (!activeFocus && text === "") header.open = false

        Icon {
            x: 12
            anchors.verticalCenter: parent.verticalCenter
            name: "search"
            size: 16
            color: Theme.muted
        }
        Rectangle {  // the key that focuses it
            id: hint
            visible: field.text === "" && !field.activeFocus
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: 20
            height: 20
            radius: 5
            color: Theme.raised
            border.color: Theme.borderStrong
            Text {
                anchors.centerIn: parent
                text: "/"
                color: Theme.muted
                font { family: Theme.sans; pixelSize: 11 }
            }
        }
    }
    Connections {  // the search set from Python (a view opened, a page left): the box follows
        target: header.library
        function onSearchChanged() {
            if (field.text !== header.library.search)
                field.text = header.library.search
        }
    }

    Rectangle {  // the search box's icon, on a narrow header
        objectName: "searchIcon"
        visible: header.narrow && !header.overTitle
        x: tools.x - 8 - width
        anchors.verticalCenter: title.verticalCenter
        width: 34
        height: 34
        radius: 8
        color: searchHover.hovered ? Theme.hover : "transparent"
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Search")
        HoverHandler { id: searchHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: header.openSearch() }
        Icon { anchors.centerIn: parent; name: "search"; size: 18; color: Theme.muted }
    }

    Row {
        id: tools
        anchors.right: parent.right
        anchors.rightMargin: 24
        anchors.verticalCenter: title.verticalCenter
        spacing: 8

        Rectangle {  // the view-mode switch (R6.4)
            objectName: "modes"
            visible: header.library.modes.length > 1
            width: 6 + 35 * header.library.modes.length
            height: 34
            radius: 8
            color: Theme.surface
            border.color: Theme.border
            Repeater {
                model: header.library.modes
                Rectangle {
                    required property int index
                    required property var modelData
                    x: 3 + index * 35
                    y: 3
                    width: 35
                    height: 28
                    radius: 6
                    color: header.library.mode === modelData.mode ? Theme.raised : "transparent"
                    Accessible.role: Accessible.RadioButton
                    Accessible.name: modelData.label
                    Accessible.checked: header.library.mode === modelData.mode
                    Icon {
                        anchors.centerIn: parent
                        name: modelData.icon
                        size: 16
                        color: header.library.mode === modelData.mode ? Theme.text : Theme.muted
                    }
                    TapHandler { onTapped: header.library.setMode(modelData.mode) }
                }
            }
        }

        Rectangle {  // the sort (R6.4)
            id: sortButton
            objectName: "sort"
            visible: header.library.sorts.length > 0
            width: sortRow.width + 28
            height: 34
            radius: 8
            color: sortHover.hovered ? Theme.hover : Theme.surface
            border.color: Theme.border
            Accessible.role: Accessible.ButtonMenu
            Accessible.name: header.library.sortText
            HoverHandler { id: sortHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: sortMenu.popup(sortButton, 0, sortButton.height + 4) }
            Row {
                id: sortRow
                anchors.centerIn: parent
                spacing: 6
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: header.library.sortText
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 13 }
                }
                Icon { anchors.verticalCenter: parent.verticalCenter; name: "chevDown"; size: 14; color: Theme.muted }
            }
        }

        Rectangle {  // ⋮ (R6.6; Rescan library, R2.3, and Change history, R4.9, so far)
            id: moreButton
            objectName: "more"
            width: 34
            height: 34
            radius: 8
            color: moreHover.hovered ? Theme.hover : "transparent"
            Accessible.role: Accessible.ButtonMenu
            Accessible.name: qsTr("More")
            HoverHandler { id: moreHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: moreMenu.popup(moreButton, moreButton.width - moreMenu.width, moreButton.height + 4) }
            Icon { anchors.centerIn: parent; name: "more"; size: 18; color: Theme.muted }
        }
    }

    Menu {
        id: sortMenu
        Repeater {
            model: header.library.sorts
            MenuItem {
                required property var modelData
                text: modelData.label
                checkable: true
                checked: header.library.sort === modelData.sort
                onTriggered: header.library.setSort(modelData.sort)
            }
        }
    }
    Menu {
        id: moreMenu
        objectName: "moreMenu"
        MenuItem {
            objectName: "rescan"
            text: qsTr("Rescan library")
            enabled: !header.library.scanning
            onTriggered: header.library.rescan()
        }
        MenuItem {
            objectName: "changeHistory"
            text: qsTr("Change history")
            enabled: header.history !== null
            onTriggered: header.history.show()
        }
    }
}
