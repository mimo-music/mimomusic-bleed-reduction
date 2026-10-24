# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Where the networks run.

An NVIDIA card (torch's CUDA build), an AMD chip (torch's ROCm build: the same torch.cuda calls), an
Apple chip, else the processor. An AMD chip only when install.sh's check (tools/device_check.py)
found it computing right and faster than the processor: its verdict in work/device.<host>.json;
and every run checks it once more on a small sum first (a driver update can break it), else the
processor, with a line why. NVIDIA and Apple as before (no check).
A chip ROCm has no kernels for (the 880M is gfx1150) may run with the kernels of a near one
(HSA_OVERRIDE_GFX_VERSION=11.0.0): the check tries that too and records it ("env"); choose() sets it
before torch first asks for the chip.
BLEED_DEVICE=cpu: always the processor; BLEED_DEVICE=gpu: the AMD chip without the install check.
"""
import json
import os
import socket
import sys

from paths import work


def record_path():
    return work(f"device.{socket.gethostname()}.json")


def record():
    """The install check's verdict: {"device": "gpu"|"cpu", "why", "name", "gpu_s", "cpu_s", ...}."""
    try:
        return json.load(open(record_path()))
    except (OSError, ValueError):
        return {}


def is_rocm(torch):
    return getattr(torch.version, "hip", None) is not None


def works(torch, dev):
    """A small convolution and product on dev, against the processor's result."""
    try:
        g = torch.Generator().manual_seed(0)
        x = torch.randn(2, 64, 4096, generator=g)
        w = torch.randn(64, 64, 9, generator=g)
        ref = torch.nn.functional.conv1d(x, w, padding=4)
        ref = ref @ ref.transpose(1, 2)
        y = torch.nn.functional.conv1d(x.to(dev), w.to(dev), padding=4)
        y = (y @ y.transpose(1, 2)).cpu()
        err = float((y - ref).abs().max() / ref.abs().max())
        if not bool(torch.isfinite(y).all()) or err > 1e-3:
            print(f"device: {dev} computes wrong (error {err:.1e})", file=sys.stderr)
            return False
        return True
    except Exception as e:      # noqa: BLE001 (any driver or kernel error: not usable)
        print(f"device: {dev} failed: {str(e).splitlines()[0][:200]}", file=sys.stderr)
        return False


def choose(torch):
    """The torch.device the networks use."""
    force = os.environ.get("BLEED_DEVICE", "")
    cpu = torch.device("cpu")
    if force == "cpu":
        return cpu
    r = record()
    if r.get("device") == "gpu":
        for k, v in r.get("env", {}).items():   # read by ROCm when torch first asks for the chip
            os.environ.setdefault(k, v)
    if torch.cuda.is_available():
        dev = torch.device("cuda")
        if not is_rocm(torch):
            return dev
        if force != "gpu" and r.get("device") != "gpu":
            print("device: the AMD chip " + (f"is not used ({r['why']})" if r.get("why") else
                                             "has not been checked yet (./install.sh)") + ": the processor",
                  file=sys.stderr)
            return cpu
        if works(torch, dev):
            return dev
        print("device: the AMD chip fails its check: the processor (./install.sh checks it again)", file=sys.stderr)
        return cpu
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return cpu
