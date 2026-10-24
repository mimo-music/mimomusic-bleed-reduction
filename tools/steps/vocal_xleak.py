#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Lead out of the coro mics: on the neural outputs of all vocal mics of a song.

  python3 tools/steps/vocal_xleak.py <concert folder> --song N [--over 14] [--floor -20]

No subtraction: the lead reaches the coro mics 9-15 ms late but mostly as
room sound (even a filter fitted on the leak passage itself
removes only 2-7 dB). Instead a per time-frequency suppression:
  roles: a lead sings alone most of the time it sings (49-86 % in the three
     concerts), a coro singer almost never (0-3 %); >= 25 % -> lead. No flag.
     Coro singers sing together: nothing is removed between them.
  leak j -> i (between the groups only), per half octave: median of
     band power i / j in the frames where j sings and i's singer doesn't
     (lead: where it sings alone); j's power with a reverb tail (0.15 s).
  gain per bin: Wiener-like from own power / (sum of the predicted leaks
     raised by --over dB), smoothed 3 bins x 3 frames, not below --floor.
Against hand-marked passages, --over 14: leak passages -16..-20 dB, singing
passages -0.0..-0.2 dB (three concerts).
Coro mics only: on the lead mic it is a gate you hear (the
lead stands back or sings along with the coro: not separable by level), so
the lead mic keeps neural. neural_xvoc is sample-aligned with neural, so a
passage can be switched back to neural (app, DAW).
Reads <n>.neural.out.wav of the vocal mics (--dir: every one in that folder; the render
uses it), writes <n>.neural_xvoc.out.wav next to them (coro mics), and the roles and
passages (coro / lead) to a json file.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import istft, stft

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from wavio import read_wav, write_wav  # noqa: E402
from paths import work, listen  # noqa: E402


def runs(b):
    """(start, end) frame index pairs of the True runs."""
    d = np.diff(np.concatenate([[0], b.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def fill_gaps(b, n):
    """b with False runs shorter than n frames between True runs filled."""
    b = b.copy()
    r = runs(b)
    for (_, e0), (s1, _) in zip(r, r[1:]):
        if s1 - e0 < n:
            b[e0:s1] = True
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="the concert folder (with --song), or with --dir: unused")
    ap.add_argument("--song", type=int)
    ap.add_argument("--dir", help="instead of a song: a folder with <n>.neural.out.wav of the vocal mics "
                                  "(the product's render segments); writes the coro versions there")
    ap.add_argument("--lead", help="with --dir: the lead mics (comma-separated), else found from the data")
    ap.add_argument("--over", type=float, default=14.0, help="leak raised by dB before the gain")
    ap.add_argument("--floor", type=float, default=-20.0, help="lowest gain, dB")
    ap.add_argument("--tail", type=float, default=0.15, help="reverb decay of the leak, s")
    ap.add_argument("--lead-over", type=float, default=8.0, help="--over on the lead mic (only for the markers now)")
    ap.add_argument("--lead-on", type=float, default=5.0,
                    help="lead mic this many dB over the predicted coro leak (0.5 s median): the lead sings")
    ap.add_argument("--lead-hold", type=float, default=0.3, help="s around that: still the lead's phrase")
    ap.add_argument("--tag", default="neural_xvoc")
    a = ap.parse_args()
    if a.dir:
        lo = a.dir
        names = sorted(os.path.basename(p).split(".")[0] for p in glob.glob(os.path.join(lo, "*.neural.out.wav")))
        concert = None
    else:
        if a.song is None:
            sys.exit("--song or --dir")
        concert = os.path.basename(os.path.normpath(a.folder))
        summ = json.load(open(work("auto_round", concert, f"song{a.song:02d}.json")))
        s0, s1 = summ["span"]
        lo = listen("songs", concert, f"song{a.song:02d}_{s0:.1f}-{s1:.1f}")
        names = [n for n, r in summ["results"].items() if r.get("tag") == "vocal"
                 and os.path.exists(os.path.join(lo, f"{n}.neural.out.wav"))]
    if len(names) < 2:
        sys.exit(f"{lo}: fewer than 2 vocal mics with a neural version")
    X = []
    for n in names:
        x, sr = read_wav(os.path.join(lo, f"{n}.neural.out.wav"))
        X.append(x[:, 0])
    L = min(map(len, X))
    X = np.array([x[:L] for x in X], dtype=np.float32)
    nfft = 2048 if sr <= 48000 else 4096
    hop = nfft // 4
    f, _, Z = stft(X, sr, nperseg=nfft, noverlap=nfft - hop)
    Z = Z.astype(np.complex64)
    P = (np.abs(Z) ** 2 + 1e-20).astype(np.float32)          # [mic, bin, frame]
    M, K, T = P.shape
    alpha = np.float32(np.exp(-hop / sr / a.tail))
    Pt = P.copy()                                            # power with a reverb tail
    for k in range(1, T):
        Pt[:, :, k] = np.maximum(P[:, :, k], alpha * Pt[:, :, k - 1])
    band = (f > 100) & (f < 6000)
    lev = 10 * np.log10(P[:, band].mean(axis=1))
    edges = 100 * 2 ** (np.arange(0, 40) / 2)
    grp = np.digitize(f, edges[edges < sr / 2])              # half octaves

    own = np.array([lev[j] > np.percentile(lev[j], 95) - 12 for j in range(M)])
    solo = np.array([own[j] & (lev[j] - np.delete(lev, j, axis=0).max(axis=0) >= 12) for j in range(M)])
    alone = solo.sum(axis=1) / np.maximum(own.sum(axis=1), 1)
    lead = alone >= 0.25
    if a.lead:                    # given (the product: from the whole recording, not one segment)
        lead = np.array([n in a.lead.split(",") for n in names])
    for j in range(M):
        print(f"{names[j]}: sings {own[j].mean() * 100:.0f} %, alone {alone[j] * 100:.0f} % of it -> "
              + ("lead" if lead[j] else "coro"))
    if lead.all() or not lead.any():
        sys.exit("no lead/coro split found: nothing done")

    Lk = np.zeros_like(P)
    over = np.where(lead, a.lead_over, a.over).astype(np.float32)   # float32 as before: same bytes for the coro mics
    for j in range(M):
        for i in range(M):
            if i == j or lead[i] == lead[j]:
                continue
            sel = solo[j] if lead[j] else (own[j] & ~own[i])
            if sel.sum() < 20:
                print(f"  {names[j]} -> {names[i]}: too few frames ({sel.sum()}), left out")
                continue
            g = np.zeros(K, np.float32)
            for b in np.unique(grp):
                m = grp == b       # band sums per frame: single bins are too noisy
                r = 10 * np.log10(P[i][m][:, sel].sum(axis=0) / Pt[j][m][:, sel].sum(axis=0))
                g[m] = np.median(r)
            print(f"  {names[j]} -> {names[i]}: leak {np.median(g[band]):+5.1f} dB ({sel.sum()} frames)")
            Lk[i] += (10 ** ((g + over[i]) / 10))[:, None] * Pt[j]
    snr = uniform_filter1d(uniform_filter1d(P / (Lk + 1e-20), 3, axis=1), 3, axis=2)
    gain = np.maximum(10 ** (a.floor / 20), np.sqrt(np.clip(1 - 1 / snr, 0, 1))).astype(np.float32)
    # who sings when, for the markers: the lead where its mic is >= --lead-on dB over the
    # predicted coro leak (0.5 s median, +-hold), the coro where a coro mic sings (own level)
    fps = sr / hop
    w = max(1, int(a.lead_hold * fps))
    hold = lambda b: np.convolve(b.astype(float), np.ones(2 * w + 1), mode="same") > 0
    coro_sings = hold(median_filter(own[~lead].any(axis=0).astype(np.int8), size=max(1, int(0.5 * fps))) > 0)
    lead_sings = np.zeros(T, bool)
    for i in np.flatnonzero(lead):
        exc = 10 * np.log10(P[i][band].sum(axis=0) / (Lk[i][band].sum(axis=0) / 10 ** (over[i] / 10) + 1e-20))
        # and at its own singing level: the coro leak into the lead mic varies by +-6 dB
        med = max(1, int(0.5 * fps))
        lead_sings |= hold((median_filter(exc, size=med) >= a.lead_on)
                           & (median_filter(own[i].astype(np.int8), size=med) > 0))
    # one label per frame, then the majority over 1 s, passages >= 1 s. Two kinds (they sing
    # something all together, or something different): coro = the coro sings (the leader with
    # them or silent), lead = the leader alone. A pregón over the coro can't be told from the
    # leader singing with them: proposed as coro.
    names3 = ("coro", "lead", "coro")
    lab = np.where(coro_sings, 1, np.where(lead_sings, 2, 0))   # 0 nobody, 1 coro, 2 lead
    win = np.ones(max(1, int(1.0 * fps)))
    votes = np.array([np.convolve((lab == k).astype(float), win, mode="same") for k in range(4)])
    lab = votes.argmax(axis=0)
    # singing stretches (gaps < 0.5 s filled, >= 1 s), split by label; a piece < 1 s
    # goes to the piece before it (the first one: to the next)
    passages = []
    for s_, e_ in runs(fill_gaps(lab > 0, int(0.5 * fps))):
        if (e_ - s_) / fps < 1.0:
            continue
        seg = lab[s_:e_].copy()
        for k in range(1, len(seg)):          # filled gaps: the label before
            if seg[k] == 0:
                seg[k] = seg[k - 1]
        pieces = [[s_ + x, s_ + y, int(seg[x])] for x, y in
                  ((x, y) for v in (1, 2, 3) for x, y in runs(seg == v))]
        pieces.sort()
        merged = []
        for pc in pieces:
            if merged and (pc[1] - pc[0] < fps or merged[-1][2] == pc[2]):
                merged[-1][1] = pc[1]
            else:
                merged.append(pc)
        if len(merged) > 1 and merged[0][1] - merged[0][0] < fps:
            merged[1][0] = merged[0][0]
            merged.pop(0)
        passages += [(x / fps, y / fps, names3[v - 1]) for x, y, v in merged]
    passages.sort()
    for name in ("coro", "lead"):
        p_ = [(x, y) for x, y, n_ in passages if n_ == name]
        print(f"{name}: {len(p_)} passages, {sum(y - x for x, y in p_):.0f} s")
    _, y = istft(Z * gain, sr, nperseg=nfft, noverlap=nfft - hop)
    y = y[:, :L]
    for i, n in enumerate(names):
        out = os.path.join(lo, f"{n}.{a.tag}.out.wav")
        if lead[i]:
            if os.path.exists(out):
                os.remove(out)
            print(f"{n} (lead): neural only")
            continue
        ch = 10 * np.log10(np.mean(y[i].astype(np.float64) ** 2) / np.mean(X[i].astype(np.float64) ** 2) + 1e-20)
        write_wav(out, y[i].astype(np.float32), sr)
        print(f"{n} (coro): whole change {ch:+.1f} dB -> {os.path.basename(out)}")
    if a.dir:
        return
    json.dump({"lead": [n for n, l in zip(names, lead) if l], "coro": [n for n, l in zip(names, lead) if not l],
               "passages": [[round(x, 2), round(y_, 2), n_] for x, y_, n_ in passages]},
              open(work("auto_round", concert, f"song{a.song:02d}_xvoc.json"), "w"), indent=1)
    p = os.path.join(lo, "versions.json")      # description for the listener
    d = json.load(open(p)) if os.path.exists(p) else {}
    d[a.tag] = (f"neural, then the lead turned down where it dominates (coro mics only; up to {-a.floor:.0f} dB)")
    json.dump(dict(sorted(d.items())), open(p, "w"), indent=1)


if __name__ == "__main__":
    main()
