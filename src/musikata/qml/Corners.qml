import QtQuick
import QtQuick.Shapes
import "."

// Rounded corners over a picture: what lies outside a rounded rectangle of its size, filled with
// the colour behind it.
Shape {
    id: corners
    property real radius: 10
    property color matte: Theme.bg
    preferredRendererType: Shape.CurveRenderer
    ShapePath {
        strokeColor: "transparent"
        fillColor: corners.matte
        fillRule: ShapePath.OddEvenFill
        PathSvg {
            readonly property real w: corners.width
            readonly property real h: corners.height
            readonly property real r: corners.radius
            path: `M0 0H${w}V${h}H0Z M${r} 0H${w - r}A${r} ${r} 0 0 1 ${w} ${r}V${h - r}`
                + `A${r} ${r} 0 0 1 ${w - r} ${h}H${r}A${r} ${r} 0 0 1 0 ${h - r}V${r}`
                + `A${r} ${r} 0 0 1 ${r} 0Z`
        }
    }
}
