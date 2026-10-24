// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

import QtQuick
import QtQuick.Controls
import Bleed

// The waveform editor (DAW/Mixxx-like), used by Listen and Markers:
//   overview of the whole sample on top (click/drag: move the view)
//   ruler · passage lane · one lane per track (the one you hear is bright)
//   wheel: zoom at the mouse · Shift+wheel or sideways: scroll · middle drag: pan
//   drag in the lanes or the ruler: new loop · click: play from there
//   loop edges (yellow): drag to move them (the play position stays where it is)
//   passage lane (editable): click selects (and loops it), Ctrl+click adds/removes,
//   Shift+click extends, drag on empty space: select by band, drag an edge: retime it,
//   drag a passage: move it (laid over what is there: coro on lead becomes lead + coro),
//   double-click: loop and play it · right click anywhere: contextRequested (menu in MarkersView)
//   loop edges snap to passage edges (within 6 px; hold Alt to place them freely)
Item {
    id: tl
    function laneWave(i) { return laneRep.itemAt(i) }   // (self-test)
    property int revision: 0            // raised when the files were rewritten (WaveView.revision)
    property var lanes: []              // [{label, sub, path, passages?, kinds?}] (a lane's own tags, else the passage lane's)
    property string passLabel: "passages"
    property int activeLane: 0
    property bool editable: false
    property bool showPassages: true
    property var passages: markers.passages
    property var selection: []          // indices into passages
    property bool dbScale: false
    property bool normalize: true
    property bool spectral: false        // colour by frequency: low red, mid green, high blue (Mixxx)
    property real duration: player.duration
    property real viewStart: 0
    property real viewEnd: 1
    property bool follow: true
    readonly property real span: Math.max(1e-6, viewEnd - viewStart)
    readonly property int headerWidth: 128
    readonly property int rulerHeight: 22
    readonly property int passHeight: !showPassages ? 0 : editable ? 34 : 14
    signal laneActivated(int i)
    signal laneCtrlClicked(int i)
    signal contextRequested(real t, int passage, real x, real y)   // right click; x, y in the timeline
    property alias area: main          // for the self-test (driver coordinates)

    implicitHeight: 360

    function xOf(t) { return (t - viewStart) / span * main.width }
    function tAt(x) { return viewStart + x / main.width * span }
    function setView(a, b) {
        const d = Math.max(duration, 0.01)
        let s = Math.max(0.01, Math.min(d, b - a))
        a = Math.max(0, Math.min(d - s, a))
        viewStart = a
        viewEnd = a + s
    }
    function fit() { setView(0, duration) }
    function zoomAt(t, f) { setView(t - (t - viewStart) * f, t + (viewEnd - t) * f) }
    function zoom(f) { const p = player.position; zoomAt(p >= viewStart && p <= viewEnd ? p : (viewStart + viewEnd) / 2, f) }
    function zoomToLoop() { const l = player.loopEnd - player.loopStart; setView(player.loopStart - l * 0.08, player.loopEnd + l * 0.08) }
    function scrollBy(frac) { setView(viewStart + frac * span, viewEnd + frac * span) }
    function isSelected(i) { return selection.indexOf(i) >= 0 }

    onDurationChanged: fit()
    Component.onCompleted: fit()

    // keep the play position in view while playing (page by page, like a DAW)
    Connections {
        target: player
        function onPositionChanged() {
            if (!tl.follow || !player.playing || mouse.pressed) return
            const p = player.position
            if (p > tl.viewEnd || p < tl.viewStart) tl.setView(p - tl.span * 0.05, p + tl.span * 0.95)
        }
    }

    // ---------------------------------------------------------------- overview
    Rectangle {
        id: overview
        x: tl.headerWidth
        width: parent.width - tl.headerWidth
        height: 40
        color: Theme.panel
        WaveView {
            anchors.fill: parent
            anchors.topMargin: 2
            anchors.bottomMargin: 2
            source: tl.activeLane >= 0 && tl.lanes.length > tl.activeLane ? tl.lanes[tl.activeLane].path : (tl.lanes.length ? tl.lanes[0].path : "")
            revision: tl.revision
            viewStart: 0
            viewEnd: Math.max(0.01, tl.duration)
            color: Theme.waveDim
            backColor: Theme.panel
            lineColor: Theme.panel
            passages: tl.showPassages ? tl.passages : []
            kinds: markers.kinds
            tint: 0.30
            normalize: tl.normalize
            dbScale: tl.dbScale
        }
        Rectangle {   // the loop
            x: player.loopStart / Math.max(0.01, tl.duration) * overview.width
            width: Math.max(1, (player.loopEnd - player.loopStart) / Math.max(0.01, tl.duration) * overview.width)
            height: parent.height
            color: Theme.loop
            opacity: player.loopOn ? 0.18 : 0.07
        }
        Rectangle {   // the view
            x: tl.viewStart / Math.max(0.01, tl.duration) * overview.width
            width: Math.max(4, tl.span / Math.max(0.01, tl.duration) * overview.width)
            height: parent.height
            color: "#14ffffff"
            border.color: Theme.text
            border.width: 1
            radius: 2
        }
        Rectangle {
            x: player.position / Math.max(0.01, tl.duration) * overview.width
            width: 1
            height: parent.height
            color: Theme.playhead
        }
        MouseArea {
            anchors.fill: parent
            preventStealing: true
            cursorShape: Qt.PointingHandCursor
            function centre(x) { const t = x / width * tl.duration; tl.setView(t - tl.span / 2, t + tl.span / 2) }
            onPressed: (m) => centre(m.x)
            onPositionChanged: (m) => centre(m.x)
            onWheel: (w) => { const t = w.x / width * tl.duration; tl.zoomAt(t, w.angleDelta.y > 0 ? 0.8 : 1.25) }
        }
    }
    Text {
        anchors.right: overview.left
        anchors.rightMargin: 8
        anchors.verticalCenter: overview.verticalCenter
        text: "overview"
        color: Theme.dim
        font.pixelSize: 11
    }

    // ---------------------------------------------------------------- headers
    Column {
        id: headers
        x: 0
        y: main.y
        width: tl.headerWidth
        Rectangle {
            width: parent.width; height: tl.rulerHeight; color: Theme.panel
            Text { x: 8; anchors.verticalCenter: parent.verticalCenter; text: Theme.fmt(tl.viewStart, 1) + " – " + Theme.fmt(tl.viewEnd, 1); color: Theme.dim; font.pixelSize: 10 }
        }
        Rectangle {
            visible: tl.passHeight > 0
            width: parent.width; height: tl.passHeight; color: Theme.panel
            Text { x: 8; width: parent.width - 12; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: tl.passLabel; color: Theme.dim; font.pixelSize: tl.editable ? 12 : 10 }
        }
        Repeater {
            model: tl.lanes
            Rectangle {
                required property var modelData
                required property int index
                width: tl.headerWidth
                height: lanesBox.laneH
                color: index === tl.activeLane ? Theme.box : Theme.panel
                border.color: Theme.bg
                Rectangle { visible: index === tl.activeLane; width: 3; height: parent.height; color: Theme.wave }
                Column {
                    x: 10; anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text { text: modelData.label; color: index === tl.activeLane ? Theme.text : Theme.dim; font.pixelSize: 13; font.bold: index === tl.activeLane }
                    Text { text: modelData.sub || ""; color: Theme.dim; font.pixelSize: 10; visible: text !== "" && lanesBox.laneH >= 50 }
                    Text { text: index === tl.activeLane ? "♪ heard" : "click: hear"; color: index === tl.activeLane ? Theme.wave : Theme.dim; font.pixelSize: 10
                           visible: tl.lanes.length > 1 && (lanesBox.laneH >= 64 || index === tl.activeLane && lanesBox.laneH >= 36) }
                }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: (m) => { if (m.modifiers & Qt.ControlModifier) tl.laneCtrlClicked(index); else tl.laneActivated(index) } }
            }
        }
    }

    // ---------------------------------------------------------------- main area
    Item {
        id: main
        x: tl.headerWidth
        y: overview.height + 4
        width: parent.width - tl.headerWidth
        height: parent.height - y - hbar.height
        clip: true

        TimeRuler {
            id: ruler
            width: parent.width
            height: tl.rulerHeight
            viewStart: tl.viewStart
            viewEnd: tl.viewEnd
            color: Theme.dim
            backColor: Theme.panel
        }

        // passage lane
        Rectangle {
            id: passLane
            y: tl.rulerHeight
            width: parent.width
            height: tl.passHeight
            visible: height > 0
            color: Theme.bg
            Repeater {
                model: tl.passages
                Rectangle {
                    required property var modelData
                    required property int index
                    readonly property bool sel: tl.isSelected(index)
                    x: tl.xOf(modelData.start)
                    width: Math.max(1, tl.xOf(modelData.end) - x)
                    visible: x < passLane.width && x + width > 0
                    y: 3
                    height: passLane.height - 6
                    radius: 2
                    color: Theme.tagColor(markers.kinds.indexOf(modelData.kind))
                    opacity: sel ? 1.0 : modelData.auto ? 0.42 : 0.78
                    border.width: sel ? 2 : 0
                    border.color: "white"
                    Text {
                        visible: parent.width > 30 && tl.editable
                        x: Math.max(4, -parent.x + 4)
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 8
                        elide: Text.ElideRight
                        text: modelData.kind + (modelData.auto ? " ?" : "")
                        color: "#141519"
                        font.pixelSize: 12
                        font.bold: parent.sel
                    }
                }
            }
            Rectangle {   // a passage being moved
                id: ghost
                visible: false
                property string kind: ""
                y: 1
                height: parent.height - 2
                radius: 2
                color: Theme.tagColor(markers.kinds.indexOf(kind))
                opacity: 0.85
                border.width: 2
                border.color: "white"
            }
            Rectangle {   // band selection
                id: band
                visible: false
                y: 0
                height: parent.height
                color: "#33ffffff"
                border.color: "white"
            }
        }

        // track lanes
        Column {
            id: lanesBox
            y: tl.rulerHeight + tl.passHeight
            width: parent.width
            readonly property real laneH: tl.lanes.length ? Math.max(40, (main.height - y) / tl.lanes.length) : 0
            Repeater {
                id: laneRep
                model: tl.lanes
                WaveView {
                    required property var modelData
                    required property int index
                    width: lanesBox.width
                    height: lanesBox.laneH
                    source: modelData.path
                    revision: tl.revision
                    viewStart: tl.viewStart
                    viewEnd: tl.viewEnd
                    color: index === tl.activeLane ? Theme.wave : Theme.waveDim
                    backColor: index % 2 ? "#141519" : "#16171b"
                    lineColor: Theme.line
                    passages: tl.showPassages ? (modelData.passages !== undefined ? modelData.passages : tl.passages) : []
                    kinds: modelData.kinds !== undefined ? modelData.kinds : markers.kinds
                    tint: modelData.passages !== undefined ? 0.16 : 0.10
                    normalize: tl.normalize
                    dbScale: tl.dbScale
                    spectral: tl.spectral
                }
            }
        }

        // loop range and its edges (over everything)
        Rectangle {
            id: loopRect
            x: tl.xOf(player.loopStart)
            width: Math.max(1, tl.xOf(player.loopEnd) - x)
            y: 0
            height: parent.height
            color: Theme.loop
            opacity: player.loopOn ? 0.10 : 0.035
            visible: player.loaded && !(player.loopStart <= 0.001 && player.loopEnd >= tl.duration - 0.001)
        }
        Repeater {
            model: 2
            Item {
                required property int index
                readonly property real t: index === 0 ? player.loopStart : player.loopEnd
                visible: loopRect.visible
                x: tl.xOf(t) - 1
                width: 2
                height: main.height
                Rectangle { width: 2; height: parent.height; color: Theme.loop; opacity: player.loopOn ? 0.95 : 0.45 }
                Rectangle {   // the flag in the ruler
                    x: index === 0 ? 0 : -width + 2
                    width: 28; height: 14; radius: 2
                    color: Theme.loop
                    opacity: player.loopOn ? 1 : 0.5
                    Text { anchors.centerIn: parent; text: index === 0 ? "IN" : "OUT"; font.pixelSize: 9; font.bold: true; color: "#141519" }
                }
            }
        }
        // play position
        Rectangle {
            x: tl.xOf(player.position)
            width: 1.5
            height: parent.height
            color: Theme.playhead
            visible: x >= 0 && x <= main.width
        }

        // ------------------------------------------------------------ mouse
        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            preventStealing: true
            acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
            property string mode: ""
            property real x0: 0
            property real t0: 0
            property bool moved: false
            property int pIndex: -1
            property int pWhich: 0
            property var sel0: []
            property real v0: 0

            function region(y) { return y < tl.rulerHeight ? "ruler" : y < tl.rulerHeight + tl.passHeight ? "pass" : "wave" }
            function near(x, t) { return Math.abs(x - tl.xOf(t)) <= 5 }
            function loopEdgeAt(x) {
                if (!loopRect.visible) return -1
                if (near(x, player.loopStart)) return 0
                if (near(x, player.loopEnd)) return 1
                return -1
            }
            // [index, which] of a passage edge under x, or [-1, 0]
            function passEdgeAt(x) {
                for (let i = 0; i < tl.passages.length; ++i) {
                    if (near(x, tl.passages[i].start)) return [i, 0]
                    if (near(x, tl.passages[i].end)) return [i, 1]
                }
                return [-1, 0]
            }
            function passAt(x) { return markers.at(tl.tAt(x)) }
            // loop edges snap to passage edges within 6 px (hold Alt for none)
            function snap(t, x, mods) {
                if (!tl.showPassages || (mods & Qt.AltModifier)) return t
                let best = t, d = 6
                for (const p of tl.passages)
                    for (const e of [p.start, p.end]) {
                        const dx = Math.abs(tl.xOf(e) - x)
                        if (dx < d) { d = dx; best = e }
                    }
                return best
            }

            cursorShape: {
                if (pressed) return mode === "pan" || mode === "pmove" ? Qt.ClosedHandCursor : mode === "loop0" || mode === "loop1" || mode === "edge" ? Qt.SizeHorCursor : Qt.ArrowCursor
                return Qt.ArrowCursor
            }
            onPositionChanged: (m) => {
                if (!pressed) {   // hover: show what a press would grab
                    const r = region(m.y)
                    const e = r === "pass" && tl.editable ? passEdgeAt(m.x)[0] >= 0 : loopEdgeAt(m.x) >= 0
                    cursorShape = e ? Qt.SizeHorCursor : r === "pass" && tl.editable ? (passAt(m.x) >= 0 ? Qt.OpenHandCursor : Qt.PointingHandCursor) : Qt.IBeamCursor
                    return
                }
                const t = Math.max(0, Math.min(tl.duration, tl.tAt(m.x)))
                if (!moved && Math.abs(m.x - x0) < 4) return
                moved = true
                if (mode === "pan") {
                    tl.setView(v0 - (m.x - x0) / main.width * tl.span, v0 - (m.x - x0) / main.width * tl.span + tl.span)
                } else if (mode === "loop0") {
                    player.setLoop(Math.min(snap(t, m.x, m.modifiers), player.loopEnd - 0.01), player.loopEnd, false)
                } else if (mode === "loop1") {
                    player.setLoop(player.loopStart, Math.max(snap(t, m.x, m.modifiers), player.loopStart + 0.01), false)
                } else if (mode === "edge") {
                    markers.dragEdge(pIndex, pWhich, t)
                } else if (mode === "newloop") {
                    const a = snap(t0, x0, m.modifiers), b = snap(t, m.x, m.modifiers)
                    player.setLoop(Math.min(a, b), Math.max(a, b), false)
                } else if (mode === "pclick" && !(m.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)) || mode === "pmove") {
                    // move the passage; its edges snap to other passages' and the loop's edges
                    mode = "pmove"
                    const p = tl.passages[pIndex]
                    let s = p.start + (t - t0)
                    const len = p.end - p.start
                    if (!(m.modifiers & Qt.AltModifier)) {
                        let best = 6, sh = 0
                        let edges = [player.loopStart, player.loopEnd]
                        for (let k = 0; k < tl.passages.length; ++k) if (k !== pIndex) edges.push(tl.passages[k].start, tl.passages[k].end)
                        for (const e of edges)
                            for (const q of [s, s + len]) {
                                const dx = Math.abs(tl.xOf(e) - tl.xOf(q))
                                if (dx < best) { best = dx; sh = e - q }
                            }
                        s += sh
                    }
                    s = Math.max(0, Math.min(tl.duration - len, s))
                    ghost.kind = p.kind
                    ghost.x = tl.xOf(s)
                    ghost.width = tl.xOf(s + len) - ghost.x
                    ghost.visible = true
                    v0 = s
                } else if (mode === "band" || mode === "pclick") {
                    mode = "band"
                    const a = Math.min(t0, t), b = Math.max(t0, t)
                    band.visible = true
                    band.x = tl.xOf(a)
                    band.width = tl.xOf(b) - band.x
                    let s = (m.modifiers & Qt.ControlModifier) ? sel0.slice() : []
                    for (const i of markers.within(a, b)) if (s.indexOf(i) < 0) s.push(i)
                    tl.selection = s
                }
            }
            onPressed: (m) => {
                x0 = m.x
                t0 = Math.max(0, Math.min(tl.duration, tl.tAt(m.x)))
                moved = false
                sel0 = tl.selection.slice()
                if (m.button === Qt.MiddleButton) { mode = "pan"; v0 = tl.viewStart; return }
                if (m.button === Qt.RightButton) {
                    mode = ""
                    tl.contextRequested(t0, markers.at(t0), m.x + main.x, m.y + main.y)
                    return
                }
                const r = region(m.y)
                if (r === "pass" && tl.editable) {
                    const e = passEdgeAt(m.x)
                    if (e[0] >= 0) { mode = "edge"; pIndex = e[0]; pWhich = e[1]; markers.begin(); return }
                    const i = passAt(m.x)
                    if (i < 0) { mode = "band"; if (!(m.modifiers & Qt.ControlModifier)) tl.selection = []; return }
                    mode = "pclick"; pIndex = i
                    if (m.modifiers & Qt.ControlModifier) {
                        let s = tl.selection.slice()
                        const k = s.indexOf(i)
                        if (k >= 0) s.splice(k, 1); else s.push(i)
                        tl.selection = s
                    } else if (m.modifiers & Qt.ShiftModifier && tl.selection.length) {
                        const a = Math.min(i, ...tl.selection), b = Math.max(i, ...tl.selection)
                        let s = []
                        for (let k = a; k <= b; ++k) s.push(k)
                        tl.selection = s
                    } else {
                        tl.selection = [i]
                    }
                    return
                }
                const le = loopEdgeAt(m.x)
                if (le >= 0) { mode = le === 0 ? "loop0" : "loop1"; return }
                mode = "newloop"
            }
            onReleased: (m) => {
                band.visible = false
                ghost.visible = false
                if (mode === "pmove") {
                    const len = tl.passages[pIndex].end - tl.passages[pIndex].start   // read before the move
                    markers.move(pIndex, v0, v0 + len)
                    const i = markers.at(v0 + Math.min(0.01, len / 2))
                    tl.selection = i >= 0 ? [i] : []
                } else if (mode === "newloop") {
                    if (moved) {
                        player.loopOn = true
                        player.setLoop(player.loopStart, player.loopEnd, true)
                        player.seek(player.loopStart)
                    } else {
                        player.seek(t0)
                    }
                } else if (mode === "pclick" && !moved && !(m.modifiers & (Qt.ControlModifier | Qt.ShiftModifier))) {
                    const p = tl.passages[pIndex]
                    if (p) { player.setLoop(p.start, p.end); player.seek(p.start) }
                }
                mode = ""
            }
            onDoubleClicked: (m) => {
                if (m.button !== Qt.LeftButton || region(m.y) !== "pass") return
                const i = passAt(m.x)
                if (i < 0) return
                const p = tl.passages[i]
                tl.selection = [i]
                player.loopOn = true
                player.setLoop(p.start, p.end)
                player.seek(p.start)
                if (!player.playing) player.play()
            }
            onWheel: (w) => {
                const dx = w.angleDelta.x, dy = w.angleDelta.y
                if (dx !== 0 || (w.modifiers & Qt.ShiftModifier)) {
                    const d = dx !== 0 ? -dx : -dy
                    tl.scrollBy(d / 120 * 0.15)
                } else if (dy !== 0) {
                    tl.zoomAt(tl.tAt(w.x), Math.pow(0.8, dy / 120))
                }
            }
        }
    }

    // ---------------------------------------------------------------- scroll bar
    ScrollBar {
        id: hbar
        x: tl.headerWidth
        anchors.bottom: parent.bottom
        width: parent.width - tl.headerWidth
        orientation: Qt.Horizontal
        policy: ScrollBar.AlwaysOn
        size: tl.duration > 0 ? Math.min(1, tl.span / tl.duration) : 1
        position: tl.duration > 0 ? tl.viewStart / tl.duration : 0
        onPositionChanged: if (pressed) tl.setView(position * tl.duration, position * tl.duration + tl.span)
    }
}
