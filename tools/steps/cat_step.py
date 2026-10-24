#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Other instruments out of an instrument mic by the category network (rated best in
listening tests on violin, bongo and trumpet). One track of a song folder:

  python3 tools/steps/cat_step.py <song folder> <track> [--base novocal] [--threads 6]
      [--model htdemucs_6s] [--tag novocal_cat]

1. the network (tools/steps/neural_stems.py, separation venv) splits the voice-removed
   version (<track>.<base>.out.wav; on the original it leaves the singer in "other") into
   drums, bass, other, vocals, guitar, piano; stems cached in work/stems/<concert>/<song>/
2. the mic's own category = the loudest stem that isn't vocals (percussion: drums; tres:
   guitar; bass: bass; horns, violin: other), written as <track>.<tag>.out.wav

The stems stay in the cache, so another choice (two categories, another base) costs nothing.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from wavio import read_wav, write_wav  # noqa: E402
from paths import work, VENV_PY  # noqa: E402

DESC = ("voice removed, then an instrument category network ({model}): only the mic's own category kept "
        "(percussion = drums; tres = guitar; horns, violin = other)")


def db(v):
    return 10 * np.log10(np.mean(v.astype(np.float64) ** 2) + 1e-20)


def stems_for(folder, track, base, model, threads, stems_dir=None, shifts=4):
    """{stem: path} of the network's output for <track>.<base>.out.wav, computed if missing
    (cached in work/stems/<concert>/<song>/, or stems_dir)."""
    song = os.path.basename(os.path.normpath(folder))
    concert = os.path.basename(os.path.dirname(os.path.normpath(folder)))
    d = stems_dir or work("stems", concert, song)
    os.makedirs(d, exist_ok=True)
    prefix = os.path.join(d, f"{track}.{base}.{model}" + (f"_s{shifts}" if shifts > 1 else ""))
    src = os.path.join(folder, f"{track}.{base}.out.wav")
    have = glob.glob(prefix + ".*.wav")
    if not have or min(os.path.getmtime(p) for p in have) < os.path.getmtime(src):
        rc = subprocess.call([VENV_PY, os.path.join(HERE, "neural_stems.py"), src, prefix,
                              "--model", model, "--threads", str(threads), "--shifts", str(shifts)])
        if rc:
            sys.exit(f"{track}: the category network failed ({rc})")
        have = glob.glob(prefix + ".*.wav")
    return {os.path.basename(p)[len(os.path.basename(prefix)) + 1:-4]: p for p in have}


def keep_stems(lev):
    """The mic's own categories: the loudest non-vocal stem; when even that is more than 3 dB under
    the mic (the network split the instrument: a timba as "guitar" -6.8 / "bass" -7.2, timbal, clave),
    also every non-vocal stem within 6 dB of it."""
    order = sorted((k for k in lev if k != "vocals"), key=lambda k: -lev[k])
    if lev[order[0]] >= -3:
        return order[:1]
    return [k for k in order if lev[k] >= lev[order[0]] - 6]


def sum_stems(stems, keep):
    y, sr = read_wav(stems[keep[0]])
    y = y[:, 0].copy()
    for k in keep[1:]:
        z = read_wav(stems[k])[0][:, 0]
        n = min(len(y), len(z))
        y = y[:n] + z[:n]
    return y, sr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("track")
    ap.add_argument("--base", default="novocal", help="the version the network gets (voice already removed)")
    ap.add_argument("--model", default="htdemucs_6s")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--tag", default="novocal_cat")
    ap.add_argument("--shifts", type=int, default=4, help="network runs on shifted input, averaged: no frame-rate buzz "
                                                          "(1: the single run of the first versions)")
    ap.add_argument("--stems-dir", help="where the network's stems are cached (default work/stems/<concert>/<song>)")
    ap.add_argument("--no-versions", action="store_true", help="don't write versions.json (the product's render)")
    a = ap.parse_args()
    orig = glob.glob(os.path.join(a.folder, f"{a.track}.orig*.wav"))[0]
    stems = stems_for(a.folder, a.track, a.base, a.model, a.threads, a.stems_dir, a.shifts)
    x = read_wav(orig)[0][:, 0]
    lev = {k: db(read_wav(p)[0][:, 0]) - db(x) for k, p in stems.items()}
    keep = keep_stems(lev)
    y, sr = sum_stems(stems, keep)
    own = "+".join(keep)
    write_wav(os.path.join(a.folder, f"{a.track}.{a.tag}.out.wav"), y.astype(np.float32), sr)
    print(f"{a.track}: own category {own} ({lev[keep[0]]:+.1f} dB vs the original); others: "
          + " ".join(f"{k} {v:+.1f}" for k, v in sorted(lev.items()) if k not in keep))
    if a.no_versions:
        return
    vj = os.path.join(a.folder, "versions.json")
    d = json.load(open(vj)) if os.path.exists(vj) else {}
    d[a.tag] = DESC.format(model=a.model) + ("" if a.base == "novocal" else f"; from {a.base}")
    json.dump(dict(sorted(d.items())), open(vj, "w"), indent=1)


if __name__ == "__main__":
    main()
