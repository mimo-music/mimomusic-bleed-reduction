# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Long digital silence out before a network, back in after.

Tracks exported from a DAW are exact zeros wherever there is no region (coro
mics edited to the sung phrases: 80-84 % zeros, regions of 1.6 s every 4.3 s). The networks work on
windows of several seconds, and a window that is mostly exact zeros throws them
off for the sound in it as well: the vocal network passed whole regions through
untouched (removed -48 dB = only the resampling error) while the same regions,
with the zero gaps cut out, lost 13-26 dB of instruments, evenly.

squeeze() drops every run of at least min_gap s of exact zeros, the network runs
on what is left, unsqueeze() puts its output back in place (zeros where the
input was silent). Short zero runs (and single zero samples) stay.
"""
import numpy as np


def squeeze(x, sr, min_gap=0.25):
    """(the sound of x without its long zero runs, the kept [start, end) pieces)."""
    z = x == 0
    d = np.diff(np.r_[0, z.astype(np.int8), 0])
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    gaps = [(a, b) for a, b in zip(starts, ends) if b - a >= min_gap * sr]
    pieces, p = [], 0
    for a, b in gaps:
        if a > p:
            pieces.append((p, a))
        p = b
    if p < len(x):
        pieces.append((p, len(x)))
    if not pieces:
        return np.zeros(0, x.dtype), []
    return np.concatenate([x[a:b] for a, b in pieces]), pieces


def unsqueeze(y, pieces, n):
    """y (the network's output for squeeze()'s sound) back to length n."""
    out = np.zeros(n, np.float32)
    o = 0
    for a, b in pieces:
        out[a:b] = y[o:o + b - a]
        o += b - a
    return out
