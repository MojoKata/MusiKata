import QtQuick
import "."

// A mosaic of up to four covers (R5.8's table, laid out by models.mosaic): an artist's tile, a
// playlist's (R8.2). With no cover at all, the dashed tile, with the artist's icon or `emptyIcon`.
Item {
    id: mosaic
    property var tiles: []            // [{source, x, y, w, h}], from Python
    property real gap: 2
    property real radius: 10
    property color matte: Theme.bg
    property int sourceSide: 256
    property string emptyIcon: "artist"  // the dashed tile's icon: an artist's, or a playlist's
    readonly property bool loading: {
        for (let i = 0; i < pieces.count; i++)
            if (pieces.itemAt(i) && pieces.itemAt(i).loading) return true
        return false
    }

    Repeater {
        id: pieces
        model: mosaic.tiles
        Cover {
            required property var modelData
            x: modelData.x * (mosaic.width + mosaic.gap)
            y: modelData.y * (mosaic.height + mosaic.gap)
            width: modelData.w * (mosaic.width + mosaic.gap) - mosaic.gap
            height: modelData.h * (mosaic.height + mosaic.gap) - mosaic.gap
            source: modelData.source
            sourceSide: mosaic.sourceSide
            radius: mosaic.tiles.length === 1 ? mosaic.radius : 0
            matte: mosaic.matte
        }
    }
    Corners {  // one rounded corner over the whole, as a single cover has
        anchors.fill: parent
        visible: mosaic.tiles.length > 1
        radius: mosaic.radius
        matte: mosaic.matte
    }
    Cover {
        anchors.fill: parent
        visible: mosaic.tiles.length === 0
        emptyText: qsTr("No art")
        emptyIcon: mosaic.emptyIcon
        radius: mosaic.radius
    }
}
