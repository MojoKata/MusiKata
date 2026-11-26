import QtQuick
import QtQuick.Controls.Basic
import "."

// The header of a library view (R6.4, L01-albums, L03-songs-bulk-edit): the view's title and count,
// the search box (R2.7; `/` focuses it, Esc clears it), the view-mode switch where the view has more
// than one mode, the sort, and the ⋮ menu. When the header is too narrow for everything, the search
// box becomes its icon, which opens it over the title. What each says is the library's.
Item {
    id: header
    required property var library
    property bool open: false           // the search box opened from its icon on a narrow header
    readonly property real fieldMax: 250
    readonly property real fieldMin: 180
    // the room left for the search box between the count and the tools
    readonly property real room: tools.x - 8 - (count.x + count.implicitWidth + 24)
    readonly property bool narrow: room < fieldMin
    readonly property bool overTitle: narrow && (open || field.activeFocus || header.library.search !== "")
    // the tour waits on what is `loading`: here, a search's rows still to come
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
        visible: !header.overTitle
        verticalAlignment: Text.AlignVCenter
        text: header.library.title
        color: Theme.text
        font { family: Theme.sans; pixelSize: 22; weight: Font.Bold }
    }
    Text {
        id: count
        objectName: "viewCount"
        anchors.left: title.right
        anchors.leftMargin: 14
        anchors.baseline: title.baseline
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
                    TapHandler { onTapped: header.library.setAlbumsMode(modelData.mode) }
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

        Rectangle {  // ⋮ (R6.6; Rescan library, R2.3, so far)
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
    }
}
