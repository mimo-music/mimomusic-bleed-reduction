#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Projects of the product app (Bleed Reduction): a folder with project.json.

  python3 tools/project.py new <project folder> --name NAME (--stems FOLDER | --ardour SESSION_FOLDER)
  python3 tools/project.py analyse <project folder> [--threads N]
  python3 tools/project.py show <project folder>
  python3 tools/project.py reimport <project folder> [--source FOLDER]

new      the stems: a folder of WAV files (one per mic; the file name is the track's name),
         linked, not copied; or an Ardour session: every track exported unprocessed
         (tools/export_raw_stems.sh) into <project>/stems/<id>/.
reimport the recording again from the same source, with the same settings: exported into a fresh
         stems folder, every track keeps its settings by name (also when its number changed:
         "03 Conga" = "05 Conga"), new tracks are marked "new",
         tracks that are gone are dropped. The renders stay; the next render does only the tracks
         whose audio changed (tools/render.py). --source for projects made before the source was stored.
analyse  the basic analysis on the whole recording (minutes, then ~3 min per track on 8
         cores): delays and leak between the mics (scan.py), the songs (timeline.py), and
         per track how much voice it carries (vocal_share.py) -> a suggested role:
         vocal, instrument (also the "mixed" ones: an instrument that sounds like a voice, sax,
         room; same chain), keep (silent: left as it is). Only tracks the user hasn't set ("role_set") get a
         suggestion. The user changes roles and chains in the app; tools/render.py renders.
project.json:
  {"name", "id", "stems_dir", "created",
   "source": {"kind": "ardour" | "stems", "path"},
   "tracks": {"<track>": {"file", "role", "lead", "role_set", "chain", "share_db", "new"}},
   "analysis": {"done", "songs": [[start, end], ...], "rate", "seconds"},
   "render": {"start", "end"}}
chain "auto": vocal lead -> neural, vocal coro -> neural_xvoc, instrument / mixed ->
novocal_guided_cat, keep -> original (the best rated in listening tests).
roles: vocal (+ lead: the lead singers' mics; several are fine), instrument, keep (old projects: mixed = instrument;
"line" and "silent" are read as keep).
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from paths import work, VENV_PY  # noqa: E402
from resources import default_threads, limit_threads  # noqa: E402
from scan import open_wav  # noqa: E402


def save(proj, pj):
    p = os.path.join(proj, "project.json")
    json.dump(pj, open(p + ".tmp", "w"), indent=1)
    os.replace(p + ".tmp", p)


def load(proj):
    return json.load(open(os.path.join(proj, "project.json")))


def new(a):
    proj = os.path.abspath(a.project)
    if os.path.exists(os.path.join(proj, "project.json")):
        sys.exit(f"{proj} is a project already")
    pid = new_id(a.name)
    source = {"kind": "ardour", "path": os.path.abspath(a.ardour)} if a.ardour else \
        {"kind": "stems", "path": os.path.abspath(a.stems)}
    sd, tracks, rate = fetch(proj, pid, source)
    pj = {"name": a.name, "id": pid, "stems_dir": sd, "created": datetime.datetime.now().isoformat(timespec="seconds"),
          "source": source, "tracks": tracks, "analysis": {"done": False}, "render": {"start": 0, "end": None}}
    save(proj, pj)
    print(f"project {a.name}: {len(tracks)} tracks, {rate} Hz -> {proj}")


def new_id(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") + datetime.datetime.now().strftime("_%Y%m%d_%H%M%S")


def fetch(proj, pid, source):
    """The source's tracks into <proj>/stems/<pid>/ (Ardour: exported; stems: linked).
    Returns (stems folder, {track: fresh settings}, rate); removes the folder on failure."""
    sd = os.path.join(proj, "stems", pid)
    os.makedirs(sd)
    try:
        if source["kind"] == "ardour":
            rc = subprocess.call(["sh", os.path.join(HERE, "export_raw_stems.sh"), source["path"], sd])
            if rc:
                sys.exit("the Ardour export failed (is the session closed in Ardour?)")
            files = sorted(f for f in os.listdir(sd) if f.lower().endswith(".wav"))
        else:
            files = []
            for f in sorted(os.listdir(source["path"])):
                if f.lower().endswith(".wav") and open_wav(os.path.join(source["path"], f)) is not None:
                    os.symlink(os.path.join(source["path"], f), os.path.join(sd, f))
                    files.append(f)
        if len(files) < 2:
            sys.exit("need at least two WAV files")
        tracks = {}
        rates = set()
        for f in files:
            info = open_wav(os.path.join(sd, f))[1]
            rates.add(info["sr"])
            tracks[os.path.splitext(f)[0]] = {"file": os.path.join(sd, f), "role": "instrument", "lead": False, "chain": "auto"}
        if len(rates) > 1:
            sys.exit(f"the files have different sample rates: {sorted(rates)}")
    except BaseException:
        shutil.rmtree(sd, ignore_errors=True)
        raise
    return sd, tracks, rates.pop()


def bare(name):
    """A track's name without the export's number: "03 Conga" -> "Conga"."""
    return re.sub(r"^\d+\s+", "", name)


def reimport(a):
    proj = os.path.abspath(a.project)
    pj = load(proj)
    source = pj.get("source")
    if a.source:
        p = os.path.abspath(a.source)
        source = {"kind": "ardour" if glob.glob(os.path.join(p, "*.ardour")) else "stems", "path": p}
    if not source:
        sys.exit("this project doesn't know where its recording came from: give --source FOLDER")
    if not os.path.isdir(source["path"]):
        sys.exit(f"{source['path']} is not there any more: give --source FOLDER")
    print(f"re-import from {source['path']} ({source['kind']})", flush=True)
    # the finished render pieces: what they were made from, while the old files are still
    # there (then the next render does only the tracks whose audio changed)
    from render import upgrade_work
    upgrade_work(proj, pj)
    pid = new_id(pj["name"])
    sd, fresh, rate = fetch(proj, pid, source)
    old = pj["tracks"]
    by_bare = {}
    for n in old:
        by_bare.setdefault(bare(n), []).append(n)
    keep = ("role", "lead", "role_set", "chain", "share_db")
    tracks, kept, added, used = {}, [], [], set()
    for n, t in fresh.items():
        same = by_bare.get(bare(n), [])
        o = n if n in old else same[0] if len(same) == 1 else None    # two old tracks of that name: no guess
        if o and o not in used:
            used.add(o)
            t.update({k: old[o][k] for k in keep if k in old[o]})
            kept.append(n if o == n else f"{o} -> {n}")
        else:
            t["new"] = True
            added.append(n)
        tracks[n] = t
    gone = [n for n in old if n not in used]
    old_sd = pj.get("stems_dir")
    pj.update(id=pid, stems_dir=sd, source=source, tracks=tracks,
              reimported=datetime.datetime.now().isoformat(timespec="seconds"))
    save(proj, pj)
    # the old export is ours (inside the project): gone now; linked stems folders only hold links
    if old_sd and os.path.realpath(old_sd).startswith(os.path.join(proj, "stems") + os.sep) and old_sd != sd:
        shutil.rmtree(old_sd, ignore_errors=True)
    msg = (f"re-imported from {source['path']}: {len(tracks)} tracks, {rate} Hz, {len(kept)} kept their settings"
           + "".join(f"\n  renamed: {k}" for k in kept if " -> " in k)
           + "".join(f"\n  new (set its role): {n}" for n in added)
           + "".join(f"\n  gone: {n}" for n in gone)
           + "\n  the next Render does only the tracks whose audio or settings changed")
    print(msg)
    # the app's log panel shows render/render.log: the summary goes there too
    os.makedirs(os.path.join(proj, "render"), exist_ok=True)
    with open(os.path.join(proj, "render", "render.log"), "a") as f:
        f.write(datetime.datetime.now().strftime("%H:%M:%S ") + msg + "\n")


def analyse(a):
    limit_threads(a.threads)
    proj = os.path.abspath(a.project)
    pj = load(proj)
    sd, c = pj["stems_dir"], pj["id"]
    steps = [("scan", ["python3", "-u", "tools/scan.py", sd], work("scan", c, "scan.json")),
             ("songs", ["python3", "-u", "tools/timeline.py", sd], work("timeline", c, "timeline.json")),
             ("voice share", [VENV_PY, "-u", "tools/steps/vocal_share.py", sd, "--threads", str(a.threads)],
              work("timeline", c, "vocal_share.json"))]
    for label, cmd, out in steps:
        if os.path.exists(out):
            print(f"{label}: done before")
            continue
        print(f"{label} …", flush=True)
        rc = subprocess.call(cmd, cwd=ROOT)
        if rc:
            sys.exit(f"{label} failed")
    tl = json.load(open(work("timeline", c, "timeline.json")))
    vs = json.load(open(work("timeline", c, "vocal_share.json")))
    for n, t in pj["tracks"].items():
        v = vs.get(n, {})
        t["share_db"] = v.get("share_db")
        if t.get("role_set"):          # the user's choice stays
            continue
        role = v.get("tag", "instrument")
        t["role"] = {"vocal": "vocal", "silent": "keep"}.get(role, "instrument")
        t["lead"] = False
    voc = [n for n, t in pj["tracks"].items() if t["role"] == "vocal"]
    free = [n for n in voc if not pj["tracks"][n].get("role_set")]
    if free and not any(pj["tracks"][n].get("lead") for n in voc):
        # the lead: of the vocal mics, the one carrying the most voice (the user corrects it)
        best = max(free, key=lambda n: pj["tracks"][n].get("share_db") or -99)
        pj["tracks"][best]["lead"] = True
    info = open_wav(next(iter(pj["tracks"].values()))["file"])[1]
    pj["analysis"] = {"done": True, "songs": [[round(s, 1), round(e, 1)] for s, e in
                                               (x if isinstance(x, list) else (x["start"], x["end"]) for x in tl["songs"])],
                      "rate": info["sr"], "seconds": round(info["frames"] / info["sr"], 1)}
    save(proj, pj)
    show(a)


def show(a):
    pj = load(os.path.abspath(a.project))
    sys.path.insert(0, HERE)
    from render import chain_of
    print(f"{pj['name']} ({len(pj['tracks'])} tracks)" + (f", {len(pj['analysis'].get('songs', []))} songs, "
                                                          f"{pj['analysis'].get('seconds', 0) / 60:.0f} min" if pj["analysis"].get("done") else ", not analysed"))
    for n, t in pj["tracks"].items():
        print(f"  {n:14s} {t['role'] + (' (lead)' if t.get('lead') else ''):18s} {chain_of(t)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("project")
    p.add_argument("--name", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--stems")
    g.add_argument("--ardour")
    p = sub.add_parser("analyse")
    p.add_argument("project")
    p.add_argument("--threads", type=int, default=default_threads(),
                   help="default: half the processor's threads, or BLEED_THREADS")
    p = sub.add_parser("show")
    p.add_argument("project")
    p = sub.add_parser("reimport")
    p.add_argument("project")
    p.add_argument("--source", help="the Ardour session folder or the stems folder (default: the one it came from)")
    a = ap.parse_args()
    {"new": new, "analyse": analyse, "show": show, "reimport": reimport}[a.cmd](a)


if __name__ == "__main__":
    main()
