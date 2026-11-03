// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Mettronic GmbH

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import Bleed

// Bleed Reduction. A project: import (a folder of stems, or an Ardour session) -> Analyse (roles
// suggested) -> check roles and chains -> range -> Render -> listen (rendered against the
// original) -> the files in <project>/render/, one per track, aligned with the originals.
ApplicationWindow {
    id: win
    width: 1500
    height: 950
    visible: true
    title: "Bleed Reduction" + (studio.path ? " – " + studio.name : "")
    color: Theme.bg
    palette.window: Theme.bg
    palette.windowText: Theme.text
    palette.base: "#121317"
    palette.text: Theme.text
    palette.button: Theme.button
    palette.buttonText: Theme.text
    palette.highlight: Theme.accent
    palette.highlightedText: "white"
    palette.placeholderText: Theme.dim
    palette.toolTipBase: Theme.box
    palette.toolTipText: Theme.text

    property string message: ""
    property string selected: ""          // the track in the listen panel
    property bool showChains: false
    readonly property var roleLabel: ({ lead: "Lead vocal", backing: "Backing vocal", instrument: "Instrument", keep: "Don't clean" })
    readonly property var roleTip: ({ lead: "a lead singer's mic: the voice only (several lead mics are fine)",
                                      backing: "a coro / backing singer's mic: the voice only, the lead singers' leak turned down",
                                      instrument: "the singers' voices removed (where the vocal mics explain them, so a sax solo stays) "
                                                  + "and the other instruments removed: the mic's own instrument kept",
                                      keep: "left as it is (a line input, a silent or unused mic, a track that is fine)" })
    property int filesRev: 0              // a render or re-import finished (the waveforms read again)
    property var picked: ({})             // name -> true: the tracks ticked in the list (for the bulk buttons)
    property int lastPick: -1             // for Shift+click ranges
    readonly property var pickedNames: Object.keys(picked).filter(n => picked[n])
    function pick(i, on, range) {
        const p = Object.assign({}, picked)
        const ts = studio.tracks
        const a = range && lastPick >= 0 ? Math.min(lastPick, i) : i
        const b = range && lastPick >= 0 ? Math.max(lastPick, i) : i
        for (let k = a; k <= b; ++k) p[ts[k].name] = on
        picked = p
        lastPick = i
    }
    // a change rebuilds the track list: keep where it was scrolled to
    function keepScroll(fn) {
        const y = trackList.contentY
        fn()
        Qt.callLater(() => trackList.contentY = Math.max(0, Math.min(y, trackList.contentHeight - trackList.height)))
    }
    onHasProjectChanged: { picked = ({}); lastPick = -1 }
    readonly property bool hasProject: studio.path !== ""
    readonly property var track: { const t = studio.tracks.find(x => x.name === selected); return t ? t : null }
    readonly property real rStart: studio.rendered.start !== undefined ? studio.rendered.start : studio.rangeStart
    readonly property real rEnd: studio.rendered.end !== undefined ? studio.rendered.end : studio.rangeEnd

    function fmtTime(s) { return Theme.fmt(s, 0) }
    function listen(name) {
        selected = name
        const t = studio.tracks.find(x => x.name === name)
        if (!t) return
        const orig = studio.originalFile(name), out = studio.renderedFile(name)
        if (out !== "") player.load(["range:" + orig + "|" + rStart + "|" + (rEnd > 0 ? rEnd : 0), out], true)
        else player.load([orig], true)
        player.selected = out !== "" ? 1 : 0
    }
    readonly property var lanes: {
        if (!track) return []
        const s = player.sources
        let l = []
        if (s.length > 1) l.push({ label: "rendered", sub: track.resolved, path: s[1] })
        if (s.length > 0) l.push({ label: "original", sub: s.length > 1 ? fmtTime(rStart) + "–" + fmtTime(rEnd > 0 ? rEnd : player.duration + rStart) : "", path: s[0] })
        return l
    }

    Connections { target: studio; function onMessage(t) { win.message = t } }
    Connections {
        target: studio
        // a render or re-import rewrote the files: the open track again (original or rendered as before)
        function onFilesChanged() {
            win.filesRev++
            if (win.selected === "") return
            const sel = player.selected
            win.listen(win.selected)
            if (sel < player.count) player.selected = sel
        }
    }

    Shortcut { sequence: "Space"; onActivated: player.toggle() }
    Shortcut { sequence: "0"; onActivated: player.selected = 0 }
    Shortcut { sequence: "1"; onActivated: if (player.count > 1) player.selected = 1 }
    Shortcut { sequence: "Esc"; onActivated: player.wholeSample() }

    // ------------------------------------------------------------ new project
    FolderDialog { id: projDlg; title: "Project folder (new, empty)"; onAccepted: projPath.text = studio.urlToPath(selectedFolder) }
    FolderDialog { id: srcDlg; title: srcArdour.checked ? "Ardour session folder" : "Folder with the WAV stems"; onAccepted: srcPath.text = studio.urlToPath(selectedFolder) }
    FolderDialog { id: reSrcDlg; title: "Ardour session folder (or the folder with the WAV stems)"
                   onAccepted: { if (studio.reimport(studio.urlToPath(selectedFolder))) { reDlg.close(); win.message = "re-importing …" } } }
    Popup {
        id: reDlg
        anchors.centerIn: Overlay.overlay
        width: 620
        modal: true
        padding: 20
        background: Rectangle { color: Theme.panel; border.color: Theme.accent; radius: 4 }
        ColumnLayout {
            width: parent.width
            spacing: 10
            Text { text: "Re-import the recording"; color: Theme.text; font.bold: true; font.pixelSize: 16 }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: Theme.dim
                text: (studio.source ? "From: " + studio.source + "\n\n" : "This project doesn't know its source yet: choose the Ardour session folder.\n\n")
                      + "Close the session in Ardour first. Every track is exported again as it is now (takes, edits). "
                      + "Each track keeps its role by its name, also when its number changed; new tracks are marked \"new\". "
                      + "The rendered files stay; the next Render does only the tracks whose audio changed (and where it changed)."
            }
            Row {
                spacing: 8
                Layout.alignment: Qt.AlignRight
                Btn { text: "Cancel"; onClicked: reDlg.close() }
                Btn { text: "From another folder…"; onClicked: { if (studio.source) reSrcDlg.currentFolder = studio.folderUrl(studio.source); reSrcDlg.open() } }
                Btn { text: "Re-import"; checked: true; enabled: studio.source !== ""
                      onClicked: { if (studio.reimport("")) { reDlg.close(); win.message = "re-importing …" } } }
            }
        }
    }
    function ardourName(n) { return n.replace(/^\d+\s+/, "").replace(/-[LR]$/, "") }
    Popup {
        id: ardourDlg
        anchors.centerIn: Overlay.overlay
        width: 720
        modal: true
        padding: 20
        background: Rectangle { color: Theme.panel; border.color: Theme.accent; radius: 4 }
        ColumnLayout {
            width: parent.width
            spacing: 10
            Text { text: "Into Ardour"; color: Theme.text; font.bold: true; font.pixelSize: 16 }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: Theme.dim
                text: "Into " + studio.source + "\n\n"
                      + "Save and close the session in Ardour first. For every track ticked \"into Ardour\": its render goes onto "
                      + "the track \"<name> Cleaned\" (its regions replaced; its plugins, fader and mute stay as you set them). "
                      + "Where there is none, it is made right below the original, as Ardour's Duplicate makes it (plugins, sends, "
                      + "fader, group, outputs), and the original is muted. The files are copied into the session, at the "
                      + "recording's start (also \"Move to Original Position\"); the recordings are not touched. "
                      + "The session file before is kept next to it (.ardour.bleed-backup). Re-import leaves the Cleaned tracks out."
            }
            Text { text: "What changes:"; color: Theme.text }
            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: 220
                TextArea { readOnly: true; text: studio.busy === "ardour" ? "…" : studio.log; font.family: "monospace"; font.pixelSize: 11; onTextChanged: cursorPosition = length
                           color: Theme.dim; background: Rectangle { color: "#121317" } }
            }
            Row {
                spacing: 8
                Layout.alignment: Qt.AlignRight
                Btn { text: "Cancel"; onClicked: ardourDlg.close() }
                Btn { text: "Into Ardour"; checked: true; enabled: studio.busy === ""
                      onClicked: { if (studio.toArdour(false)) ardourDlg.close() } }
            }
        }
    }
    FolderDialog { id: openDlg; title: "Open a project"; onAccepted: studio.open(studio.urlToPath(selectedFolder)) }
    Popup {
        id: newDlg
        anchors.centerIn: Overlay.overlay
        width: 680
        modal: true
        padding: 20
        background: Rectangle { color: Theme.panel; border.color: Theme.accent; radius: 4 }
        ColumnLayout {
            width: parent.width
            spacing: 10
            Text { text: "New project"; color: Theme.text; font.bold: true; font.pixelSize: 16 }
            GridLayout {
                columns: 3
                columnSpacing: 8
                rowSpacing: 8
                Layout.fillWidth: true
                Text { text: "Name"; color: Theme.dim }
                TextField { id: projName; Layout.fillWidth: true; Layout.columnSpan: 2; placeholderText: "e.g. Live at the Club 2026-05-12" }
                Text { text: "Project folder"; color: Theme.dim }
                TextField { id: projPath; Layout.fillWidth: true; placeholderText: "a new, empty folder: the project and its renders go there" }
                Btn { text: "Browse…"; onClicked: { if (projPath.text) projDlg.currentFolder = studio.folderUrl(projPath.text); projDlg.open() } }
                Text { text: "Recording"; color: Theme.dim }
                Row {
                    Layout.columnSpan: 2
                    spacing: 6
                    Btn { id: srcStems; text: "Folder of WAV stems"; checked: true; onClicked: { checked = true; srcArdour.checked = false } }
                    Btn { id: srcArdour; text: "Ardour session"; onClicked: { checked = true; srcStems.checked = false }
                          tip: "every track exported as it is recorded and edited, without plugins, sends or fader (close the session in Ardour first)" }
                }
                Text { text: srcArdour.checked ? "Session folder" : "Stems folder"; color: Theme.dim }
                TextField { id: srcPath; Layout.fillWidth: true; placeholderText: srcArdour.checked ? "the folder with the .ardour file" : "one WAV per mic; the file names are the track names" }
                Btn { text: "Browse…"; onClicked: { if (srcPath.text) srcDlg.currentFolder = studio.folderUrl(srcPath.text); srcDlg.open() } }
            }
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: Theme.dim
                font.pixelSize: 12
                text: srcArdour.checked ? "The tracks are exported into the project (as stored in Ardour: the takes as edited, unprocessed). The session is not changed."
                                        : "The stems are linked, not copied: keep them where they are."
            }
            Row {
                spacing: 8
                Layout.alignment: Qt.AlignRight
                Btn { text: "Cancel"; onClicked: newDlg.close() }
                Btn {
                    text: "Create"
                    checked: true
                    enabled: projName.text.trim() !== "" && projPath.text !== "" && srcPath.text !== ""
                    onClicked: { if (studio.create(projPath.text, projName.text, srcPath.text, srcArdour.checked)) newDlg.close() }
                }
            }
        }
    }

    header: Rectangle {
        height: 52
        color: Theme.panel
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 10
            Text { text: "Bleed Reduction"; color: Theme.text; font.bold: true; font.pixelSize: 18 }
            Text { text: win.hasProject ? "·  " + studio.name : ""; color: Theme.wave; font.pixelSize: 16 }
            Text { text: win.hasProject ? studio.path : ""; color: Theme.dim; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.maximumWidth: 420 }
            Item { Layout.fillWidth: true }
            Text { text: win.message; color: Theme.text; font.pixelSize: 12; elide: Text.ElideRight; Layout.maximumWidth: 460 }
            Btn { visible: win.hasProject; text: studio.busy === "reimport" ? "Re-importing …" : "Re-import…"
                  checked: studio.busy === "reimport"; enabled: studio.busy === ""; onClicked: reDlg.open()
                  tip: "the recording again from the Ardour session (or stems folder), e.g. after changing takes; the settings stay" }
            Btn { text: "New project…"; enabled: studio.busy === ""; onClicked: newDlg.open() }
            Btn { text: "Open…"; enabled: studio.busy === "" || studio.busy === "render"; onClicked: openDlg.open() }
        }
    }

    // ------------------------------------------------------------ no project
    ColumnLayout {
        visible: !win.hasProject
        anchors.centerIn: parent
        spacing: 14
        width: 640
        Text { text: "Bleed Reduction"; color: Theme.text; font.pixelSize: 26; font.bold: true }
        Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.dim
               text: "Takes the other instruments and singers out of every mic of a multitrack recording. "
                     + "Import a folder of stems or an Ardour session, tell it what each mic is (or let it suggest), render: one cleaned file per track, aligned with the originals." }
        Row {
            spacing: 10
            Btn { text: "New project…"; implicitHeight: 40; onClicked: newDlg.open() }
            Btn { text: "Open a project…"; implicitHeight: 40; onClicked: openDlg.open() }
        }
        Text { visible: studio.recent.length > 0; text: "Recent"; color: Theme.dim; topPadding: 10 }
        Repeater {
            model: studio.recent
            Btn { required property string modelData; text: modelData; onClicked: studio.open(modelData); implicitWidth: 640 }
        }
        Text { visible: studio.busy !== ""; text: studio.busy + " …"; color: Theme.loop }
        ScrollView {
            visible: studio.busy === "import" || studio.log !== ""      // stays after a failed import
            Layout.fillWidth: true
            Layout.preferredHeight: 200
            TextArea { readOnly: true; text: studio.log; font.family: "monospace"; font.pixelSize: 11; color: Theme.dim; background: Rectangle { color: Theme.panel } }
        }
    }

    // ------------------------------------------------------------ project
    ColumnLayout {
        id: projectPage
        visible: win.hasProject
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        SplitView {
            orientation: Qt.Vertical
            Layout.fillWidth: true
            Layout.fillHeight: true

            // tracks, then the render box below them: set the roles, render
            Rectangle {
                SplitView.preferredHeight: 480
                SplitView.minimumHeight: 240
                color: Theme.panel
                radius: 3
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 4
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: "Tracks"; color: Theme.text; font.bold: true; font.pixelSize: 15 }
                        Text { color: Theme.dim; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight
                               text: "the role of each mic decides how it is cleaned" }
                        Btn {
                            text: studio.busy === "analyse" ? "Suggesting …" : "Suggest roles…"
                            checked: studio.busy === "analyse"
                            enabled: studio.busy === ""
                            onClicked: win.keepScroll(() => studio.analyse())
                            tip: "listens to the recording and suggests a role for the tracks you haven't set yourself; also finds the songs "
                                 + "(for rendering one song) and how much voice each mic carries. Optional; takes minutes, then ~3 min per track"
                        }
                        Btn { text: "Chains"; checked: win.showChains; onClicked: win.showChains = !win.showChains
                              tip: "show the processing chain of each track (for trying other chains; normally the role decides)" }
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 6
                        Text { height: 28; verticalAlignment: Text.AlignVCenter; color: Theme.dim; font.pixelSize: 12
                               text: win.pickedNames.length ? win.pickedNames.length + " ticked, set them to:" : "tick tracks (Shift+click: a range) to set several at once" }
                        Repeater {
                            model: win.pickedNames.length ? studio.roles : []
                            Btn { required property string modelData; text: win.roleLabel[modelData]; tip: win.roleTip[modelData]
                                  onClicked: win.keepScroll(() => studio.setRole(win.pickedNames, modelData)) }
                        }
                        Btn { visible: win.pickedNames.length > 0; text: "untick all"; onClicked: { win.picked = ({}); win.lastPick = -1 } }
                    }
                    RowLayout {
                        spacing: 8
                        CheckBox {
                            Layout.preferredWidth: 28
                            implicitHeight: 24
                            checked: studio.tracks.length > 0 && win.pickedNames.length === studio.tracks.length
                            onToggled: { const p = {}; if (checked) for (const t of studio.tracks) p[t.name] = true; win.picked = p; win.lastPick = -1 }
                            ToolTip.visible: hovered
                            ToolTip.text: "tick / untick all"
                        }
                        Text { text: "track"; color: Theme.dim; font.pixelSize: 11; Layout.preferredWidth: 170 }
                        Text { text: "role"; color: Theme.dim; font.pixelSize: 11; Layout.preferredWidth: 170 }
                        Text { visible: win.showChains; text: "chain"; color: Theme.dim; font.pixelSize: 11; Layout.preferredWidth: 210 }
                        Text { text: "what happens"; color: Theme.dim; font.pixelSize: 11; Layout.preferredWidth: 380 }
                        Text { text: "voice"; color: Theme.dim; font.pixelSize: 11; Layout.preferredWidth: 60 }
                        Text { text: "rendered"; color: Theme.dim; font.pixelSize: 11; Layout.preferredWidth: 60 }
                        Text { visible: studio.fromArdour; text: "into Ardour"; color: Theme.dim; font.pixelSize: 11 }
                    }
                    ListView {
                        id: trackList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: studio.tracks
                        ScrollBar.vertical: ScrollBar {}
                        delegate: Rectangle {
                            id: row
                            required property var modelData
                            required property int index
                            width: ListView.view.width - 10
                            height: 34
                            color: modelData.name === win.selected ? "#2a4656" : index % 2 ? Theme.panel : "#1c1e22"
                            MouseArea { anchors.fill: parent; onClicked: win.listen(row.modelData.name) }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 4
                                spacing: 8
                                CheckBox {
                                    Layout.preferredWidth: 28
                                    implicitHeight: 28
                                    checked: !!win.picked[row.modelData.name]
                                    MouseArea {   // Shift+click: everything since the last tick
                                        anchors.fill: parent
                                        onClicked: (m) => win.pick(row.index, !win.picked[row.modelData.name], m.modifiers & Qt.ShiftModifier)
                                    }
                                }
                                Text { text: row.modelData.name; color: Theme.text; font.bold: row.modelData.name === win.selected; Layout.preferredWidth: 170; elide: Text.ElideRight }
                                ComboBox {
                                    Layout.preferredWidth: 170
                                    implicitHeight: 28
                                    model: studio.roles.map(r => win.roleLabel[r])
                                    currentIndex: studio.roles.indexOf(row.modelData.ui_role)
                                    onActivated: (i) => win.keepScroll(() => studio.setRole([row.modelData.name], studio.roles[i]))
                                    ToolTip.visible: hovered
                                    ToolTip.text: win.roleTip[row.modelData.ui_role] + (row.modelData.role_set ? "" : "  (suggested)")
                                }
                                ComboBox {
                                    visible: win.showChains
                                    Layout.preferredWidth: 210
                                    implicitHeight: 28
                                    model: studio.chains.map(c => c === "auto" ? "auto (" + row.modelData.resolved + ")" : c)
                                    currentIndex: Math.max(0, studio.chains.indexOf(row.modelData.chain || "auto"))
                                    onActivated: (i) => win.keepScroll(() => studio.setTrack(row.modelData.name, "chain", studio.chains[i]))
                                }
                                Text {
                                    Layout.preferredWidth: 380
                                    elide: Text.ElideRight
                                    color: Theme.dim
                                    font.pixelSize: 11
                                    text: (({ original: "left as it is",
                                              neural: "the voice only",
                                              neural_xvoc: "the voice only, the lead singers' leak turned down",
                                              novocal: "the voice removed",
                                              novocal_guided: "the voice removed where the vocal mics explain it",
                                              novocal_cat: "voice and other instruments removed",
                                              novocal_guided_cat: "voice (where the vocal mics explain it) and other instruments removed",
                                              novocal_guided_cat_mask: "as guided cat, the network only as a gain on the mic: no whine (DI bass)" })[row.modelData.resolved] || "")
                                          + (row.modelData.new && !row.modelData.role_set ? "   · new: set its role"
                                             : row.modelData.role_set ? "" : "   · suggested")
                                }
                                Text { Layout.preferredWidth: 60; color: Theme.dim; font.pixelSize: 11
                                       text: row.modelData.share_db !== undefined && row.modelData.share_db !== null ? Math.round(row.modelData.share_db) + 0 + " dB" : "" }
                                Text { text: row.modelData.rendered ? "✓" : ""; color: Theme.wave; Layout.preferredWidth: 60 }
                                CheckBox {
                                    visible: studio.fromArdour
                                    implicitHeight: 28
                                    checked: row.modelData.to_ardour
                                    onToggled: win.keepScroll(() => studio.setTrack(row.modelData.name, "to_ardour", checked))
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Into Ardour puts this track's render into the session: on its \"" + win.ardourName(row.modelData.name)
                                                  + " Cleaned\" track (made, below it, the original muted, if there is none)"
                                }
                                Item { Layout.fillWidth: true }
                            }
                        }
                    }

                    // render: what, how, go
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: renderFlow.implicitHeight + 16
                        color: "transparent"
                        border.color: Theme.line
                        radius: 3
                        Flow {
                            id: renderFlow
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 8
                            Text { height: 40; verticalAlignment: Text.AlignVCenter; text: "Render"; color: Theme.text; font.bold: true; font.pixelSize: 15 }
                            Text { height: 40; verticalAlignment: Text.AlignVCenter; text: "what:"; color: Theme.dim }
                            Btn { implicitHeight: 40; text: "Whole recording"; checked: studio.rangeStart <= 0 && studio.rangeEnd <= 0; onClicked: studio.setRange(0, 0) }
                            ComboBox {
                                id: songBox
                                implicitHeight: 40
                                implicitWidth: 220
                                property var songs: studio.analysis.songs || []
                                enabled: songs.length > 0
                                model: [songs.length ? "a song …" : "a song (after Suggest roles)"].concat(songs.map((s, i) => "song " + (i + 1) + "  " + win.fmtTime(s[0]) + "–" + win.fmtTime(s[1])))
                                onActivated: (i) => { if (i > 0) studio.setRange(songs[i - 1][0], songs[i - 1][1]); currentIndex = 0 }
                                ToolTip.visible: hovered
                                ToolTip.text: "render one song only (to try it on a laptop: the networks need ~7x real time per track on the processor)"
                            }
                            ValueBox { label: "from s"; value: studio.rangeStart; to: 36000; implicitWidth: 110; onCommitted: (v) => studio.setRange(v, studio.rangeEnd) }
                            ValueBox { label: "to s (0: the end)"; value: studio.rangeEnd; to: 36000; implicitWidth: 130; onCommitted: (v) => studio.setRange(studio.rangeStart, v) }
                            Rectangle { width: 1; height: 40; color: Theme.line }
                            Text { height: 40; verticalAlignment: Text.AlignVCenter; text: "quality:"; color: Theme.dim }
                            Btn { implicitHeight: 40; text: "Final"; checked: studio.quality !== "draft"; enabled: studio.busy === ""; onClicked: studio.setQuality("final")
                                  tip: "the category network runs 4 times on shifted input: no buzz in quiet places" }
                            Btn { implicitHeight: 40; text: "Draft"; checked: studio.quality === "draft"; enabled: studio.busy === ""; onClicked: studio.setQuality("draft")
                                  tip: "once, about 4x faster; may leave a faint 43/86 Hz buzz where a mic is almost silent: for trying a song on a laptop" }
                            Rectangle { width: 1; height: 40; color: Theme.line }
                            Btn {
                                implicitHeight: 40
                                implicitWidth: 140
                                text: studio.busy === "render" ? "■ Stop render" : "▶ Render"
                                checked: true
                                danger: studio.busy === "render"
                                enabled: studio.busy === "" || studio.busy === "render"
                                onClicked: studio.busy === "render" ? studio.stopRender() : studio.render()
                                tip: "every track through the cleaning of its role, one file per track, aligned with the originals. "
                                     + "Only what changed is done again: tracks whose audio (e.g. after a re-import) or settings changed, "
                                     + "and in the pieces of 3 min where it changed; keeps running when this window closes"
                            }
                            Btn {
                                implicitHeight: 40
                                visible: win.pickedNames.length > 0 && studio.busy !== "render"
                                text: "▶ Render the " + win.pickedNames.length + " ticked"
                                enabled: studio.busy === ""
                                onClicked: studio.render(win.pickedNames)
                                tip: "only these tracks (if they changed). A vocal mic's clean voice is used for the coro mics and "
                                     + "the guided voice removal of the others: after changing one, Render all"
                            }
                            Btn { implicitHeight: 40; visible: studio.fromArdour; text: studio.busy === "ardour" ? "Into Ardour …" : "Into Ardour…"
                                  checked: studio.busy === "ardour"
                                  enabled: studio.busy === "" && studio.rendered.finished !== undefined
                                  onClicked: { studio.toArdour(true); ardourDlg.open() }
                                  tip: "the rendered tracks ticked \"into Ardour\" into the session, each on a \"… Cleaned\" track below its original" }
                            Column {
                                visible: studio.progress.fraction !== undefined
                                spacing: 2
                                ProgressBar { width: 220; from: 0; to: 1; value: studio.progress.fraction || 0 }
                                Text {
                                    color: Theme.dim; font.pixelSize: 11
                                    text: (studio.progress.step || "") + (studio.progress.segments ? "  ·  piece " + studio.progress.segment + "/" + studio.progress.segments : "")
                                          + (studio.busy === "render" && studio.progress.eta ? "  ·  ~" + Math.round(studio.progress.eta / 60) + " min left" : "")
                                }
                            }
                            Btn { implicitHeight: 40; text: "Open the render folder"; enabled: studio.rendered.finished !== undefined
                                  onClicked: Qt.openUrlExternally("file://" + studio.renderDir()) }
                        }
                    }
                }
            }

            // listen
            ColumnLayout {
                SplitView.fillHeight: true
                SplitView.minimumHeight: 200
                spacing: 6
                RowLayout {
                    spacing: 6
                    Btn { text: player.playing ? "■ Stop" : "▶ Play"; keyHint: "Space"; checked: player.playing; onClicked: player.toggle(); enabled: player.loaded }
                    Btn { text: "original"; keyHint: "0"; checked: player.selected === 0; onClicked: player.selected = 0; enabled: player.loaded }
                    Btn { text: "rendered"; keyHint: "1"; checked: player.count > 1 && player.selected === 1; enabled: player.count > 1; onClicked: player.selected = 1 }
                    Btn { text: "⟳ Loop"; checked: player.loopOn; onClicked: player.loopOn = !player.loopOn }
                    Btn { text: "Whole"; keyHint: "Esc"; onClicked: player.wholeSample() }
                    Btn { text: "dB"; checked: tl.dbScale; onClicked: tl.dbScale = !tl.dbScale }
                    Text {
                        color: Theme.dim
                        text: !win.track ? "click a track to listen" : win.track.rendered ? win.selected + ": rendered against the original (same range)" : win.selected + ": not rendered yet (the original)"
                    }
                }
                Timeline {
                    id: tl
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    lanes: win.lanes
                    revision: win.filesRev
                    activeLane: win.track && player.count > 1 ? 1 - player.selected : 0
                    showPassages: false
                    onLaneActivated: (i) => { if (player.count > 1) player.selected = 1 - i }
                }
            }

            // log
            Rectangle {
                SplitView.preferredHeight: 150
                color: Theme.panel
                radius: 3
                ScrollView {
                    id: logView
                    anchors.fill: parent
                    anchors.margins: 6
                    TextArea {
                        readOnly: true
                        text: studio.log
                        font.family: "monospace"
                        font.pixelSize: 11
                        color: Theme.dim
                        background: null
                        onTextChanged: cursorPosition = length
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------ self-test
    property int testStep: 0
    function check(ok, what) { console.log("product-test: " + (ok ? "ok   " : "FAILED: ") + what); if (!ok) testFailed = true }
    property bool testFailed: false
    property real testY: 0
    property real testPeak: 0
    function laneWave(i) { return tl.laneWave(i) }
    readonly property var testSteps: [
        () => { check(studio.open(productTestProject), "project opened: " + studio.name) },
        () => {
            check(studio.tracks.length >= 2, studio.tracks.length + " tracks")
            const v = studio.tracks.find(t => t.role === "vocal")
            if (studio.analysis.done)
                check(!!v, "a vocal track: " + (v ? v.name + " -> " + v.resolved : "none"))
            const i = studio.tracks.find(t => t.role !== "vocal")
            studio.setTrack(i.name, "chain", "novocal_cat")
            check(studio.chainOf(i.name) === "novocal_cat", "chain set on " + i.name)
            studio.setTrack(i.name, "chain", "auto")
            check(studio.chainOf(i.name) === "novocal_guided_cat", "auto again: guided cat")
            const q = studio.quality
            studio.setQuality("draft")
            check(studio.quality === "draft", "quality draft")
            studio.setQuality(q)
            check(studio.quality === q, "quality back: " + q)
            // into Ardour: ticked where the track is cleaned, the tick stored
            const c = studio.tracks.find(t => t.resolved !== "original"), k = studio.tracks.find(t => t.resolved === "original")
            check(c.to_ardour === true && (!k || k.to_ardour === false), "into Ardour: ticked where cleaned")
            studio.setTrack(c.name, "to_ardour", false)
            check(studio.tracks.find(t => t.name === c.name).to_ardour === false, "into Ardour: unticked " + c.name)
            studio.setTrack(c.name, "to_ardour", true)
            const r = studio.tracks.find(t => t.rendered)
            win.listen(r ? r.name : studio.tracks[0].name)
        },
        () => {   // tick + bulk role / lead, the list keeps its scroll position
            const ts = studio.tracks
            const was = ts.map(t => [t.name, t.role, !!t.lead, t.role_set])
            win.pick(0, true, false); win.pick(2, true, true)
            check(win.pickedNames.length === 3, "Shift range ticks 3: " + win.pickedNames.length)
            studio.setRole(win.pickedNames, "lead")
            let v = studio.tracks.slice(0, 3)
            check(v.every(t => t.ui_role === "lead" && t.role_set && t.resolved === "neural"), "3 lead vocals at once")
            studio.setRole(win.pickedNames, "keep")
            v = studio.tracks.slice(0, 3)
            check(v.every(t => t.ui_role === "keep" && !t.lead && t.resolved === "original"), "3 don't clean at once")
            for (const [n, r, l, rs] of was) { studio.setTrack(n, "role", r); studio.setTrack(n, "lead", l); studio.setTrack(n, "role_set", rs) }
            win.picked = ({})
            trackList.contentY = Math.max(0, trackList.contentHeight - trackList.height)
            win.testY = trackList.contentY
            win.keepScroll(() => studio.setTrack(ts[ts.length - 1].name, "chain", "auto"))
        },
        () => {
            check(win.testY <= 0 || Math.abs(trackList.contentY - win.testY) < 1, "scroll kept after a change: " + trackList.contentY + " / " + win.testY)
            check(player.loaded && tl.lanes.length === (win.track.rendered ? 2 : 1), "listening: " + tl.lanes.length + " lanes")
            if (win.track.rendered)
                check(Math.abs(player.duration - (win.rEnd - win.rStart)) < 0.05, "the original cut to the rendered range: " + player.duration.toFixed(2) + " s")
            win.shot("product")
            // a render rewrites the open track's file under the same name: the waveform follows
            const other = studio.tracks.find(t => t.rendered && t.name !== win.selected)
            win.testPeak = laneWave(0) ? laneWave(0).peakDb : 0
            if (win.track.rendered && other) {
                check(driver.copyFile(studio.renderedFile(other.name), studio.renderedFile(win.selected)), "a new render of " + win.selected)
                studio.filesChanged()
            }
        },
        () => {
            if (win.track.rendered && laneWave(0))
                check(Math.abs(laneWave(0).peakDb - win.testPeak) > 0.01, "the waveform follows the new render: peak "
                      + win.testPeak.toFixed(1) + " -> " + laneWave(0).peakDb.toFixed(1) + " dB")
        },
        () => { console.log("product-test: " + (testFailed ? "FAILED" : "ok")); Qt.exit(testFailed ? 1 : 0) }
    ]
    function shot(name) {
        if (screenshotDir === "") return
        projectPage.grabToImage(r => r.saveToFile(screenshotDir + "/" + name + ".png"))
    }
    Timer {
        running: guiTest
        interval: 800
        repeat: true
        onTriggered: { if (win.testStep < win.testSteps.length) win.testSteps[win.testStep++]() }
    }
}
