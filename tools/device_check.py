#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Is the graphics chip worth using for the networks? (install.sh runs it in work/venv-sep; see
device.py). Checks that the chip computes right (a small sum, then the instrument network on 10 s of
a test signal against the processor's result), times both, and writes the verdict to
work/device.<host>.json: "gpu" when the chip is right and faster, else "cpu" with the reason.

  work/venv-sep/bin/python tools/device_check.py [--seconds 10] [--timeout 600]

Every try runs in its own process with a time limit: a driver that hangs or crashes on the chip
fails that try, not the install. An AMD chip ROCm has no kernels for (the Radeon 880M is gfx1150) is
tried again with the kernels of a near one (HSA_OVERRIDE_GFX_VERSION); what worked is recorded and
device.py sets it. An NVIDIA card is used anyway (device.py); its timing is written for the record.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "steps"))
import device  # noqa: E402
from paths import work  # noqa: E402
from resources import default_threads  # noqa: E402

# the kernels to try instead, by the chip's family (gfx1150 / 1151 / 1103 ... -> gfx1100)
OVERRIDES = {"gfx11": "11.0.0", "gfx103": "10.3.0"}


def save(d):
    d.update(torch=torch.__version__, hip=getattr(torch.version, "hip", None),
             checked=datetime.datetime.now().isoformat(timespec="seconds"))
    os.makedirs(os.path.dirname(device.record_path()), exist_ok=True)
    json.dump(d, open(device.record_path(), "w"), indent=1)
    print(f"   verdict: {d['device']}" + (f" ({d['why']})" if d.get("why") else "") + f" -> {device.record_path()}")
    return d


def test_signal(sr, seconds):
    """Something like music: a few tones with overtones, noise bursts on a beat."""
    t = np.arange(int(sr * seconds)) / sr
    x = sum(0.1 * np.sin(2 * np.pi * f * k * t) / k for f in (110, 165, 220) for k in (1, 2, 3))
    beat = (np.mod(t, 0.5) < 0.03).astype(float) * np.random.default_rng(0).standard_normal(len(t)) * 0.3
    return (x + beat).astype(np.float32)


def run_net(dev, x, sr):
    import neural_stems as ns
    ns.DEV = dev
    model, cfg, mt = ns.load("htdemucs_6s")
    t = time.time()
    y = ns.separate(model, cfg, mt, x, sr, shifts=1)
    if dev.type == "cuda":
        torch.cuda.synchronize()
    return y, time.time() - t


def attempt(seconds):
    """One try, in the child process: {"ok", "why", "name", "arch", "gpu_s", "cpu_s", "error_db"}."""
    d = {"ok": False}
    if not torch.cuda.is_available():
        return dict(d, why="torch sees no graphics card or chip")
    gpu = torch.device("cuda")
    p = torch.cuda.get_device_properties(0)
    d.update(name=p.name, arch=getattr(p, "gcnArchName", ""), memory_gb=round(p.total_memory / 2 ** 30, 1))
    if not device.works(torch, gpu):
        return dict(d, why="the chip computes wrong or fails (small sum)")
    if not os.path.exists(work("models", "htdemucs_6s.ckpt")):
        return dict(d, why="no network weights yet to time it (./install.sh again)")
    sr = 44100
    x = test_signal(sr, seconds)
    try:
        run_net(gpu, x[:sr], sr)                    # the first run compiles the chip's kernels
        yg, tg = run_net(gpu, x, sr)
    except Exception as e:                          # noqa: BLE001
        return dict(d, why=f"the network fails on the chip: {str(e).splitlines()[0][:160]}")
    yc, tc = run_net(torch.device("cpu"), x, sr)
    err = max(float(np.abs(yg[k] - yc[k]).max()) for k in yc) / max(float(np.abs(yc[k]).max()) for k in yc)
    d.update(gpu_s=round(tg, 2), cpu_s=round(tc, 2), error_db=round(20 * np.log10(err + 1e-12), 1))
    print(f"   {seconds:.0f} s through the instrument network: chip {tg:.1f} s, processor {tc:.1f} s"
          f" ({tc / tg:.1f}x); difference {d['error_db']:.0f} dB", file=sys.stderr)
    if err > 1e-2:
        return dict(d, why=f"the chip's result differs from the processor's ({d['error_db']} dB)")
    if tg > 0.8 * tc:
        return dict(d, why=f"the chip is not faster ({tg:.1f} s vs {tc:.1f} s)")
    return dict(d, ok=True, why="")


def try_in_child(a, env):
    """attempt() in its own process with env added; a hang or a crash is a failed try."""
    e = dict(os.environ, BLEED_DEVICE="cpu", **env)   # cpu: the networks' own import leaves the chip alone
    cmd = [sys.executable, os.path.abspath(__file__), "--child", "--seconds", str(a.seconds)]
    if env:
        print("   again with " + " ".join(f"{k}={v}" for k, v in env.items()))
    try:
        p = subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=a.timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": f"no answer from the chip in {a.timeout} s"}
    for ln in p.stderr.splitlines():
        if ln.startswith("   ") or ln.startswith("device:"):
            print(ln)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        last = (p.stderr.strip().splitlines() or ["?"])[-1][:160]
        return {"ok": False, "why": f"the check stopped (exit {p.returncode}): {last}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--timeout", type=float, default=600.0, help="s for one try")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    torch.set_num_threads(default_threads())
    if a.child:
        print(json.dumps(attempt(a.seconds)))
        return
    rocm = device.is_rocm(torch)
    print(f"   torch {torch.__version__}" + (f", ROCm (HIP {torch.version.hip})" if rocm else ""))
    if rocm:
        print("   (on a laptop the chip also drives the screen: it may go black for a moment)")
    r = try_in_child(a, {})
    if r.get("name"):
        print(f"   chip: {r['name']}" + (f" ({r['arch']}, {r['memory_gb']} GB)" if r.get("arch") else ""))
    fam = next((v for k, v in OVERRIDES.items() if r.get("arch", "").startswith(k)), None)
    if rocm and not r["ok"] and fam and "HSA_OVERRIDE_GFX_VERSION" not in os.environ \
            and not any(w in r["why"] for w in ("not faster", "no network weights", "no answer")):
        env = {"HSA_OVERRIDE_GFX_VERSION": fam}
        r2 = try_in_child(a, env)
        if r2["ok"]:
            r = dict(r2, env=env)
        else:
            r["why"] += f"; with {fam} kernels: {r2['why']}"
    ok = r.pop("ok")
    if not ok and not rocm and r.get("name") and "no network weights" in r["why"]:
        ok = True                                   # NVIDIA: used anyway, only not timed
    r["device"] = "gpu" if ok else "cpu"
    save(r)


if __name__ == "__main__":
    main()
