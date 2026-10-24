# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Ways to use a neural vocal estimate.

Usage:
  python3 tools/steps/neural_mix.py orig.wav vocals.wav out_prefix \
      [--base stage1.wav] [--keep -12,-18] [--floor -12,-18]

From the original x (or the stage-1 output, --base) and the neural vocal
estimate v, writes for every value:
  <prefix>.keepNN.wav   v + g * (x - v): the estimate with the rest turned
                        down by NN dB instead of removed (masks artifacts,
                        nothing of the voice is ever lost entirely);
  <prefix>.maskNN.wav   x filtered by a soft mask from v (STFT 4096/1024,
                        mask = |V|^2 / (|V|^2 + |X-V|^2), smoothed over
                        3 frames x 3 bins, never below NN dB): the phase and
                        fine structure stay the original's, only the gain
                        per bin comes from the network.
With --mode vocal|novocal it writes listener files instead (A/B tool):
  vocal:   <prefix>.neural.out.wav (v)
  novocal: instrument mics, the voice is the bleed: <prefix>.novocal.out.wav (x - v)
  (the keep versions, rest / voice only turned down 12 dB, rated below both
  in listening tests)
"""
import argparse

import numpy as np
from scipy.ndimage import uniform_filter
from scipy.signal import stft, istft

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wavio import read_wav, write_wav  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("orig")
    ap.add_argument("vocals")
    ap.add_argument("prefix")
    ap.add_argument("--base")
    ap.add_argument("--keep", default="-12,-18")
    ap.add_argument("--floor", default="-12,-18")
    ap.add_argument("--mode", choices=["vocal", "novocal"])
    a = ap.parse_args()
    x, sr = read_wav(a.base or a.orig)
    x = x[:, 0].astype(np.float64)
    v = read_wav(a.vocals)[0][:, 0].astype(np.float64)[:len(x)]
    x = x[:len(v)]
    if a.mode:
        outs = {"neural": v} if a.mode == "vocal" else {"novocal": x - v}
        for tag, y in outs.items():
            write_wav(f"{a.prefix}.{tag}.out.wav", y.astype(np.float32), sr)
        return
    for k in (float(s) for s in a.keep.split(",") if s):
        write_wav(f"{a.prefix}.keep{int(-k)}.wav", (v + 10 ** (k / 20) * (x - v)).astype(np.float32), sr)
    n = 4096 * sr // 48000
    _, _, X = stft(x, nperseg=n, noverlap=n * 3 // 4)
    _, _, V = stft(v, nperseg=n, noverlap=n * 3 // 4)
    pv = uniform_filter(np.abs(V) ** 2, 3)
    pr = uniform_filter(np.abs(X - V) ** 2, 3)
    m0 = pv / (pv + pr + 1e-20)
    for f in (float(s) for s in a.floor.split(",") if s):
        g = np.maximum(m0, 10 ** (f / 20))
        _, y = istft(X * g, nperseg=n, noverlap=n * 3 // 4)
        write_wav(f"{a.prefix}.mask{int(-f)}.wav", y[:len(x)].astype(np.float32), sr)


if __name__ == "__main__":
    main()
