#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Instrument categories of one mono stem by a multi-stem network (for removing
other instruments from instrument mics).

Usage (with the separation venv):
  work/venv-sep/bin/python tools/steps/neural_stems.py in.wav out_prefix \
      [--model htdemucs_6s|scnet_xl_ihf] [--threads 6]

Writes <out_prefix>.<stem>.wav for every stem of the model (htdemucs_6s:
drums, bass, other, vocals, guitar, piano; scnet_xl_ihf: drums, bass, other,
vocals), mono, at the stem's rate and length. Same handling as
neural_sep.py (44.1 kHz stereo in, mono back); graphics card when there is
one, else the processor.
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
from resources import need_memory  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from silence import squeeze, unsqueeze  # noqa: E402
sys.path.insert(0, os.path.join(BASE, "msst"))
from utils.settings import get_model_from_config  # noqa: E402
from utils.model_utils import demix  # noqa: E402

# the fastest device there is: NVIDIA or a checked AMD chip, Apple's, else the processor (device.py)
DEV = choose_device(torch)
MODELS = {"htdemucs_6s": "htdemucs", "scnet_xl_ihf": "scnet"}
MEMORY = {"htdemucs_6s": 3.5e9, "scnet_xl_ihf": 7e9}     # rough peak on the processor, 3 min of audio


def load(name):
    mt = MODELS[name]
    model, cfg = get_model_from_config(mt, os.path.join(BASE, "models", name + ".yaml"))
    sd = torch.load(os.path.join(BASE, "models", name + ".ckpt"), map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "state" in sd:          # demucs release files
        sd = sd["state"]
    model.load_state_dict(sd.get("state_dict", sd) if isinstance(sd, dict) else sd)
    model.to(DEV).eval()
    return model, cfg, mt


def separate(model, cfg, mt, x, sr, shifts=1):
    """As _separate, with long digital silence cut out first (silence.py)."""
    xs, pieces = squeeze(x, sr)
    if len(xs) < sr // 10:
        return {k: np.zeros(len(x), np.float32) for k in cfg.training.instruments}
    return {k: unsqueeze(v, pieces, len(x)) for k, v in _separate(model, cfg, mt, xs, sr, shifts).items()}


def _separate(model, cfg, mt, x, sr, shifts=1):
    """{stem: mono float32 array} of x (mono, rate sr), same length and rate.
    shifts > 1: the average of that many runs on the input delayed by hop/shifts steps (htdemucs:
    hop 1024 at 44.1 kHz). One run leaves a buzz at the frame rate (43.07 Hz, 86.1 Hz) in quiet
    passages (heard as a "50 Hz" hum on a guitar mic, only after this step; measured: 15 / 19 dB
    over the input; 4 shifts: 4.7 / 2.9 dB = the input's)."""
    msr = cfg.audio.get("sample_rate", None) or cfg.training.samplerate   # demucs configs: training.samplerate
    g = gcd(sr, msr)
    xm = resample_poly(x, msr // g, sr // g).astype(np.float32)
    acc = {}
    for i in range(shifts):
        d = i * 1024 // shifts
        xs = np.concatenate([np.zeros(d, np.float32), xm])
        with torch.no_grad():
            res = demix(cfg, model, torch.from_numpy(np.stack([xs, xs])), DEV, mt, pbar=False)
        for k, v in res.items():
            v = np.asarray(v).mean(axis=0)[d:d + len(xm)] / shifts
            acc[k] = acc[k] + v if k in acc else v
    out = {}
    for k, v in acc.items():
        y = resample_poly(v, sr // g, msr // g)[:len(x)]
        out[k] = np.pad(y, (0, len(x) - len(y))).astype(np.float32)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("prefix")
    ap.add_argument("--model", default="htdemucs_6s", choices=sorted(MODELS))
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--shifts", type=int, default=4, help="runs on shifted input, averaged (1: the old single run)")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    need_memory(MEMORY[a.model] if DEV.type == "cpu" else 1.5e9, f"{a.model} {os.path.basename(a.inp)}")
    model, cfg, mt = load(a.model)
    x, sr = sf.read(a.inp, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    t = time.time()
    for k, y in separate(model, cfg, mt, x, sr, a.shifts).items():
        sf.write(f"{a.prefix}.{k}.wav", y, sr, subtype="FLOAT")
    print(f"{a.model} on {DEV}: {len(x) / sr:.0f} s in {time.time() - t:.0f} s ({a.shifts} shifts)", file=sys.stderr)


if __name__ == "__main__":
    main()
