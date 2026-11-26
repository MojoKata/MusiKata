pragma Singleton
import QtQuick

// The design tokens of R6.2, dark (the design target and the default), with the in-between shades
// the mockups draw with (docs/mockups/src/render.py, C). Light and "Match system" (R6.6) come with
// the ⋮ menu.
QtObject {
    readonly property color bg: "#0e1014"
    readonly property color side: "#12151b"
    readonly property color surface: "#171a21"
    readonly property color raised: "#1e222b"
    readonly property color hover: "#252a35"
    readonly property color sel: "#2a2550"
    readonly property color border: "#232731"
    readonly property color borderStrong: "#323744"
    readonly property color text: "#eceef4"
    readonly property color cell: "#c9cdd8"         // a list's cells, a shade under text
    readonly property color muted: "#99a0b2"
    readonly property color faint: "#838a9d"
    readonly property color accent: "#a78bfa"
    readonly property color accentHi: "#c4b5fd"
    readonly property color accentSoft: "#2b2450"
    readonly property color primaryA: "#6d28d9"
    readonly property color primaryB: "#7c3aed"
    readonly property color cyan: "#22d3ee"
    readonly property color pink: "#f472b6"
    readonly property color ok: "#34d399"
    readonly property color warn: "#fbbf24"
    readonly property color err: "#fb7185"
    readonly property color errSoft: "#3d1a22"     // behind what is red: the banner and card of R2.10
    readonly property color warnSoft: "#3a2e12"    // behind what is amber: R2.10.1's question
    readonly property color star: "#fbbf24"
    readonly property color progress: "#4ade80"
    readonly property color input: "#0f1217"
    readonly property string sans: "Noto Sans"
}
