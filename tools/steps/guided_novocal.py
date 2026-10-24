#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Voice removal guided by the vocal mics.

Problem (a sax mic): the voice network also takes a sax solo for a voice
(novocal -10..-15 dB in the solo), and every later step starts from novocal.

Here the network's removed part R = original - novocal is only taken out where the
singers can explain it: the leak of each vocal mic's clean voice (its `neural`
version) into this mic is measured from the cross spectrum (the mic's own
instrument doesn't correlate with the voice and averages out), the
predicted leak L = |sum_j H_j V_j| per time-frequency bin, and the removal is limited
to `--slack` dB above it:  R' = R * min(1, slack * L / |R|).  Where nobody sings,
nothing is removed; where the sax plays louder than the voice leak, the sax stays.

  work/venv-sep/bin/python tools/steps/guided_novocal.py <song folder> <track> [<track> ...]
      [--slack 6] [--tag novocal_guided]

Writes <track>.<tag>.out.wav next to the other versions. Vocal mics = the tracks with
a `neural` version in the folder.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
from scipy.signal import stft, istft

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from wavio import read_wav, write_wav  # noqa: E402
from resources import need_memory  # noqa: E402

NFFT, HOP = 4096, 1024


def spec(x, sr):
    return stft(x.astype(np.float32), sr, nperseg=NFFT, noverlap=NFFT - HOP)[2].astype(np.complex64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("tracks", nargs="+")
    ap.add_argument("--slack", type=float, default=6.0, help="dB the removal may exceed the predicted voice leak")
    ap.add_argument("--tag", default="novocal_guided")
    a = ap.parse_args()
    voc = sorted(os.path.basename(p).split(".")[0] for p in glob.glob(os.path.join(a.folder, "*.neural.out.wav")))
    print("vocal mics:", " ".join(voc))
    first, sr = read_wav(glob.glob(os.path.join(a.folder, f"{a.tracks[0]}.orig*.wav"))[0])
    n = len(first)
    need_memory((len(voc) + 4) * n / HOP * (NFFT // 2 + 1) * 8 * 1.3, "guided_novocal")
    V = [spec(read_wav(os.path.join(a.folder, f"{v}.neural.out.wav"))[0][:n, 0], sr) for v in voc]
    pw = [np.abs(v) ** 2 for v in V]
    for t in a.tracks:
        x = read_wav(glob.glob(os.path.join(a.folder, f"{t}.orig*.wav"))[0])[0][:n, 0]
        nv = read_wav(os.path.join(a.folder, f"{t}.novocal.out.wav"))[0][:n, 0]
        X, R = spec(x, sr), spec(x - nv, sr)
        L = np.zeros(X.shape, np.complex64)
        for j, (v, p) in enumerate(zip(V, pw)):
            # frames where this singer is loud (top 20 % of its frame energy): the leak path is measured there
            e = p.sum(0)
            sel = e >= np.percentile(e, 80)
            H = (X[:, sel] * np.conj(v[:, sel])).mean(1) / (p[:, sel].mean(1) + 1e-20)
            print(f"  {t} <- {voc[j]}: leak {10 * np.log10(np.mean(np.abs(H) ** 2) + 1e-20):+.1f} dB")
            L += H[:, None] * v
        lim = 10 ** (a.slack / 20) * np.abs(L)
        g = np.minimum(1.0, lim / (np.abs(R) + 1e-12)).astype(np.float32)
        y = istft(X - g * R, sr, nperseg=NFFT, noverlap=NFFT - HOP)[1][:n].astype(np.float32)
        y = np.pad(y, (0, n - len(y)))
        db = lambda s: 10 * np.log10(np.mean(s.astype(np.float64) ** 2) + 1e-20)
        print(f"  {t}: removed {db(x) - db(y):+.2f} dB of the original (network: {db(x) - db(nv):+.2f} dB); "
              f"kept {np.mean(g < 0.5) * 100:.0f} % of the network's removal bins at < half")
        write_wav(os.path.join(a.folder, f"{t}.{a.tag}.out.wav"), y, sr)
        vj = os.path.join(a.folder, "versions.json")
        d = json.load(open(vj)) if os.path.exists(vj) else {}
        d[a.tag] = (f"voice removed only where the vocal mics explain it (their measured leak, up to {a.slack:g} dB "
                    "above it): a sax or trumpet the voice network took for a voice stays")
        json.dump(dict(sorted(d.items())), open(vj, "w"), indent=1)


if __name__ == "__main__":
    main()
