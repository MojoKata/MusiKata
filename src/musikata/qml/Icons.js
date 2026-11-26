.pragma library
// Icon paths on a 20-unit square, the mockups' set (docs/mockups/src/render.py, icon()): `stroke`
// is drawn as lines, `fill` filled.
function ellipse(cx, cy, rx, ry) {
    return `M${cx - rx} ${cy}a${rx} ${ry} 0 1 0 ${2 * rx} 0a${rx} ${ry} 0 1 0 ${-2 * rx} 0Z`
}
function starPoints(r) {
    let d = ""
    for (let i = 0; i < 10; i++) {
        const a = -Math.PI / 2 + i * Math.PI / 5
        const rr = i % 2 === 0 ? r : r * 0.45
        d += (i ? "L" : "M") + (10 + rr * Math.cos(a)).toFixed(2) + " " + (10 + rr * Math.sin(a)).toFixed(2)
    }
    return d + "Z"
}
const STROKE = {
    song: "M8 14.5V3.5L15 2.5V12.5",
    album: ellipse(10, 10, 7, 7) + ellipse(10, 10, 2, 2),
    artist: ellipse(10, 7, 3.4, 3.4) + "M3.8 17C4.5 11.5 15.5 11.5 16.2 17",
    genre: "M3 3H10.5L17 9.5L9.5 17L3 10.5Z" + ellipse(7, 7, 1.2, 1.2),
    folder: "M2.5 6V15.5H17.5V7H9.5L8 4.5H3.5Z",
    playlist: "M3 4.5H15M3 9H15M3 13.5H9M14.5 16V10L17.5 11",
    attention: "M10 2.8L17.8 16.5H2.2Z M10 7.5V11.5 M10 14V14.01",
    plus: "M10 4V16M4 10H16",
    search: ellipse(8.8, 8.8, 5.3, 5.3) + "M12.8 12.8L16.5 16.5",
    chevDown: "M5.5 8L10 12.5L14.5 8",
    starLine: starPoints(9),
}
const FILL = {
    song: ellipse(5.8, 14.8, 2.4, 2) + ellipse(12.8, 12.8, 2.4, 2),
    playlist: ellipse(13, 16, 1.8, 1.5),
    more: ellipse(10, 4.5, 1.6, 1.6) + ellipse(10, 10, 1.6, 1.6) + ellipse(10, 15.5, 1.6, 1.6),
    star: starPoints(9),
}
function stroke(name) { return STROKE[name] || "" }
function fill(name) { return FILL[name] || "" }
