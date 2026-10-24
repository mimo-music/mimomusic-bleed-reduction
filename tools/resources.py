# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Memory check before a big calculation (two heavy jobs at once can take a
computer with 16 GB down), and how many processor threads a render uses.

  from resources import need_memory
  need_memory(est_bytes, "instrument network, song 3")   # exits if it doesn't fit

Compares the estimate with MemAvailable (/proc/meminfo, Linux); allows up
to --share (default 70 %) of it. Elsewhere it only warns.
"""
import os
import sys


def available():
    """Bytes of memory available now, or None where unknown."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def need_memory(est, what, share=0.7):
    av = available()
    gb = lambda b: f"{b / 2 ** 30:.1f} GB"
    if av is None:
        print(f"{what}: needs about {gb(est)} (free memory unknown here)", file=sys.stderr)
        return
    print(f"{what}: needs about {gb(est)}, {gb(av)} available", file=sys.stderr)
    if est > share * av and not os.environ.get("BLEED_IGNORE_MEMORY"):
        sys.exit(f"{what}: not enough memory ({gb(est)} > {share * 100:.0f} % of {gb(av)} available). "
                 "Stop other jobs first, or set BLEED_IGNORE_MEMORY=1.")


def default_threads():
    """Processor threads for a render or an analysis: half of them (the network on the graphics
    card and every thread at once can be more than a power supply delivers: the computer
    switches itself off). BLEED_THREADS=N sets it."""
    try:
        n = int(os.environ.get("BLEED_THREADS", ""))
    except ValueError:
        n = 0
    try:
        cores = len(os.sched_getaffinity(0))
    except AttributeError:
        cores = os.cpu_count() or 2
    return max(1, n if n > 0 else cores // 2)


def limit_threads(n):
    """The steps started from here (numpy, scipy, torch) use at most n threads."""
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[k] = str(n)
