#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""The render: every track of a project, whole length, through its chain.

  python3 tools/render.py <project folder> [--start S] [--end S] [--tracks A,B | --track A ...] [--threads N]
  python3 tools/render.py <project folder> --plan          only show what would be done

The project (tools/project.py): project.json with the tracks (file, role, chain). The
recording is done in segments (--segment, default 180 s, with --overlap 4 s on each side),
so memory stays small and a stopped render resumes where it stopped (finished segments are
kept). Per segment, in <project>/work/segNNN/:
  cut         <track>.orig.wav (only the tracks some chain needs)
  network     <track>.kj.wav  vocals estimate (Mel-RoFormer) of every track that isn't
              "original"; vocal mics always (the guided removal needs their voice)
  neural      vocal mics: <track>.neural.out.wav; instrument mics: <track>.novocal.out.wav
  coro        neural_xvoc: the lead's leak turned down on the coro mics (vocal_xleak --dir)
  guided      novocal_guided: the voice removed only where the vocal mics explain it
  category    <chain base> through the category network, the mic's own category kept
              (quality "final": the network run 4 times on shifted input and averaged, no
              buzz at its frame rate; "draft": once, ~4x faster, for trying on a laptop;
              --quality, else the project's render.quality, else final)
Only what changed is done again: done.json keeps per track a key of what its result was made from: its chain, the
audio of its own cut (a hash of the samples, so a re-import of unchanged audio costs nothing),
and for the coro and guided steps the vocal mics' audio (their clean voice is used); a track
whose key changed is done again, the others are kept. The voice network's output (neural /
novocal, the heavy part) stays in the segment for the next time, with the hash it came from.
Then the segments are joined (linear crossfades over the overlaps; the chain outputs are
sample-aligned with the input) into <project>/render/<track>.wav: 32-bit float, the
recording's rate, exactly the length of the range, so they line up with the originals; a bext
chunk holds where the file starts on the session's timeline (Ardour: "Move to Original Position").
Progress: <project>/render/progress.json; log: <project>/render/render.log.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from paths import VENV_PY  # noqa: E402
from resources import default_threads, limit_threads  # noqa: E402
from scan import open_wav, read_frames  # noqa: E402
from ardour_session import session_start  # noqa: E402
from wavio import bext_chunk, write_wav  # noqa: E402

# the processing's version: a finished segment of an older one is rendered again
# 2: long digital silence cut out before the networks (silence.py)
VERSION = 2

# chain -> the steps it needs (in this order)
CHAINS = {
    "original": [],
    "neural": ["neural"],
    "neural_xvoc": ["neural", "coro"],
    "novocal": ["novocal"],
    "novocal_guided": ["novocal", "guided"],
    "novocal_cat": ["novocal", "cat"],
    "novocal_guided_cat": ["novocal", "guided", "cat"],
    "novocal_guided_cat_mask": ["novocal", "guided", "cat", "mask"],   # the category network as a gain: no whine
}
AUTO = {"vocal": "neural", "coro": "neural_xvoc", "lead": "neural", "instrument": "novocal_guided_cat",
        "mixed": "novocal_guided_cat", "keep": "original", "line": "original", "silent": "original"}


def chain_of(t):
    c = t.get("chain", "auto")
    if c == "auto":
        role = t.get("role", "instrument")
        if role == "vocal":
            role = "lead" if t.get("lead") else "coro"
        c = AUTO.get(role, "original")
    return c


class Log:
    def __init__(self, path):
        self.f = open(path, "a")

    def __call__(self, msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        self.f.write(line + "\n")
        self.f.flush()


def run(cmd, log, cwd=ROOT):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip().splitlines()
    for ln in out:
        if "Warning" not in ln and "warn(" not in ln and ln.strip() and not ln.startswith(" "):
            log("    " + ln[:200])
    return p.returncode


class WavStream:
    """A float32 mono WAV written in pieces (RF64 when it gets past 4 GB), with a bext chunk:
    where it starts on the timeline (time_ref, samples; Ardour's "Move to Original Position")."""

    def __init__(self, path, sr, time_ref=0):
        self.path, self.sr, self.n = path, sr, 0
        self.bext = bext_chunk(time_ref)
        self.f = open(path + ".part", "wb")
        self.f.write(self._header(0))

    def _header(self, n):
        data = n * 4
        fmt = struct.pack("<HHIIHH", 3, 1, self.sr, self.sr * 4, 4, 32)
        head = 4 + 8 + 16 + 8 + 28 + len(self.bext) + 8
        if data + head + 36 < 2 ** 32:
            return (b"RIFF" + struct.pack("<I", head + data) + b"WAVE"
                    + b"fmt " + struct.pack("<I", 16) + fmt
                    + b"JUNK" + struct.pack("<I", 28) + b"\0" * 28        # room for ds64
                    + self.bext + b"data" + struct.pack("<I", data))
        return (b"RF64" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
                + b"fmt " + struct.pack("<I", 16) + fmt
                + b"ds64" + struct.pack("<I", 28) + struct.pack("<QQQI", head + data, data, n, 0)
                + self.bext + b"data" + struct.pack("<I", 0xFFFFFFFF))

    def write(self, y):
        self.f.write(np.asarray(y, dtype="<f4").tobytes())
        self.n += len(y)

    def close(self):
        self.f.seek(0)
        self.f.write(self._header(self.n))
        self.f.close()
        os.replace(self.path + ".part", self.path)


def read_range(path, a, b):
    """Samples [a, b) of channel 0 as float32 (zeros past the end)."""
    mm, info = open_wav(path)
    a0, b0 = max(0, a), min(info["frames"], b)
    x = read_frames(mm, info, a0, max(0, b0 - a0)) if b0 > a0 else np.zeros(0, np.float32)
    return np.concatenate([np.zeros(a0 - a, np.float32), x, np.zeros(max(0, b - max(b0, a)), np.float32)])[:b - a]


def audio_hash(path, a, b):
    """The samples [a, b) of a track: what a segment's result depends on (not the file's name or date)."""
    return hashlib.sha1(read_range(path, a, b).tobytes()).hexdigest()[:16]


def vocals_of(tracks):
    vocal = [n for n in tracks if tracks[n].get("role") == "vocal"]
    return vocal, [n for n in vocal if tracks[n].get("lead")]


def track_key(n, chain, hashes, vocal, leads, shifts):
    """What track n's result in a segment is made from."""
    k = {"chain": chain, "audio": hashes[n], "vocal": n in vocal, "shifts": shifts, "version": VERSION}
    steps = CHAINS[chain]
    if "coro" in steps or "guided" in steps:
        k["vocals"] = {v: hashes[v] for v in sorted(vocal)}
    if "coro" in steps:
        k["leads"] = sorted(leads)
    return k


def upgrade_work(proj, pj):
    """done.json of renders before the per-track keys (they only knew the files they were cut
    from): the keys from those files, as long as they are still there (project.py reimport
    calls this before it removes the old export)."""
    tracks = pj["tracks"]
    vocal, leads = vocals_of(tracks)
    for done in sorted(glob.glob(os.path.join(proj, "work", "seg*", "done.json"))):
        dj = json.load(open(done))
        if "tracks" in dj or dj.get("version", 1) != VERSION or "inputs" not in dj:
            continue
        c0, c1 = dj["range"]
        sig = {n: [t["file"], os.path.getsize(t["file"]), int(os.path.getmtime(t["file"]))]
               for n, t in tracks.items() if os.path.exists(t["file"])}
        hashes = {n: audio_hash(tracks[n]["file"], c0, c1) for n in sig}
        keys = {}
        for n, c in dj.get("chains", {}).items():
            need = [n] + (vocal if {"coro", "guided"} & set(CHAINS[c]) else [])
            if n in tracks and chain_of(tracks[n]) == c and all(dj["inputs"].get(m) == sig.get(m) for m in need) \
                    and os.path.exists(os.path.join(os.path.dirname(done), f"{n}.result.wav")):
                keys[n] = track_key(n, c, hashes, vocal, leads, dj.get("shifts", 4))
        json.dump({"range": dj["range"], "tracks": keys, "net": {}}, open(done + ".tmp", "w"))
        os.replace(done + ".tmp", done)


def drop_tracks(proj, names):
    """What was rendered for tracks that are not in the project any more (a re-import: renamed
    in Ardour without the project knowing it, or deleted): their files and keys removed."""
    if not names:
        return
    gone = set(names)

    def files(d):
        for f in os.listdir(d):
            if any(f.startswith(n + ".") for n in gone):
                os.remove(os.path.join(d, f))
    for done in sorted(glob.glob(os.path.join(proj, "work", "seg*", "done.json"))):
        dj = json.load(open(done))
        for k in ("tracks", "net"):
            if k in dj:
                dj[k] = {n: v for n, v in dj[k].items() if n not in gone}
        files(os.path.dirname(done))
        json.dump(dj, open(done + ".tmp", "w"))
        os.replace(done + ".tmp", done)
    out = os.path.join(proj, "render")
    if os.path.isdir(out):
        files(out)
        rj = os.path.join(out, "render.json")
        if os.path.exists(rj):
            r = json.load(open(rj))
            r["chains"] = {n: c for n, c in r.get("chains", {}).items() if n not in gone}
            json.dump(r, open(rj, "w"), indent=1)


def rename_tracks(proj, renames):
    """What was rendered for tracks that are named differently now ({old: new}; a re-import:
    "05 Conga" is "04 Conga"): their files and keys under the new names, so the next
    render keeps them."""
    if not renames:
        return
    rn = lambda n: renames.get(n, n)                      # noqa: E731
    tmp = {o: f".renaming-{i}" for i, o in enumerate(renames)}

    def files(d):
        for m in (tmp, {tmp[o]: n for o, n in renames.items()}):     # in two steps: names may swap
            for f in sorted(os.listdir(d)):
                a = next((a for a in m if f.startswith(a + ".")), None)
                if a:
                    os.rename(os.path.join(d, f), os.path.join(d, m[a] + f[len(a):]))

    def key(k):
        if "vocals" in k:
            k["vocals"] = {rn(v): h for v, h in k["vocals"].items()}
        if "leads" in k:
            k["leads"] = sorted(rn(v) for v in k["leads"])
        return k
    def moved(d):          # a track that is gone may have had a renamed one's new name: the renamed wins
        return sorted(d.items(), key=lambda x: x[0] in renames)
    for done in sorted(glob.glob(os.path.join(proj, "work", "seg*", "done.json"))):
        dj = json.load(open(done))
        dj["tracks"] = {rn(n): key(k) for n, k in moved(dj.get("tracks", {}))}
        dj["net"] = {rn(n): v for n, v in moved(dj.get("net", {}))}
        files(os.path.dirname(done))
        json.dump(dj, open(done + ".tmp", "w"))
        os.replace(done + ".tmp", done)
    out = os.path.join(proj, "render")
    if os.path.isdir(out):
        files(out)
        rj = os.path.join(out, "render.json")
        if os.path.exists(rj):
            r = json.load(open(rj))
            r["chains"] = {rn(n): c for n, c in moved(r.get("chains", {}))}
            json.dump(r, open(rj, "w"), indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--start", type=float, help="s (default: the project's render range, else 0)")
    ap.add_argument("--end", type=float, help="s (default: the project's render range, else the end)")
    ap.add_argument("--tracks", help="only these (comma-separated)")
    ap.add_argument("--track", action="append", default=[], help="only this one (several times: several)")
    ap.add_argument("--segment", type=float, default=180.0)
    ap.add_argument("--overlap", type=float, default=4.0)
    ap.add_argument("--threads", type=int, default=default_threads(),
                    help="default: half the processor's threads, or BLEED_THREADS")
    ap.add_argument("--quality", choices=["final", "draft"], help="default: the project's render.quality, else final")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--keep-work", action="store_true", help="keep the intermediate files of each segment")
    a = ap.parse_args()
    limit_threads(a.threads)
    proj = os.path.abspath(a.project)
    pj = json.load(open(os.path.join(proj, "project.json")))
    tracks = pj["tracks"]
    only = set(a.tracks.split(",") if a.tracks else []) | set(a.track)
    names = [n for n in tracks if not only or n in only]
    if not names:
        sys.exit("none of those tracks is in the project")
    infos = {n: open_wav(tracks[n]["file"])[1] for n in tracks}
    sr = infos[names[0]]["sr"]
    if any(i["sr"] != sr for i in infos.values()):
        sys.exit("the tracks have different sample rates")
    total = min(i["frames"] for i in infos.values())
    rr = pj.get("render", {})
    start = a.start if a.start is not None else rr.get("start", 0) or 0
    end = a.end if a.end is not None else rr.get("end") or total / sr
    quality = a.quality or rr.get("quality") or "final"
    shifts = 1 if quality == "draft" else 4
    A, B = int(round(start * sr)), min(total, int(round(end * sr)))
    seg, ov = int(a.segment * sr), int(a.overlap * sr)
    bounds = list(range(A, B, seg)) + [B]
    nseg = len(bounds) - 1
    chains = {n: chain_of(tracks[n]) for n in names}
    vocal, leads = vocals_of(tracks)
    out_dir = os.path.join(proj, "render")
    os.makedirs(out_dir, exist_ok=True)
    log = Log(os.path.join(out_dir, "render.log"))
    log(f"render {pj.get('name', proj)}: {start:.1f}-{B / sr:.1f} s, {nseg} segment(s), {len(names)} tracks, {sr} Hz, quality {quality}")
    for n in names:
        log(f"  {n:12s} {tracks[n].get('role', '?'):10s} -> {chains[n]}")
    if a.plan:
        return
    prog_path = os.path.join(out_dir, "progress.json")

    def progress(**kw):
        d = dict(project=pj.get("name"), segments=nseg, start=start, end=B / sr, time=time.time(), **kw)
        json.dump(d, open(prog_path + ".tmp", "w"))
        os.replace(prog_path + ".tmp", prog_path)

    upgrade_work(proj, pj)                              # done.json of an older render: its keys
    t_begin = time.time()
    for k in range(nseg):
        s0, s1 = bounds[k], bounds[k + 1]
        c0, c1 = max(A, s0 - ov), min(B, s1 + ov)          # with the overlaps
        d = os.path.join(proj, "work", f"seg{k:03d}")
        done = os.path.join(d, "done.json")
        dj = json.load(open(done)) if os.path.exists(done) else {}
        if os.path.isdir(d) and (dj.get("range") != [c0, c1] or "tracks" not in dj):
            if dj:
                log(f"segment {k + 1}/{nseg}: another range or an older version, done again")
            shutil.rmtree(d)
            dj = {}
        os.makedirs(d, exist_ok=True)
        hashes = {n: audio_hash(tracks[n]["file"], c0, c1) for n in set(names) | set(vocal)}
        keys = {n: track_key(n, chains[n], hashes, vocal, leads, shifts) for n in names}
        old = dj.get("tracks", {})
        redo = [n for n in names if old.get(n) != keys[n] or not os.path.exists(os.path.join(d, f"{n}.result.wav"))]
        if not redo:
            log(f"segment {k + 1}/{nseg}: done before")
            continue
        log(f"segment {k + 1}/{nseg}: {c0 / sr:.1f}-{c1 / sr:.1f} s, {len(redo)} of {len(names)} tracks"
            + (": " + ", ".join(redo) if len(redo) < len(names) else ""))

        def net_files(n):               # the voice network's outputs that are kept
            # a vocal mic: its voice (the coro and guided steps of the others use it); also the
            # rest when its own chain removes the voice (a vocal mic set to an instrument chain)
            modes = (["vocal"] if n in vocal else []) + \
                (["novocal"] if n not in vocal or "novocal" in CHAINS[chains.get(n, "neural")] else [])
            return {m: os.path.join(d, f"{n}.{'neural' if m == 'vocal' else 'novocal'}.out.wav") for m in modes}

        # what stays: the results, and the network outputs of the same audio; the rest (a
        # stopped run's steps, made from what may have changed since) goes
        net = {n: v for n, v in dj.get("net", {}).items()
               if n in hashes and v == f"{hashes[n]}:{VERSION}" and all(map(os.path.exists, net_files(n).values()))}
        keep = {"done.json"} | {os.path.basename(f) for n in net for f in net_files(n).values()}
        for f in os.listdir(d):
            if f not in keep and not f.endswith(".result.wav"):
                p = os.path.join(d, f)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        # the tracks done again are out of it until they are finished (a stop: again next time)
        state = {"range": [c0, c1], "tracks": {n: v for n, v in old.items() if n in tracks and n not in redo}, "net": net}

        def save_state():
            json.dump(state, open(done + ".tmp", "w"))
            os.replace(done + ".tmp", done)

        save_state()
        need_voc = any({"coro", "guided"} & set(CHAINS[chains[n]]) for n in redo)
        work_set = set(n for n in redo if chains[n] != "original") | (set(vocal) if need_voc else set())
        steps_total = len(work_set) + len(redo)
        step_i = [0]

        def mark(what):
            step_i[0] += 1
            el = time.time() - t_begin
            frac = (k + step_i[0] / max(1, steps_total)) / nseg
            progress(segment=k + 1, step=what, fraction=frac, eta=el / max(frac, 1e-3) * (1 - frac))

        def cut(n):
            p = os.path.join(d, f"{n}.orig.wav")
            if not os.path.exists(p):
                write_wav(p, read_range(tracks[n]["file"], c0, c1), sr)
            return p

        # network (the heavy part) and the neural / novocal versions
        for n in sorted(work_set, key=lambda n: (n not in vocal, n)):
            mark(f"network {n}")
            if n in net:
                continue
            kj = os.path.join(d, f"{n}.kj.wav")
            log(f"  {n}: voice network")
            if run([VENV_PY, "tools/steps/neural_sep.py", cut(n), kj, "--threads", str(a.threads)], log):
                sys.exit(f"{n}: the voice network failed")
            for mode, f in net_files(n).items():
                run(["python3", "tools/steps/neural_mix.py", cut(n), kj, os.path.join(d, n), "--mode", mode], log)
                if not os.path.exists(f):
                    sys.exit(f"{n}: {os.path.basename(f)} missing")
            os.remove(kj)
            net[n] = f"{hashes[n]}:{VERSION}"
            save_state()
        # coro versions (of every coro mic at once)
        if any("coro" in CHAINS[chains[n]] for n in redo) and len(vocal) >= 2:
            log("  coro: lead leak on the coro mics")
            cmd = [VENV_PY, "tools/steps/vocal_xleak.py", d, "--dir", d]
            if leads:
                cmd += ["--lead", ",".join(leads)]
            run(cmd, log)
        # guided and category
        guided = [n for n in redo if "guided" in CHAINS[chains[n]]]
        if guided:
            log(f"  guided voice removal: {', '.join(guided)}")
            for n in guided:
                cut(n)
            if run([VENV_PY, "tools/steps/guided_novocal.py", d] + guided, log):
                sys.exit("the guided voice removal failed")
        for n in redo:
            c = chains[n]
            if "cat" in CHAINS[c]:
                mark(f"category {n}")
                base = "novocal_guided" if "guided" in CHAINS[c] else "novocal"
                log(f"  {n}: category network on {base}")
                if run(["python3", "tools/steps/cat_step.py", d, n, "--base", base, "--tag", c,
                        "--threads", str(a.threads), "--stems-dir", os.path.join(d, "stems"), "--no-versions",
                        "--shifts", str(shifts)] + (["--mask"] if "mask" in CHAINS[c] else []), log):
                    sys.exit(f"{n}: the category network failed")
        # results: the chain's output (the original for "original"; a coro version missing -> neural)
        for n in redo:
            c = chains[n]
            src = cut(n) if c == "original" else os.path.join(d, f"{n}.{c}.out.wav")
            if c == "neural_xvoc" and not os.path.exists(src):
                log(f"  {n}: no coro version in this segment (lead?), neural used")
                src = os.path.join(d, f"{n}.neural.out.wav")
            if not os.path.exists(src):
                sys.exit(f"{n}: {os.path.basename(src)} missing")
            shutil.copyfile(src, os.path.join(d, f"{n}.result.wav"))
        state["tracks"].update({n: keys[n] for n in redo})
        save_state()
        if not a.keep_work:
            keep = {"done.json"} | {os.path.basename(f) for n in net for f in net_files(n).values()}
            for f in os.listdir(d):
                if f not in keep and not f.endswith(".result.wav"):
                    p = os.path.join(d, f)
                    shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        mark("segment done")

    # join: linear crossfades over the overlaps; only the tracks with a newer piece than their file
    from wavio import read_wav
    seg_dirs = [os.path.join(proj, "work", f"seg{k:03d}") for k in range(nseg)]
    origin = session_start(pj)          # the recording's sample 0 on the Ardour timeline (0: stems)

    def stale(n):
        out = os.path.join(out_dir, f"{n}.wav")
        return not os.path.exists(out) or any(
            os.path.getmtime(os.path.join(sd, f"{n}.result.wav")) > os.path.getmtime(out) for sd in seg_dirs)

    prev = os.path.join(out_dir, "render.json")
    pr = json.load(open(prev)) if os.path.exists(prev) else {}
    same_range = pr.get("start") == start and pr.get("end") == B / sr
    join = [n for n in names if not same_range or stale(n)]
    log(f"joining the segments: {len(join)} of {len(names)} tracks" if join else "every track's file is up to date")
    for n in join:
        w = WavStream(os.path.join(out_dir, f"{n}.wav"), sr, time_ref=origin + A)
        tail = None                     # the previous segment's samples past its end
        for k in range(nseg):
            s0, s1 = bounds[k], bounds[k + 1]
            c0, c1 = max(A, s0 - ov), min(B, s1 + ov)
            y = read_wav(os.path.join(proj, "work", f"seg{k:03d}", f"{n}.result.wav"))[0][:, 0].astype(np.float32)
            y = np.pad(y, (0, max(0, (c1 - c0) - len(y))))[:c1 - c0]
            core = y[s0 - c0:s1 - c0].copy()
            if tail is not None and len(tail):
                # the overlap after s0: the previous segment fades out, this one in
                m = min(len(tail), len(core))
                r = np.linspace(0, 1, m, dtype=np.float32)
                core[:m] = tail[:m] * (1 - r) + core[:m] * r
            w.write(core)
            tail = y[s1 - c0:]
        w.close()
        log(f"  {n}.wav: {w.n / sr:.1f} s")
    progress(segment=nseg, step="done", fraction=1.0, eta=0)
    kept = {n: c for n, c in pr.get("chains", {}).items() if n in tracks and same_range}   # other tracks rendered before
    json.dump({"start": start, "end": B / sr, "chains": {**kept, **chains}, "rate": sr, "quality": quality,
               "finished": time.strftime("%Y-%m-%d %H:%M")},
              open(os.path.join(out_dir, "render.json"), "w"), indent=1)
    log(f"DONE in {(time.time() - t_begin) / 60:.1f} min: {out_dir}")


if __name__ == "__main__":
    main()
