// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

import QtQuick
import QtQuick.Controls

// flat button in the plugins' style: grey box, blue when checked, optional colour chip and key hint
AbstractButton {
    id: b
    property color chip: "transparent"
    property string keyHint: ""
    property string tip: ""
    property bool danger: false
    implicitHeight: 28
    implicitWidth: Math.max(28, row.implicitWidth + 18)
    focusPolicy: Qt.NoFocus
    hoverEnabled: true
    opacity: enabled ? 1 : 0.4
    ToolTip.visible: hovered && tip !== ""
    ToolTip.delay: 500
    ToolTip.text: tip
    background: Rectangle {
        radius: 3
        color: b.checked ? (b.hovered ? Theme.accentHi : Theme.accent)
               : b.pressed ? Theme.buttonHover : b.hovered ? Theme.buttonHover : Theme.button
        border.width: b.chip.a > 0 && b.checked ? 1 : 0
        border.color: b.chip
    }
    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 6
            Rectangle {
                visible: b.chip.a > 0
                width: 10; height: 10; radius: 2
                color: b.chip
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: b.text
                color: b.danger ? Theme.danger : Theme.text
                font.pixelSize: 13
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: b.keyHint !== ""
                text: b.keyHint
                color: Theme.dim
                font.pixelSize: 11
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
