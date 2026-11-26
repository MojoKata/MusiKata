import QtQuick
import QtQuick.Controls.Basic
import "."

// One field of the Edit tags panel (L03-songs-bulk-edit): its label, and the text the songs share or
// what was typed. A mixed field (R4.3) holds nothing and says "Mixed: keep each song's own" in grey;
// its ▾ lists the values in use, each with how many songs have it, and picking one sets it on all. A
// field changed from what the files hold is outlined in the accent with a dot at its end (R4.4); one
// whose text can't be written, in red, saying why in its tooltip. Artist, Album artist, Album and
// Genre suggest the library's values as they are typed (R4.6): ↓ goes into the list, Enter or a click
// takes one, Esc closes it. Everything it shows is the bridge's (musikata.edittags).
Item {
    id: f
    required property var edit
    required property string name
    readonly property var field: f.edit.fields[f.name] || ({})
    readonly property bool changed: f.field.changed === true
    readonly property bool wrong: (f.field.problem || "") !== ""
    readonly property bool suggesting: f.edit.suggestFor === f.name && f.edit.suggestions.length > 0 && (input.activeFocus || list.activeFocus)
    property string placeholder: f.field.placeholder || ""
    implicitHeight: 54
    objectName: "field-" + f.name

    Text {
        id: label
        text: f.field.label || ""
        color: Theme.muted
        width: parent.width
        elide: Text.ElideRight
        font { family: Theme.sans; pixelSize: 13 }
    }
    TextField {
        id: input
        objectName: "input-" + f.name
        y: 20
        width: parent.width
        height: 34
        leftPadding: 12
        rightPadding: 12 + (dot.visible ? 10 : 0) + (values.visible ? 18 : 0)
        text: f.field.text || ""
        placeholderText: f.placeholder
        placeholderTextColor: Theme.faint
        color: Theme.text
        selectionColor: Theme.accentSoft
        selectedTextColor: Theme.text
        selectByMouse: true
        font { family: Theme.sans; pixelSize: 14 }
        Accessible.name: (f.field.label || "") + (f.field.mixed && input.text === "" ? ", " + f.placeholder : "")
        Accessible.description: f.wrong ? f.field.problem : ""
        ToolTip.visible: f.wrong && hovered
        ToolTip.text: f.field.problem || ""
        ToolTip.delay: 300
        background: Rectangle {
            radius: 8
            color: Theme.input
            border.color: f.wrong ? Theme.err : f.changed ? Theme.accent : input.activeFocus ? Theme.borderStrong : Theme.border
            border.width: f.changed || f.wrong ? 1.5 : 1
        }
        onTextEdited: {
            f.edit.setText(f.name, text)
            if (f.field.suggests)
                f.edit.suggest(f.name, text)
        }
        onActiveFocusChanged: if (!activeFocus) Qt.callLater(() => { if (!input.activeFocus && !list.activeFocus) f.edit.clearSuggestions() })
        Keys.onDownPressed: (event) => {
            if (f.suggesting) {
                list.currentIndex = 0
                list.forceActiveFocus()
            } else {
                event.accepted = false
            }
        }
        Keys.onEscapePressed: (event) => {
            if (f.suggesting)
                f.edit.clearSuggestions()
            else
                event.accepted = false
        }

        Rectangle {  // changed (R4.4)
            id: dot
            visible: f.changed || f.wrong
            width: 7
            height: 7
            radius: 3.5
            color: f.wrong ? Theme.err : Theme.accent
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: values.visible ? values.left : parent.right
            anchors.rightMargin: values.visible ? 4 : 12
        }
        Item {  // a mixed field's ▾: the values in use (R4.3)
            id: values
            objectName: "values-" + f.name
            visible: f.field.mixed === true && (f.field.values || []).length > 0
            anchors.right: parent.right
            anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            width: 24
            height: 28
            Accessible.role: Accessible.ButtonMenu
            Accessible.name: qsTr("Values of %1 in use").arg(f.field.label || "")
            Rectangle { anchors.fill: parent; radius: 6; color: valuesHover.hovered ? Theme.hover : "transparent" }
            Icon { anchors.centerIn: parent; name: "chevDown"; size: 14; color: Theme.muted }
            HoverHandler { id: valuesHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: inUse.popup(values, 0, values.height) }
        }
    }
    Menu {
        id: inUse
        objectName: "inUse-" + f.name
        Repeater {
            model: f.field.values || []
            MenuItem {
                required property var modelData
                text: modelData.line
                onTriggered: f.edit.pick(f.name, modelData.text)
            }
        }
    }
    Popup {  // suggestions (R4.6)
        id: suggestions
        objectName: "suggestions-" + f.name
        y: input.y + input.height + 4
        width: input.width
        height: Math.min(list.contentHeight, 8 * 32) + 8
        padding: 4
        visible: f.suggesting
        closePolicy: Popup.NoAutoClose
        background: Rectangle { radius: 8; color: Theme.raised; border.color: Theme.borderStrong }
        ListView {
            id: list
            anchors.fill: parent
            clip: true
            model: f.edit.suggestFor === f.name ? f.edit.suggestions : []
            Accessible.role: Accessible.List
            Accessible.name: qsTr("Suggestions")
            delegate: Rectangle {
                id: item
                required property var modelData
                required property int index
                width: list.width
                height: 32
                radius: 6
                color: list.currentIndex === index && list.activeFocus || itemHover.hovered ? Theme.hover : "transparent"
                Accessible.role: Accessible.ListItem
                Accessible.name: modelData
                Text {
                    x: 10
                    width: parent.width - 20
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: item.modelData
                    color: Theme.text
                    font { family: Theme.sans; pixelSize: 13 }
                }
                HoverHandler { id: itemHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: { f.edit.pickSuggestion(f.name, item.modelData); input.forceActiveFocus() } }
            }
            Keys.onReturnPressed: { f.edit.pickSuggestion(f.name, list.model[list.currentIndex]); input.forceActiveFocus() }
            Keys.onEnterPressed: { f.edit.pickSuggestion(f.name, list.model[list.currentIndex]); input.forceActiveFocus() }
            Keys.onEscapePressed: { f.edit.clearSuggestions(); input.forceActiveFocus() }
            Keys.onUpPressed: { if (list.currentIndex === 0) input.forceActiveFocus(); else list.decrementCurrentIndex() }
        }
    }
}
