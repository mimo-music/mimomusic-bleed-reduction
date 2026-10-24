# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Level timeline of a whole concert folder: sets, songs, mutes, and per
stem the passages where its own source is silent (learning candidates).

Usage:
  python3 tools/timeline.py <folder> [--step 0.5] [--out DIR]

Streams every complete stem once (blocks of 60 s, memory-mapped) into a
level per step (dB RMS) and a mute flag (SQ5: a muted channel is a constant
value). Cached in <out>/levels.npz, so new stems only add their own pass.

Segmentation, all from the levels:
  - muted: constant samples;
  - band playing: share of the instrument stems that are active
    (> their p90 - 15 dB); songs are runs where it stays high, separated
    by gaps of >= --gap s where it drops (applause in the vocal and room
    mics doesn't count, those stems can be excluded with --not-band);
  - own source silent, per stem: < its p90 - 20 dB while not muted and
    the band plays. These are the bleed-only passages to learn from.
Writes timeline.json and timeline.png.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.optimize import nnls

sys.path.insert(0, os.path.dirname(__file__))
from scan import open_wav, read_frames, stem_label
from paths import work


def stem_levels(mm, info, step):
    sr = info["sr"]
    hop = int(step * sr)
    n = info["frames"] // hop
    lev = np.empty(n, np.float32)
    mute = np.empty(n, bool)
    per = max(1, int(60 / step))           # steps per block
    for b in range(0, n, per):
        m = min(per, n - b)
        x = read_frames(mm, info, b * hop, m * hop).reshape(m, hop)
        lev[b:b + m] = 10 * np.log10(np.mean(x.astype(np.float64) ** 2, axis=1) + 1e-20)
        mute[b:b + m] = np.ptp(x, axis=1) == 0
    return lev, mute


def load_leaks(*paths):
    """{(src, dst): leak dB while dst's own source is silent} from scan.json."""
    for p in paths:
        if os.path.exists(p):
            d = json.load(open(p))
            n = d["names"]
            c, ca, lag = d["silent_coupling_db"], d["coupling_db"], d["lag_ms"]
            out = {}
            for i in range(len(n)):
                for j in range(len(n)):
                    if i == j:
                        continue
                    # no silent passages of dst (it plays all the time): use
                    # the estimate over all frames, whichever way the lag
                    # points (two-way leaks between close mics: the louder
                    # direction decides the lag sign)
                    out[(n[i], n[j])] = c[i][j] if c[i][j] > -99 else ca[i][j]
            return out
    return {}


def runs(mask, min_len):
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    keep = en - st >= min_len
    return list(zip(st[keep], en[keep]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--gap", type=float, default=4.0, help="min gap between songs, s")
    ap.add_argument("--min-song", type=float, default=60.0, help="min song length, s")
    ap.add_argument("--not-band", default="MAIN", help="name parts not counted as band (mix, vocal, room)")
    ap.add_argument("--out")
    ap.add_argument("--detector", choices=["level", "explained"], default="explained")
    ap.add_argument("--dirty", type=float, default=-15.0,
                    help="leave a ref out of the silence predictor when the target leaks into it above this (dB)")
    a = ap.parse_args()
    out = a.out or work("timeline", os.path.basename(os.path.normpath(a.folder)))
    os.makedirs(out, exist_ok=True)
    cache = os.path.join(out, "levels.npz")
    have = dict(np.load(cache)) if os.path.exists(cache) else {}

    names, L, M = [], [], []
    for fn in sorted(os.listdir(a.folder)):
        if not fn.lower().endswith(".wav"):
            continue
        r = open_wav(os.path.join(a.folder, fn))
        if r is None or not r[1]["complete"]:
            print(f"skip {fn}: incomplete or unreadable", file=sys.stderr)
            continue
        name = stem_label(fn, r[1])
        if f"lev_{name}" not in have or float(have.get("step", 0)) != a.step:
            print(f"  levels {name}", flush=True)
            have[f"lev_{name}"], have[f"mute_{name}"] = stem_levels(*r, a.step)
        names.append(name)
        L.append(have[f"lev_{name}"])
        M.append(have[f"mute_{name}"])
    have["step"] = np.array(a.step)
    np.savez(cache, **have)
    n = min(len(l) for l in L)
    L = np.array([l[:n] for l in L])
    M = np.array([m[:n] for m in M])
    K = len(names)
    t = np.arange(n) * a.step

    live = [L[k][~M[k] & (L[k] > -120)] for k in range(K)]
    p90 = np.array([np.percentile(l, 90) if len(l) else -200 for l in live])
    active = (L > p90[:, None] - 15) & ~M
    nb = [s.upper() for s in a.not_band.split(",") if s]
    band_idx = [k for k in range(K) if not any(s in names[k].upper() for s in nb) and p90[k] > -70]
    playing_share = active[band_idx].mean(axis=0)
    # smooth over 2 s so single quiet beats don't split a song
    w = max(1, int(2 / a.step))
    sm = np.convolve(playing_share, np.ones(w) / w, mode="same")
    band = sm > 0.25
    gaps = runs(~band, int(a.gap / a.step))
    # songs: band runs between gaps, long enough
    edges = [0] + [e for g in gaps for e in g] + [n]
    songs = []
    for s, e in zip(edges[0::2], edges[1::2]):
        if e - s >= a.min_song / a.step and band[s:e].mean() > 0.5:
            songs.append((s, e))
    all_muted = M[band_idx].all(axis=0) if band_idx else np.zeros(n, bool)

    silent_level = (L < p90[:, None] - 20) & ~M & band[None, :]
    # second detector: the target is silent where the other stems explain
    # its level (bleed only). Fit target power ~ sum g_r P_r to the lower
    # envelope (iteratively on the frames with the lowest ratio), using only
    # refs the target does not leak into (scan.json, silent-target leak
    # > --dirty dB): a ref that carries the target's own source would
    # explain the singing too.
    scan_json = work("scan", os.path.basename(os.path.normpath(a.folder)), "scan.json")
    if a.detector == "explained" and not os.path.exists(scan_json):
        # without it every ref may predict, also mics that carry the
        # target's own source (piano "silent" 99 % by its other channel)
        sys.exit(f"{scan_json} missing: run tools/scan.py on this folder first")
    leaks = load_leaks(scan_json)
    silent_expl = np.zeros_like(silent_level)
    silent_strict = np.zeros_like(silent_level)   # < 1.5 dB: surer, for learning
    expl_refs = {}
    P = 10 ** (L / 10)
    for k in range(K):
        if k not in band_idx and not any(s_ in names[k].upper() for s_ in nb if s_ != "MAIN"):
            continue
        if "MAIN" in names[k].upper():
            continue
        refs = [r for r in band_idx if r != k and leaks.get((names[k], names[r]), -99) < a.dirty]
        m = band & ~M[k] & (L[k] > -120)
        if not refs or m.sum() < 100:
            continue
        X = P[refs].T
        keep = m.copy()
        for _ in range(8):
            g, _ = nnls(X[keep] / P[k][keep, None], np.ones(keep.sum()))
            r = 10 * np.log10(P[k] / (X @ g + 1e-30))
            keep = m & (r < np.percentile(r[m], 30))
        silent_expl[k] = m & (r < 3)
        silent_strict[k] = m & (r < 1.5)
        expl_refs[names[k]] = [names[i] for i, w in zip(refs, g) if w > 0]
    silent = silent_expl if a.detector == "explained" else silent_level
    res = dict(names=names, step=a.step, p90_db=p90.round(1).tolist(),
               band_stems=[names[k] for k in band_idx],
               songs=[(round(s * a.step, 1), round(e * a.step, 1)) for s, e in songs],
               all_muted=[(round(s * a.step, 1), round(e * a.step, 1)) for s, e in runs(all_muted, int(10 / a.step))],
               muted={names[k]: [(round(s * a.step, 1), round(e * a.step, 1)) for s, e in runs(M[k], int(5 / a.step))]
                      for k in range(K)},
               detector=a.detector, explained_by=expl_refs,
               silent_passages_strict={names[k]: [(round(s * a.step, 1), round(e * a.step, 1))
                                                  for s, e in runs(silent_strict[k], int(1.5 / a.step))]
                                       for k in range(K)},
               silent_passages={names[k]: [(round(s * a.step, 1), round(e * a.step, 1))
                                           for s, e in runs(silent[k], int(1.5 / a.step))] for k in range(K)})
    json.dump(res, open(os.path.join(out, "timeline.json"), "w"), indent=1)

    print(f"{K} stems, {n * a.step / 60:.1f} min; band stems: {len(band_idx)}")
    print(f"all band stems muted: " + ", ".join(f"{s / 60:.1f}-{e / 60:.1f} min" for s, e in res["all_muted"]))
    print(f"{len(songs)} songs:")
    for i, (s, e) in enumerate(songs):
        print(f"  {i + 1:2d}  {s * a.step / 60:6.1f} - {e * a.step / 60:6.1f} min  ({(e - s) * a.step / 60:.1f} min)")
    print("own source silent while the band plays (>= 1.5 s passages):")
    for k in range(K):
        ps = res["silent_passages"][names[k]]
        tot = sum(e - s for s, e in ps)
        print(f"  {names[k]:>12}: {len(ps):4d} passages, {tot / 60:5.1f} min, "
              f"{silent[k].sum() / max(1, band.sum()):.0%} of band time"
              + (f"  (explained by {', '.join(expl_refs[names[k]])})" if names[k] in expl_refs else ""))
    render(os.path.join(out, "timeline.png"), names, L, M, p90, songs, band, silent, a.step)
    print(f"wrote {out}/timeline.json, timeline.png")


def render(path, names, L, M, p90, songs, band, silent, step):
    K, n = L.shape
    W, row, left = 1600, 22, 110
    img = Image.new("RGB", (left + W + 10, 40 + (K + 1) * row + 20), "white")
    d = ImageDraw.Draw(img)
    cols = np.linspace(0, n, W + 1).astype(int)
    for k in range(K):
        y = 40 + k * row
        d.text((4, y + 5), names[k][:15], fill="black")
        for x in range(W):
            a_, b_ = cols[x], max(cols[x] + 1, cols[x + 1])
            if M[k, a_:b_].all():
                c = (200, 200, 255)
            else:
                v = float(np.clip((np.max(L[k, a_:b_]) - (p90[k] - 40)) / 40, 0, 1))
                g = int(255 - 220 * v)
                c = (g, g, g)
                if silent[k, a_:b_].mean() > 0.5:
                    c = (255, 200, 120)
            d.line([(left + x, y), (left + x, y + row - 3)], fill=c)
    y = 40 + K * row
    d.text((4, y + 5), "band", fill="black")
    for x in range(W):
        if band[cols[x]:max(cols[x] + 1, cols[x + 1])].mean() > 0.5:
            d.line([(left + x, y), (left + x, y + row - 3)], fill=(120, 180, 120))
    for i, (s, e) in enumerate(songs):
        xs, xe = left + s * W // n, left + e * W // n
        d.rectangle([xs, 22, xe, 34], outline=(0, 120, 0))
        d.text((xs + 2, 22), str(i + 1), fill=(0, 120, 0))
    for m in range(0, int(n * step / 60) + 1, 10):
        x = left + int(m * 60 / step * W / n)
        d.text((x, 4), f"{m}'", fill="gray")
    d.text((left + W - 420, 4), "grey: level  blue: muted  orange: own source silent", fill="gray")
    img.save(path)


if __name__ == "__main__":
    main()
