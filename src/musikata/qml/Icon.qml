import QtQuick
import QtQuick.Shapes
import "."
import "Icons.js" as Icons

// One of the mockups' icons (Icons.js), drawn at `size` px in `color`.
Item {
    id: icon
    property string name
    property color color: Theme.muted
    property real size: 18
    property real lineWidth: 1.7
    width: size
    height: size

    Shape {
        width: 20
        height: 20
        scale: icon.size / 20
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: icon.color
            strokeWidth: icon.lineWidth * 20 / icon.size
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: Icons.stroke(icon.name) }
        }
        ShapePath {
            strokeColor: "transparent"
            fillColor: icon.color
            PathSvg { path: Icons.fill(icon.name) }
        }
    }
}
