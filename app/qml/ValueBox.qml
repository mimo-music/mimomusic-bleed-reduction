// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

import QtQuick
import QtQuick.Controls

// a time value like the plugins' parameter boxes: value large, label small below.
// Drag up/down or turn the wheel to change it (10 ms steps; Shift 1 ms; Ctrl 100 ms),
// double-click to type ("1:23.45" or "83.45"), Enter to take it, Esc to cancel.
Rectangle {
    id: box
    property real value: 0
    property real from: 0
    property real to: 1e9
    property string label: ""
    property color accent: Theme.text
    property bool compact: false
    signal edited(real v)          // every change while dragging / turning
    signal committed(real v)       // end of a gesture or a typed value
    signal started()               // beginning of a drag (one undo step)

    implicitWidth: compact ? 84 : 110
    implicitHeight: compact ? 26 : 44
    radius: 3
    color: area.containsMouse || area.pressed ? Theme.boxHover : Theme.box
    border.width: input.visible ? 1 : 0
    border.color: Theme.accentHi

    function step(mods) { return (mods & Qt.ShiftModifier) ? 0.001 : (mods & Qt.ControlModifier) ? 0.1 : 0.01 }
    function clamp(v) { return Math.max(from, Math.min(to, v)) }

    Text {
        visible: !input.visible
        anchors.horizontalCenter: parent.horizontalCenter
        y: box.compact ? (parent.height - height) / 2 : 5
        text: Theme.fmt(box.value, 3)
        color: box.accent
        font.pixelSize: box.compact ? 12 : 14
        font.family: "monospace"
    }
    Text {
        visible: !box.compact
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 4
        text: box.label
        color: Theme.dim
        font.pixelSize: 10
    }
    TextInput {
        id: input
        visible: false
        anchors.fill: parent
        anchors.margins: 4
        horizontalAlignment: TextInput.AlignHCenter
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.text
        selectionColor: Theme.accent
        font.pixelSize: 13
        font.family: "monospace"
        onAccepted: {
            const v = Theme.parse(text)
            visible = false
            if (!isNaN(v)) { box.started(); box.committed(box.clamp(v)) }
        }
        Keys.onEscapePressed: visible = false
        onActiveFocusChanged: if (!activeFocus) visible = false
    }
    MouseArea {
        id: area
        anchors.fill: parent
        enabled: !input.visible
        hoverEnabled: true
        preventStealing: true
        cursorShape: Qt.SizeVerCursor
        property real y0: 0
        property real v0: 0
        property bool moved: false
        onPressed: (m) => { y0 = m.y; v0 = box.value; moved = false }
        onPositionChanged: (m) => {
            if (!pressed) return
            const dy = y0 - m.y
            if (!moved && Math.abs(dy) < 3) return
            if (!moved) box.started()
            moved = true
            box.edited(box.clamp(v0 + Math.round(dy / 2) * box.step(m.modifiers)))
        }
        onReleased: if (moved) box.committed(box.value)
        onDoubleClicked: {
            input.text = Theme.fmt(box.value, 3)
            input.visible = true
            input.forceActiveFocus()
            input.selectAll()
        }
        onWheel: (w) => {
            const n = w.angleDelta.y > 0 ? 1 : w.angleDelta.y < 0 ? -1 : 0
            if (n === 0) return
            box.started()
            box.committed(box.clamp(box.value + n * box.step(w.modifiers)))
        }
    }
}
