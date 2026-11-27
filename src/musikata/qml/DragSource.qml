import QtQuick

// What starts a drag of a row or a tile (R6.10): past the drag threshold, `carry` says what it
// carries (the bridge's carry…: the selection when the row is in it, else the row's own), then the
// drag bridge (musikata.dragging) runs the platform's drag with the card (DragCard) as its picture.
// It takes the pointer over from a click's handler and from the list it is in, and is off while a
// drag runs (the platform has the pointer then), which also lets go of a drag the platform ended.
DragHandler {
    id: source
    property var dragging: null
    signal carry()
    target: null
    enabled: source.dragging !== null && !source.dragging.busy
    grabPermissions: PointerHandler.CanTakeOverFromAnything
    onActiveChanged: {
        if (source.active && source.dragging !== null) {
            source.carry()
            source.dragging.start(source.parent)
        }
    }
}
