#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""The rendered files into the Ardour session they came from, the way you would do it by hand.

  python3 tools/to_ardour.py <project folder> [--tracks A,B] [--dry-run]
  (the app: "Into Ardour…"; the same as python3 tools/project.py to-ardour)

For each Ardour track with a rendered project track ticked "into Ardour" (default: the ones
that are cleaned; --tracks: these):
- it has a cleaned track already ("<track> Cleaned": the one made last time, else by its
  name, any case, also "<track> Denoised" made by hand): that track's regions are replaced
  by the new render; its name, plugins, fader, routing and mute stay as you set them;
- else a new track "<track> Cleaned" right below it: a copy of the track (plugins, sends,
  fader, pan, group, outputs: what Ardour's "Duplicate" makes) with the render on it, and
  the original track muted.
The render is copied into the session (interchange/<session>/audiofiles/, a new file each time,
never over an existing one) with a bext timestamp, and placed where the recording starts:
"Move to Original Position" puts it back there. The re-import leaves the Cleaned tracks out.

The session must be closed in Ardour, with no crash-recovery file (.pending) left: Ardour would
offer to recover it on the next start, without these changes. The session file is changed as
text, only the lines of these tracks; the state before is kept as <name>.ardour.bleed-backup.
The session's recordings are only read.
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ardour_session import is_cleaned, original_of, session_start  # noqa: E402
from scan import open_wav  # noqa: E402
from wavio import copy_with_bext  # noqa: E402

SUFFIX = " Cleaned"
OBJECTS = r"\s*<(Route|IO|Processor|Controllable|AutomationList|Pannable|Panner|Diskstream)\b"


def esc(s):
    """An attribute value as libxml writes it."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def norm(name):
    return re.sub(r"\s+", " ", name).strip().lower()


def session_file(folder):
    name = os.path.basename(os.path.normpath(folder))
    p = os.path.join(folder, name + ".ardour")
    if os.path.exists(p):
        return p
    files = sorted(glob.glob(os.path.join(folder, "*.ardour")))
    if not files:
        sys.exit(f"no Ardour session file in {folder}")
    return files[0]


def check_closed(folder):
    pending = glob.glob(os.path.join(folder, "*.pending"))
    if pending:
        sys.exit("the session has a crash-recovery file (" + ", ".join(os.path.basename(p) for p in pending) + "): "
                 "open the session in Ardour once (recover or not, as you like), save, close Ardour, then again")
    try:
        ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout.splitlines()
    except OSError:
        ps = []
    for line in ps:
        exe = os.path.basename(line.split(" ")[0]) if line else ""
        if exe.lower().startswith("ardour") and not exe.endswith("-lua"):
            sys.exit("Ardour is running: save and close the session first")


class Session:
    """The session file as lines; every change is a small text edit."""

    def __init__(self, path):
        self.path = path
        self.text = open(path, encoding="utf-8").read()
        self.lines = self.text.split("\n")
        self.root = ET.fromstring(self.text)
        self.rate = int(self.root.get("sample-rate"))
        m = re.search(r'superclocks-per-second="(\d+)"', self.text)
        self.scs = int(m[1]) if m else 282240000
        top = max(int(x) for x in re.findall(r'(?<![\w-])id="(\d+)"', self.text))
        self.next_id = max(int(self.root.get("id-counter", "0")), top + 1)
        self.bitslot = max([int(x) for x in re.findall(r'type="intsend"[^>]*bitslot="(\d+)"', self.text)]
                           + [int(x) for x in re.findall(r'bitslot="(\d+)"[^>]*type="intsend"', self.text)] + [0])

    def new_id(self):
        self.next_id += 1
        return str(self.next_id - 1)

    def sc(self, samples):
        return samples * self.scs // self.rate

    # ---- finding lines
    def find(self, pattern, lo=0, hi=None):
        r = re.compile(pattern)
        for i in range(lo, len(self.lines) if hi is None else hi):
            if r.search(self.lines[i]):
                return i
        return None

    def end_of(self, i):
        """The last line of the element that opens on line i."""
        line = self.lines[i]
        if line.rstrip().endswith("/>"):
            return i
        indent = len(line) - len(line.lstrip())
        tag = re.match(r"\s*<([\w-]+)", line)[1]
        close = " " * indent + f"</{tag}>"
        for j in range(i + 1, len(self.lines)):
            if self.lines[j].rstrip() == close:
                return j
        raise ValueError(f"no end for line {i + 1}")

    def section(self, tag):
        a = self.find(rf"^  <{tag}>")
        if a is None:
            raise ValueError(f"no <{tag}> in the session")
        return a, self.end_of(a)

    def route_line(self, rid):
        a, b = self.section("Routes")
        return self.find(rf'^    <Route .*(?<![\w-])id="{rid}"', a, b)

    # ---- what is in it
    def tracks(self):
        """[(id, name, order, playlist id, inputs)] of the audio tracks."""
        out = []
        for r in self.root.find("Routes"):
            pi = r.find("PresentationInfo")
            if pi is None or "AudioTrack" not in pi.get("flags", ""):
                continue
            inp = [io for io in r.findall("IO") if io.get("direction") == "Input"]
            out.append((r.get("id"), r.get("name"), int(pi.get("order", 0)), r.get("audio-playlist"),
                        len(inp[0].findall("Port")) if inp else 1))
        return out

    # ---- changes
    def add_source(self, fname, pos):
        sid = self.new_id()
        _, b = self.section("Sources")
        self.lines.insert(b, f'    <Source name="{esc(fname)}" take-id="" type="audio" flags="" id="{sid}" '
                             f'natural-position="a{self.sc(pos)}" channel="0" origin="" gain="1"/>')
        return sid

    def region(self, name, sids, frames, pos, whole):
        rid = self.new_id()
        src = " ".join(f'source-{i}="{s}"' for i, s in enumerate(sids)) + " " + \
            " ".join(f'master-source-{i}="{s}"' for i, s in enumerate(sids))
        line = (f'<Region name="{esc(name)}" muted="0" opaque="1" locked="0" video-locked="0" automatic="0" '
                f'whole-file="{1 if whole else 0}" import="0" external="1" sync-marked="0" left-of-split="0" '
                f'right-of-split="0" hidden="0" position-locked="0" valid-transients="0" start="a0" '
                f'length="a{self.sc(frames)}@a{self.sc(pos) if not whole else 0}" sync-position="a0" ancestral-start="a0" '
                f'ancestral-length="a0@a0" stretch="1" shift="1" layering-index="0" tags="" contents="0" rgroup="0" '
                f'envelope-active="0" default-fade-in="0" default-fade-out="0" fade-in-active="1" fade-out-active="1" '
                f'fade-before-fx="0" scale-amplitude="1" id="{rid}" type="audio" first-edit="nothing" {src} '
                f'channels="{len(sids)}"/>')
        return line

    def add_whole_file(self, name, sids, frames, pos):
        _, b = self.section("Regions")
        self.lines.insert(b, "    " + self.region(name, sids, frames, pos, True))

    def set_playlist(self, plid, region_line):
        """The playlist's regions replaced by one."""
        a, b = self.section("Playlists")
        i = self.find(rf'^    <Playlist id="{plid}"', a, b)
        if i is None:
            raise ValueError(f"no playlist {plid}")
        if self.lines[i].rstrip().endswith("/>"):
            self.lines[i] = self.lines[i].rstrip()[:-2].rstrip() + ">"
            self.lines.insert(i + 1, "    </Playlist>")
        j = self.end_of(i)
        del self.lines[i + 1:j]
        self.lines.insert(i + 1, "      " + region_line)

    def add_playlist(self, plid, name, route_id, region_line):
        _, b = self.section("Playlists")
        self.lines[b:b] = [f'    <Playlist id="{plid}" name="{esc(name)}" type="audio" orig-track-id="{route_id}" '
                           f'pgroup-id="" shared-with-ids="" frozen="0" combine-ops="0">',
                           "      " + region_line, "    </Playlist>"]

    def set_mute(self, rid, on):
        i = self.route_line(rid)
        j = self.end_of(i)
        v = "1" if on else "0"
        for k in range(i, j):
            ln = self.lines[k]
            if ln.lstrip().startswith("<MuteMaster ") and re.match(r"^      <", ln):
                self.lines[k] = re.sub(r'muted="\d"', f'muted="{v}"', ln)
            elif re.match(r'^      <Controllable name="mute" ', ln):
                self.lines[k] = re.sub(r'value="[^"]*"', f'value="{v}"', ln)

    def duplicate(self, rid, new_name, plid):
        """A copy of route rid named new_name right below it, playing playlist plid; new ids.
        Returns the new route's id."""
        i = self.route_line(rid)
        j = self.end_of(i)
        block = self.lines[i:j + 1]
        old = re.search(r' name="([^"]*)"', block[0])[1]           # escaped, as in the file
        new = esc(new_name)
        ids = {}

        def new_id(m):
            if m[1] not in ids:
                ids[m[1]] = self.new_id()
            return f'id="{ids[m[1]]}"'

        a, b = self.section("Routes")
        my_order = int(re.search(r'<PresentationInfo order="(\d+)"', "\n".join(block))[1])
        # everything below it moves down one place
        for k in range(a, b):
            m = re.match(r'^(      <PresentationInfo order=")(\d+)(".*)$', self.lines[k])
            if m and int(m[2]) > my_order:
                self.lines[k] = f"{m[1]}{int(m[2]) + 1}{m[3]}"
        out, reverse = [], []
        for n, ln in enumerate(block):
            # Ardour's own objects get new ids; what a plugin keeps (e.g. a Lua plugin's
            # <Port id="0">: its parameter number) stays as it is
            if re.match(OBJECTS, ln):
                ln = re.sub(r'(?<![\w-])id="(\d+)"', new_id, ln)
            if n == 0:
                ln = ln.replace(f' name="{old}"', f' name="{new}"', 1)
                ln = re.sub(r'audio-playlist="\d+"', f'audio-playlist="{plid}"', ln)
            ln = re.sub(r'(<PresentationInfo order=")\d+', rf"\g<1>{my_order + 1}", ln)
            if 'type="triggerbox"' in ln:
                ln = re.sub(r'( order=")\d+', rf"\g<1>{my_order + 1}", ln)
            for attr in ("name", "output"):
                ln = ln.replace(f' {attr}="{old}"', f' {attr}="{new}"')
                ln = ln.replace(f' {attr}="{old}/', f' {attr}="{new}/')
            ln = ln.replace(f'="recorder:{old}"', f'="recorder:{new}"').replace(f'="player:{old}"', f'="player:{new}"')
            if 'type="intsend"' in ln:
                self.bitslot += 1
                ln = re.sub(r'bitslot="\d+"', f'bitslot="{self.bitslot}"', ln)
            if re.match(r'^      <Controllable name="rec-enable" ', ln):
                ln = re.sub(r'value="[^"]*"', 'value="0"', ln)
            out.append(ln)
        # the ports it connects to: the connection back
        port = None
        for ln in out:
            m = re.match(r'\s*<Port name="([^"]*)"', ln)
            if m:
                port = m[1]
            m = re.match(r'\s*<Connection other="([^"]*)"', ln)
            if m and port:
                reverse.append((m[1], port))
        self.lines[j + 1:j + 1] = out
        new_rid = ids[re.search(r'(?<![\w-])id="(\d+)"', block[0])[1]]
        for other, mine in reverse:
            k = self.find(rf'^\s*<Port name="{re.escape(other)}"')
            if k is None:
                continue
            ind = re.match(r"\s*", self.lines[k])[0] + "  "
            e = self.end_of(k)
            if e == k:                   # <Port .../> without connections
                self.lines[k] = self.lines[k].rstrip()[:-2].rstrip() + ">"
                self.lines.insert(k + 1, ind[:-2] + "</Port>")
                e = k + 1
            conns = self.lines[k + 1:e]
            line = f'{ind}<Connection other="{mine}"/>'
            if line not in conns:
                at = k + 1 + sum(1 for c in conns if c.strip().startswith("<Connection ") and c < line)
                self.lines.insert(at, line)
        # its route group
        g = re.search(r' route-group="([^"]*)"', block[0])
        if g:
            gs = self.find(rf'^    <RouteGroup .* name="{re.escape(g[1])}"')
            if gs is not None:
                def add(m):
                    ids = m[1].split()
                    ids.insert(ids.index(rid) + 1 if rid in ids else len(ids), new_rid)
                    return f' routes="{" ".join(ids)}"'
                self.lines[gs] = re.sub(r' routes="([^"]*)"', add, self.lines[gs], count=1)
        return new_rid

    def save(self):
        self.lines[1] = re.sub(r'id-counter="\d+"', f'id-counter="{self.next_id}"', self.lines[1], count=1) \
            if 'id-counter="' in self.lines[1] else self.lines[1]
        text = "\n".join(self.lines)
        ET.fromstring(text)                        # still well-formed
        shutil.copy2(self.path, self.path + ".bleed-backup")
        with open(self.path + ".bleed-tmp", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(self.path + ".bleed-tmp", self.path)


def chain_of(t):
    from render import chain_of as c
    return c(t)


def pick(tracks, only):
    if only:
        missing = [n for n in only if n not in tracks]
        if missing:
            sys.exit("not in the project: " + ", ".join(missing))
        return list(only)
    return [n for n, t in tracks.items() if t.get("to_ardour", chain_of(t) != "original")
            and not is_cleaned(re.sub(r"-[LR]$", "", n))]     # a cleaned track exported before (older exports)


def unique(folder, base, chans):
    """New file names in folder for the channels ("%L", "%R" as Ardour names them; "" for mono):
    base.wav, else base-2.wav, ...; never one that is there."""
    k = 1
    while True:
        ps = [os.path.join(folder, f"{base}{'' if k == 1 else f'-{k}'}{c}.wav") for c in chans]
        if not any(os.path.lexists(p) for p in ps):
            return ps
        k += 1


def run(proj, only=None, dry=False):
    """put(), its messages also in render/render.log (the app's log panel shows it)."""
    lines = []

    def say(msg):
        print(msg, flush=True)
        lines.append(msg)
    try:
        put(proj, only, dry, say)
    except SystemExit as e:
        if isinstance(e.code, str):
            lines.append("into Ardour: " + e.code)
        raise
    finally:
        if lines:
            os.makedirs(os.path.join(proj, "render"), exist_ok=True)
            with open(os.path.join(proj, "render", "render.log"), "a") as f:
                f.write(datetime.datetime.now().strftime("%H:%M:%S ") + "\n".join(lines) + "\n")


def put(proj, only, dry, say):
    pj = json.load(open(os.path.join(proj, "project.json")))
    src = pj.get("source") or {}
    if src.get("kind") != "ardour":
        sys.exit("this project wasn't imported from an Ardour session")
    folder = src["path"]
    if not os.path.isdir(folder):
        sys.exit(f"the session folder {folder} is not there")
    path = session_file(folder)
    if not dry:
        check_closed(folder)
    s = Session(path)
    # Ardour keeps one folder in interchange/, named after the session folder (it refuses a
    # session with two): the one that is there
    inter = [d for d in glob.glob(os.path.join(folder, "interchange", "*")) if os.path.isdir(d)]
    if len(inter) > 1:
        sys.exit(f"more than one folder in {folder}/interchange: Ardour wouldn't open the session")
    audio_dir = os.path.join(inter[0] if inter else os.path.join(folder, "interchange", os.path.basename(os.path.normpath(folder))),
                             "audiofiles")
    rj_path = os.path.join(proj, "render", "render.json")
    if not os.path.exists(rj_path):
        sys.exit("nothing rendered yet")
    rj = json.load(open(rj_path))
    pos = session_start(pj) + int(round(rj.get("start", 0) * s.rate))
    tracks = pj["tracks"]
    names = [n for n in pick(tracks, only) if os.path.exists(os.path.join(proj, "render", f"{n}.wav"))]

    strack = s.tracks()
    by_id = {t[0]: t for t in strack}
    by_name = {}
    for t in strack:
        if not is_cleaned(t[1]):
            by_name.setdefault(t[1], []).append(t)
    cleaned_by_name = {norm(original_of(t[1])): t for t in strack if is_cleaned(t[1])}
    # project tracks -> Ardour tracks: by the id the export noted, else by name ("03 Conga-L" -> "Conga")
    groups, problems = {}, []
    for n in names:
        a = tracks[n].get("ardour")
        if a and a["route_id"] in by_id:
            rid, ch = a["route_id"], a["channel"]
        else:
            m = re.match(r"^(?:\d+\s+)?(.*?)(?:-([LR]))?$", n)
            cand = by_name.get(m[1], [])
            if len(cand) != 1:
                problems.append(f"{n}: no track \"{m[1]}\" in the session (renamed? Re-import once: then the tracks "
                                "are found by Ardour's id)" if not cand else f"{n}: several tracks \"{m[1]}\"")
                continue
            rid, ch = cand[0][0], {"L": 0, "R": 1}.get(m[2], 0)
        groups.setdefault(rid, {})[ch] = n
    cleaned = pj.setdefault("ardour", {}).setdefault("cleaned", {})
    plan = []
    for rid, chans in groups.items():
        _, rname, _, _, inputs = by_id[rid]
        if sorted(chans) != list(range(inputs)):
            problems.append(f"{rname}: {inputs} channel(s) in Ardour, rendered: {', '.join(chans.values())}")
            continue
        files = [os.path.join(proj, "render", f"{chans[c]}.wav") for c in range(inputs)]
        frames = {open_wav(f)[1]["frames"] for f in files}
        dn = cleaned.get(rid)
        dt = by_id.get(dn) if dn else None
        if dt is None:
            dt = cleaned_by_name.get(norm(rname))
        plan.append((rid, rname, files, min(frames), dt))
    for p in problems:
        say("  skipped: " + p)
    if not plan:
        say("nothing to put into Ardour" + (" (tick the tracks \"into Ardour\", render them)" if not problems else ""))
        return
    say(f"into {path}:")
    for rid, rname, files, frames, dt in plan:
        say(f"  {rname}: " + (f"replaces the regions of \"{dt[1]}\"" if dt else f"new track \"{rname}{SUFFIX}\", \"{rname}\" muted")
              + f" ({frames / s.rate:.1f} s from {pos / s.rate:.2f} s)")
    if dry:
        say("(dry run: nothing changed)")
        return
    os.makedirs(audio_dir, exist_ok=True)
    made = []
    try:
        for rid, rname, files, frames, dt in plan:
            title = (dt[1] if dt else rname + SUFFIX)
            sids = []
            chans = [""] if len(files) == 1 else ["%L", "%R"] if len(files) == 2 else [f"%{c + 1}" for c in range(len(files))]
            for f, dst in zip(files, unique(audio_dir, re.sub(r'[/\\:*?"<>|]', "_", title), chans)):
                copy_with_bext(f, dst, pos, description=f"Bleed Reduction: {rname}")
                made.append(dst)
                sids.append(s.add_source(os.path.basename(dst), pos))
            s.add_whole_file(title, sids, frames, pos)
            region = s.region(title, sids, frames, pos, False)
            if dt:
                s.set_playlist(dt[3], region)
                cleaned[rid] = dt[0]
            else:
                plid = s.new_id()
                new_rid = s.duplicate(rid, title, plid)
                s.add_playlist(plid, title, new_rid, region)
                s.set_mute(rid, True)
                cleaned[rid] = new_rid
        s.save()
    except BaseException:
        for f in made:                        # our copies only
            os.remove(f)
        raise
    pj["ardour"]["exported"] = datetime.datetime.now().isoformat(timespec="seconds")
    p = os.path.join(proj, "project.json")
    json.dump(pj, open(p + ".tmp", "w"), indent=1)
    os.replace(p + ".tmp", p)
    say(f"done: {len(plan)} track(s); the session before: {os.path.basename(path)}.bleed-backup")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--tracks", help="only these (comma-separated)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(os.path.abspath(a.project), a.tracks.split(",") if a.tracks else None, a.dry_run)


if __name__ == "__main__":
    main()
