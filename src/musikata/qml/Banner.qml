import QtQuick
import "."

// A banner across the view (X02-root-unavailable): its icon, a line in bold and one under it, and
// its buttons at the right, in the tone of what it says: "err", red, for a root or a linked folder
// that isn't there (R2.10); "warn", amber, for the question of songs gone (R2.10.1). What it says
// is the library's.
Rectangle {
    id: banner
    property string tone: "err"
    property string title
    property string detail
    default property alias buttons: row.data
    readonly property color toneColor: banner.tone === "err" ? Theme.err : Theme.warn
    height: 62
    radius: 12
    color: banner.tone === "err" ? Theme.errSoft : Theme.warnSoft
    border.color: Qt.rgba(banner.toneColor.r, banner.toneColor.g, banner.toneColor.b, 0.45)
    Accessible.role: Accessible.AlertMessage
    Accessible.name: banner.title

    Icon {
        x: 15
        anchors.verticalCenter: parent.verticalCenter
        size: 18
        name: "attention"
        color: banner.toneColor
    }
    Text {
        id: titleText
        x: 46
        y: banner.detail !== "" ? 9 : 0
        width: row.x - 16 - x
        height: banner.detail !== "" ? 22 : banner.height
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        text: banner.title
        color: Theme.text
        font { family: Theme.sans; pixelSize: 14; weight: Font.DemiBold }
    }
    Text {
        x: 46
        y: 32
        width: titleText.width
        height: 20
        visible: banner.detail !== ""
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        text: banner.detail
        color: Theme.muted
        font { family: Theme.sans; pixelSize: 12 }
    }
    Row {
        id: row
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
    }
}
