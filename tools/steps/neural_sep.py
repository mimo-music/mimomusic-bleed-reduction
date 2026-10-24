# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Neural vocal separation of one mono stem.

Usage (with the separation venv, install.sh):
  work/venv-sep/bin/python tools/steps/neural_sep.py \
      in.wav out.wav [--model kj_melroformer] [--threads 6]

Runs a pretrained vocals model from ZFTurbo's Music-Source-Separation-
Training code (cloned to work/msst, weights in
work/models/<model>.ckpt/.yaml). The models work at
44.1 kHz stereo: the stem is resampled, duplicated to two channels, the
vocals estimate averaged back to mono and resampled to the stem's rate.
"""
import argparse
import os
import sys
import time
from math import gcd

import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from paths import WORK as BASE  # noqa: E402
from device import choose as choose_device  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from silence import squeeze, unsqueeze  # noqa: E402
sys.path.insert(0, os.path.join(BASE, "msst"))
from utils.settings import get_model_from_config  # noqa: E402
from utils.model_utils import demix  # noqa: E402

# the fastest device there is: NVIDIA or a checked AMD chip, Apple's, else the processor (device.py)
DEV = choose_device(torch)
MODELS = {"kj_melroformer": "mel_band_roformer", "viperx_bsroformer": "bs_roformer"}


def load(name="kj_melroformer"):
    """Returns (model, config, model type) on the CPU."""
    mt = MODELS[name]
    model, cfg = get_model_from_config(mt, os.path.join(BASE, "models", name + ".yaml"))
    sd = torch.load(os.path.join(BASE, "models", name + ".ckpt"), map_location="cpu", weights_only=False)
    model.load_state_dict(sd.get("state_dict", sd) if isinstance(sd, dict) else sd)
    model.to(DEV).eval()
    return model, cfg, mt


def separate(model, cfg, mt, x, sr):
    """Vocal estimate of the mono float array x at rate sr, same length and rate.
    Long digital silence is cut out first (silence.py: a window of mostly zeros made the
    network pass whole regions through)."""
    xs, pieces = squeeze(x, sr)
    if len(xs) < sr // 10:
        return np.zeros(len(x), np.float32)
    return unsqueeze(_separate(model, cfg, mt, xs, sr), pieces, len(x))


def _separate(model, cfg, mt, x, sr):
    msr = cfg.audio.sample_rate
    g = gcd(sr, msr)
    xm = resample_poly(x, msr // g, sr // g).astype(np.float32)
    with torch.no_grad():
        res = demix(cfg, model, torch.from_numpy(np.stack([xm, xm])), DEV, mt, pbar=False)
    v = res["vocals"] if isinstance(res, dict) else res[0]
    v = np.asarray(v).mean(axis=0)
    y = resample_poly(v, sr // g, msr // g)[:len(x)]
    return np.pad(y, (0, len(x) - len(y))).astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--model", default="kj_melroformer")
    ap.add_argument("--threads", type=int, default=6)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    model, cfg, mt = load(a.model)
    x, sr = sf.read(a.inp, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    t = time.time()
    y = separate(model, cfg, mt, x, sr)
    sf.write(a.out, y, sr, subtype="FLOAT")
    print(f"{a.model}: {len(x) / sr:.0f} s in {time.time() - t:.0f} s", file=sys.stderr)


if __name__ == "__main__":
    main()
