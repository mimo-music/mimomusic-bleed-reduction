#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""A made-up multitrack recording to try the app on, and for its self-test: eight mics of a
small band, all synthetic (no recording of anyone), each picking up the others a little.

  python3 tools/make_demo.py <folder> [--seconds 40] [--rate 48000]

Writes <folder>/01 Kick.wav ... 08 Backing Vocal 2.wav (32-bit float, mono). The "voices" are
vowel-like harmonic tones with vibrato that come and go in phrases; the backing singers answer
the lead. Every mic gets the other sources 12-30 dB down, a few ms late and dulled (room sound),
which is what the app takes out again.
"""
import argparse
import os
import sys

import numpy as np
from scipy.signal import butter, lfilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wavio import write_wav  # noqa: E402

BPM = 100


def env(t, starts, length, attack=0.002, decay=0.15):
    """Sum of percussive envelopes at the start times."""
    e = np.zeros_like(t)
    for s in starts:
        d = t - s
        m = (d >= 0) & (d < length)
        e[m] += np.minimum(d[m] / attack, 1) * np.exp(-d[m] / decay)
    return e


def phrases(t, on, off, offset=0.0, fade=0.05):
    """1 in sung phrases (on s, then off s, from offset), soft edges."""
    p = np.mod(t - offset, on + off)
    g = (p < on) & (t >= offset)
    k = max(1, int(fade * (len(t) / t[-1])))
    return np.convolve(g.astype(float), np.ones(k) / k, mode="same")


def voice(t, notes, beat, vowel_hz, seed):
    """A sung line: harmonics of the note (vibrato 5.5 Hz), shaped by two vowel resonances."""
    rng = np.random.default_rng(seed)
    f0 = np.array(notes)[(t // (2 * beat)).astype(int) % len(notes)]
    f0 = f0 * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * t + rng.uniform(0, 6)))
    ph = 2 * np.pi * np.cumsum(f0) / (len(t) / t[-1])
    y = np.zeros_like(t)
    for k in range(1, 16):
        fk = f0 * k
        w = sum(np.exp(-((fk - v) / 120) ** 2) for v in vowel_hz) + 0.15 / k
        y += w * np.sin(k * ph)
    return y + 0.01 * rng.standard_normal(len(t))


def sources(sr, seconds):
    t = np.arange(int(sr * seconds)) / sr
    beat = 60 / BPM
    rng = np.random.default_rng(1)
    beats = np.arange(0, seconds, beat)
    kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-np.mod(t, beat) * 30)) * np.mod(t, beat)) * env(t, beats, beat, decay=0.12)
    conga_t = np.sort(np.concatenate([beats + beat * 0.5, beats[::2] + beat * 0.75]))
    conga = np.sin(2 * np.pi * 220 * t) * env(t, conga_t, 0.4, decay=0.08) \
        + 0.3 * rng.standard_normal(len(t)) * env(t, conga_t, 0.05, decay=0.01)
    roots = [55.0, 55.0 * 4 / 3, 55.0 * 3 / 2, 55.0 * 4 / 3]
    root = np.array(roots)[(t // (4 * beat)).astype(int) % 4]
    bass = np.tanh(2 * np.sin(2 * np.pi * np.cumsum(root) / sr)) * env(t, beats, beat, attack=0.01, decay=0.4)
    piano = sum(np.sin(2 * np.pi * np.cumsum(root * m) / sr) / (1 + i) for i, m in enumerate((4, 5, 6, 8)))
    piano *= env(t, beats[1::2], 2 * beat, decay=0.5)
    horn_line = phrases(t, 4 * beat, 4 * beat, offset=8 * beat)
    trumpet = sum(np.sin(2 * np.pi * k * np.cumsum(root * 8) / sr) / k for k in range(1, 8)) * horn_line
    lead = voice(t, [220, 247, 262, 247], beat, (700, 1200), 2) * phrases(t, 6 * beat, 2 * beat)
    coro = phrases(t, 2 * beat, 6 * beat, offset=6 * beat)
    back1 = voice(t, [330, 370, 392, 370], beat, (400, 2000), 3) * coro
    back2 = voice(t, [277, 294, 330, 294], beat, (500, 1700), 4) * coro
    return {"01 Kick": kick, "02 Conga": conga, "03 Bass": bass, "04 Piano": piano,
            "05 Trumpet": trumpet, "06 Lead Vocal": lead, "07 Backing Vocal 1": back1,
            "08 Backing Vocal 2": back2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--seconds", type=float, default=40.0)
    ap.add_argument("--rate", type=int, default=48000)
    a = ap.parse_args()
    sr = a.rate
    src = {k: v / (np.abs(v).max() + 1e-9) * 0.5 for k, v in sources(sr, a.seconds).items()}
    b, a_ = butter(2, 3000 / (sr / 2))          # the room: leaked sound is duller
    rng = np.random.default_rng(5)
    os.makedirs(a.folder, exist_ok=True)
    for name, own in src.items():
        y = own.copy()
        for other, x in src.items():
            if other == name:
                continue
            gain = 10 ** (-rng.uniform(12, 30) / 20)
            lag = int(sr * rng.uniform(0.002, 0.012))
            y[lag:] += gain * lfilter(b, a_, x)[:len(x) - lag]
        y += 10 ** (-70 / 20) * rng.standard_normal(len(y))
        write_wav(os.path.join(a.folder, f"{name}.wav"), (y * 0.7).astype(np.float32), sr)
    print(f"{len(src)} tracks, {a.seconds:.0f} s, {sr} Hz -> {a.folder}")


if __name__ == "__main__":
    main()
