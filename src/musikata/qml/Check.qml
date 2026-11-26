import QtQuick
import "."

// A row's or a cover's checkbox (R2.9.6): round on a cover, square in List; ticked, or for the
// List header's, "some" with a dash. A tap toggles it.
Rectangle {
    id: check
    signal toggled()
    property string mark: "none"     // "none", "some" or "all"
    property bool round: false
    property bool onImage: false       // drawn over a cover: a dark ring that reads on any picture
    readonly property bool on: mark !== "none"
    width: 20
    height: 20
    radius: round ? width / 2 : 5
    color: on ? Theme.accent : (onImage ? Qt.rgba(0, 0, 0, 0.35) : "transparent")
    border.color: on ? Theme.accent : (onImage ? "#ffffff" : Theme.borderStrong)
    border.width: 1.5
    Accessible.role: Accessible.CheckBox
    Accessible.name: qsTr("Select")
    Accessible.checked: on

    Icon {
        anchors.centerIn: parent
        visible: check.on
        name: check.mark === "some" ? "minus" : "check"
        size: 14
        lineWidth: 2.2
        color: Theme.bg
    }
    TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: check.toggled() }
}
