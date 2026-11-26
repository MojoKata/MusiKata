import QtQuick
import QtQuick.Shapes
import "."

// An album's cover (R5.1), or the dashed "No album art" tile when it has none or it can't be shown
// (R5.7), under rounded corners drawn in the colour behind it (`matte`). The thumbnail loads off the
// GUI thread (covers.py); `loading` says it hasn't arrived yet, for the tour to wait on.
Item {
    id: cover
    property string source            // image://covers/<name>, or "" for none
    property int sourceSide: 256      // the thumbnail's size asked for (covers.py, SIZES)
    property real radius: 10
    property color matte: Theme.bg
    property string emptyText: qsTr("No album art")
    property string emptyIcon: "image"
    readonly property bool loading: image.status === Image.Loading
    readonly property bool shown: image.status === Image.Ready

    Image {
        id: image
        anchors.fill: parent
        source: cover.source
        sourceSize: Qt.size(cover.sourceSide, cover.sourceSide)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        smooth: true
        visible: cover.shown
    }

    Item {
        anchors.fill: parent
        visible: !cover.shown && !cover.loading
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: Theme.borderStrong
                strokeWidth: 1.5
                strokeStyle: ShapePath.DashLine
                dashPattern: [4, 3]
                fillColor: Theme.surface
                PathRectangle {
                    x: 1
                    y: 1
                    width: cover.width - 2
                    height: cover.height - 2
                    radius: cover.radius
                }
            }
        }
        Icon {
            id: emptyIcon
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: emptyLabel.visible ? -10 : 0
            name: cover.emptyIcon
            size: Math.min(28, cover.width / 3)
            color: Theme.faint
        }
        Text {
            id: emptyLabel
            anchors.top: emptyIcon.bottom
            anchors.topMargin: 6
            x: 6
            width: cover.width - 12
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            visible: cover.width >= 80
            text: cover.emptyText
            color: Theme.faint
            font { family: Theme.sans; pixelSize: 12 }
        }
    }

    Corners {
        anchors.fill: parent
        visible: cover.shown && cover.radius > 0
        radius: cover.radius
        matte: cover.matte
    }
}
