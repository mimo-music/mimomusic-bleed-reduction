// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

pragma Singleton
import QtQuick

// colours and sizes, after the MimoMusic plugins (dark panels, value boxes, teal/yellow accents)
QtObject {
    readonly property color bg: "#18191d"
    readonly property color panel: "#202227"
    readonly property color box: "#2c2f36"
    readonly property color boxHover: "#353943"
    readonly property color button: "#3a3e46"
    readonly property color buttonHover: "#4e5460"
    readonly property color line: "#2c2f36"
    readonly property color text: "#e6e8ec"
    readonly property color dim: "#8c9098"
    readonly property color accent: "#4682a0"        // active button (A/B in the plugins)
    readonly property color accentHi: "#5a96b4"
    readonly property color wave: "#78bec8"          // the lane you hear
    readonly property color waveDim: "#6e7684"       // other lanes
    readonly property color loop: "#ebc33c"          // loop range and its edges
    readonly property color playhead: "#ffffff"
    readonly property color danger: "#d25a46"
    // tag colours by their place in the track's tag list (same as WaveView::tagColor)
    readonly property var tagPalette: ["#5a9be1", "#55af6e", "#e67d46", "#b482dc", "#d2649b", "#46b4b4", "#b48c64", "#a0c850"]
    function tagColor(i) { return i < 0 ? dim : tagPalette[i % tagPalette.length] }
    function fmt(t, d) {
        if (d === undefined) d = 2
        const m = Math.floor(t / 60), s = t - 60 * m
        return m + ":" + (s < 10 ? "0" : "") + s.toFixed(d)
    }
    // "1:23.45", "83.45", "1:23" -> seconds (NaN when unreadable)
    function parse(s) {
        s = ("" + s).trim()
        const p = s.split(":")
        if (p.length === 1) return parseFloat(p[0])
        if (p.length === 2) return parseInt(p[0]) * 60 + parseFloat(p[1])
        return NaN
    }
}
