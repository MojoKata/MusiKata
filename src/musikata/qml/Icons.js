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
    chevUp: "M5.5 12L10 7.5L14.5 12",
    chevLeft: "M12 5.5L7.5 10L12 14.5",
    shuffle: "M3 6H6C11 6 10 14 15 14H17M3 14H6C11 14 10 6 15 6H17M14.5 3.5L17 6L14.5 8.5"
        + "M14.5 11.5L17 14L14.5 16.5",
    grid: "M3.5 3.5H9V9H3.5Z M11 3.5H16.5V9H11Z M3.5 11H9V16.5H3.5Z M11 11H16.5V16.5H11Z",
    list: "M7 5H17M7 10H17M7 15H17M3.5 5V5.01M3.5 10V10.01M3.5 15V15.01",
    large: "M5.5 3.5H14.5Q16.5 3.5 16.5 5.5V14.5Q16.5 16.5 14.5 16.5H5.5Q3.5 16.5 3.5 14.5V5.5"
        + "Q3.5 3.5 5.5 3.5Z",
    small: "M3.5 3.5H6.5V6.5H3.5Z M8.5 3.5H11.5V6.5H8.5Z M13.5 3.5H16.5V6.5H13.5Z"
        + "M3.5 8.5H6.5V11.5H3.5Z M8.5 8.5H11.5V11.5H8.5Z M13.5 8.5H16.5V11.5H13.5Z"
        + "M3.5 13.5H6.5V16.5H3.5Z M8.5 13.5H11.5V16.5H8.5Z M13.5 13.5H16.5V16.5H13.5Z",
    cards: "M4.5 3.5H15.5Q16.5 3.5 16.5 4.5V8.5Q16.5 9.5 15.5 9.5H4.5Q3.5 9.5 3.5 8.5V4.5"
        + "Q3.5 3.5 4.5 3.5Z M4.5 11H15.5Q16.5 11 16.5 12V16Q16.5 17 15.5 17H4.5Q3.5 17 3.5 16V12"
        + "Q3.5 11 4.5 11Z",
    file: "M5 2.5H11.5L15.5 6.5V17.5H5Z M11.5 2.5V6.5H15.5",
    wand: "M3.5 16.5L12.5 7.5 M11 4V6 M15.5 8.5H17.5 M14.5 4.5L15.8 3.2 M14.2 11.5L15.5 12.8"
        + "M8 3.2L9.3 4.5",
    arrow: "M3.5 10H16 M11.5 5.5L16 10L11.5 14.5",
    close: "M5 5L15 15M15 5L5 15",
    minus: "M5 10H15",
    image: "M4.5 3.5H15.5Q17.5 3.5 17.5 5.5V14.5Q17.5 16.5 15.5 16.5H4.5Q2.5 16.5 2.5 14.5V5.5"
        + "Q2.5 3.5 4.5 3.5Z M3 14.5L8 9.5L11.5 13L13.5 11L17 14.5" + ellipse(13, 7.5, 1.4, 1.4),
    check: "M4 10.5L8 14.5L16 5.5",
    globe: ellipse(10, 10, 7, 7) + ellipse(10, 10, 3, 7) + "M3 10H17",
    wave: "M3 8V12M5.8 5.5V14.5M8.6 3.5V16.5M11.4 6.5V13.5M14.2 4.5V15.5M17 7.5V12.5",
    starLine: starPoints(9),
    refresh: "M13.25 4.37A6.5 6.5 0 1 0 15.63 13.25 M13.2 2.5L13.4 5.6L16.4 5.2",
    repeat: "M5 9V7.5Q5 5.5 7 5.5H16 M15 11V12.5Q15 14.5 13 14.5H4 M13.5 3L16 5.5L13.5 8"
        + "M6.5 12L4 14.5L6.5 17",
    queue: "M3 4.5H17M3 9H17M3 13.5H10",
    volume: "M3 7.5H6.5L10.5 4V16L6.5 12.5H3Z M13.5 7Q15.5 10 13.5 13 M15.8 4.8Q19.5 10 15.8 15.2",
    popout: "M9 4H4V16H16V11 M10 10L16.5 3.5 M11.5 3.5H16.5V8.5",
    expand: "M3.5 8V3.5H8 M16.5 8V3.5H12 M3.5 12V16.5H8 M16.5 12V16.5H12",
    undo: "M5 8H12.5C17.5 8 17.5 16 12.5 16H8 M8 4.8L4.8 8L8 11.2",
}
const FILL = {
    song: ellipse(5.8, 14.8, 2.4, 2) + ellipse(12.8, 12.8, 2.4, 2),
    playlist: ellipse(13, 16, 1.8, 1.5),
    more: ellipse(10, 4.5, 1.6, 1.6) + ellipse(10, 10, 1.6, 1.6) + ellipse(10, 15.5, 1.6, 1.6),
    star: starPoints(9),
    play: "M6 3.5L16.5 10L6 16.5Z",
    pause: "M5 3.5H8.6V16.5H5Z M11.4 3.5H15V16.5H11.4Z",
    next: "M4 4L13 10L4 16Z M13.5 5Q13.5 4 14.5 4H15.1Q16.1 4 16.1 5V15Q16.1 16 15.1 16H14.5"
        + "Q13.5 16 13.5 15Z",
    prev: "M16 4L7 10L16 16Z M6.5 5Q6.5 4 5.5 4H4.9Q3.9 4 3.9 5V15Q3.9 16 4.9 16H5.5Q6.5 16 6.5 15Z",
    queue: "M13 11.5L17.5 14.5L13 17.5Z",
    drag: ellipse(7.5, 5, 1.3, 1.3) + ellipse(7.5, 10, 1.3, 1.3) + ellipse(7.5, 15, 1.3, 1.3)
        + ellipse(12.5, 5, 1.3, 1.3) + ellipse(12.5, 10, 1.3, 1.3) + ellipse(12.5, 15, 1.3, 1.3),
}
function stroke(name) { return STROKE[name] || "" }
function fill(name) { return FILL[name] || "" }
