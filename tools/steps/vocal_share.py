# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Suggest track tags (vocal / mixed / instrument) from the neural vocal
network (run with the separation venv).

  work/venv-sep/bin/python tools/steps/vocal_share.py <concert folder> \
      [--windows 4] [--seconds 8] [--threads 8]

Per stem: --windows passages of --seconds, at the stem's loudest moments
(timeline.json levels, spread over the concert, not muted), run through
the network; vocal share = energy of the vocal estimate / energy of the
stem there. Loud moments, because there the track's own source dominates:
a vocal mic is loud when the singer sings, an instrument mic when the
instrument plays. Tags: vocal > -3 dB, instrument < -12 dB, mixed between.
Writes vocal_share.json next to timeline.json.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from scan import open_wav, read_frames, stem_file  # noqa: E402
from paths import work  # noqa: E402
import neural_sep  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--windows", type=int, default=4)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--model", default="kj_melroformer")
    ap.add_argument("--only", help="comma-separated stems (tests)")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    concert = os.path.basename(os.path.normpath(a.folder))
    tl = json.load(open(work("timeline", concert, "timeline.json")))
    lev = np.load(work("timeline", concert, "levels.npz"))
    step = float(tl["step"])
    model, cfg, mt = neural_sep.load(a.model)
    out_path = work("timeline", concert, "vocal_share.json")
    res = json.load(open(out_path)) if os.path.exists(out_path) else {}
    for name in tl["names"]:
        if name in res or (a.only and name not in a.only.split(",")):
            continue
        L, M = lev[f"lev_{name}"], lev[f"mute_{name}"]
        if np.all(M) or tl["p90_db"][tl["names"].index(name)] < -70:
            res[name] = {"tag": "silent", "share_db": None}
            continue
        # loudest 1 s spots, one per equal slice of the concert
        w = int(a.seconds / step)
        sm = np.convolve(np.where(M, -200, L), np.ones(w) / w, "same")
        n = len(sm)
        spots = []
        for k in range(a.windows):
            s0, s1 = k * n // a.windows, (k + 1) * n // a.windows
            i = s0 + int(np.argmax(sm[s0:s1]))
            spots.append(max(0.0, i * step - a.seconds / 2))
        mm, info = open_wav(stem_file(a.folder, name))
        sr = info["sr"]
        ev = ex = 0.0
        t = time.time()
        for s in spots:
            x = read_frames(mm, info, int(s * sr), int(a.seconds * sr)).astype(np.float32)
            v = neural_sep.separate(model, cfg, mt, x, sr)
            ev += float(np.sum(v.astype(np.float64) ** 2))
            ex += float(np.sum(x.astype(np.float64) ** 2))
        share = 10 * np.log10(ev / ex + 1e-12)
        tag = "vocal" if share > -3 else "instrument" if share < -12 else "mixed"
        res[name] = {"tag": tag, "share_db": round(share, 1), "spots_s": [round(s, 1) for s in spots]}
        print(f"{name:>12}: vocal share {share:6.1f} dB -> {tag}  ({time.time() - t:.0f} s)", flush=True)
        json.dump(res, open(out_path, "w"), indent=1)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
