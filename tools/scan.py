# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Spike 2: find which stem leaks into which, and with what delay.

Usage:
  python3 tools/scan.py <folder> [--windows 240] [--win-s 1.5] [--out DIR]

Reads only sampled windows from each file (memory-mapped, so a 2.5 h stem
costs nothing to open), so it works on whole concerts. Files that are
still being copied (shorter than their header says) are skipped.

For every ordered pair (ref -> target), averaged over the windows where
both play:
  - lag: GCC-PHAT peak of the averaged cross-spectrum (ms, positive = the
    target hears it later, i.e. the ref is nearer the source);
  - peak: GCC-PHAT peak height (0..1, how clean the delay is);
  - coupling: share of the target's power that a linear filter from the
    ref explains, sum |Sxy|^2/Sxx / sum Syy, in dB (0 dB = the target is
    entirely the ref; asymmetric: the ref's own mic explains its source in
    the target, not the other way around).
Writes scan.csv, scan.json and a heatmap (scan.png) to --out.
"""
import argparse
import json
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
from paths import work

N = 8192           # FFT frame: 171 ms at 48 kHz, lags up to +-50 ms are fine
MAX_LAG_S = 0.05   # 50 ms = 17 m


def open_wav(path):
    """Memory-maps a PCM/float WAV. Returns (raw uint8/float memmap, info) or None."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        hdr = f.read(12)
        if hdr[:4] != b"RIFF" or hdr[8:12] != b"WAVE":
            return None
        pos, fmt, name = 12, None, None
        while True:
            f.seek(pos)
            ch = f.read(8)
            if len(ch) < 8:
                return None
            cid, n = ch[:4], struct.unpack("<I", ch[4:])[0]
            if cid == b"fmt ":
                body = f.read(n)
                fmt = list(struct.unpack("<HHIIHH", body[:16]))
                if fmt[0] == 0xFFFE:
                    fmt[0] = struct.unpack("<H", body[24:26])[0]
            elif cid == b"LIST":
                body = f.read(n)
                i = body.find(b"INAM")
                if i >= 0:
                    ln = struct.unpack("<I", body[i + 4:i + 8])[0]
                    name = body[i + 8:i + 8 + ln].split(b"\0")[0].decode("latin-1")
            elif cid == b"data":
                data_off, data_len = pos + 8, n
                break
            pos += 8 + n + (n & 1)
    tag, chans, sr, _, align, bits = fmt
    complete = size >= data_off + data_len
    frames = min(data_len, size - data_off) // align
    mm = np.memmap(path, dtype=np.uint8, mode="r", offset=data_off, shape=(frames * align,))
    return mm, dict(tag=tag, chans=chans, sr=sr, align=align, bits=bits,
                    frames=frames, complete=complete, name=name)


def stem_label(fn, info):
    """The file name without extension: names inside the files (INAM)
    are not used, the file name is what the user goes by."""
    return os.path.splitext(fn)[0]


def stem_file(folder, label):
    """Inverse of stem_label: the file in folder for a label."""
    for fn in os.listdir(folder):
        if os.path.splitext(fn)[0] in (label, label.split("_")[0]):
            return os.path.join(folder, fn)
    raise FileNotFoundError(label)


def read_frames(mm, info, start, count):
    """Channel 0 of frames [start, start+count) as float32."""
    a, b = info["align"], info["bits"] // 8
    raw = np.asarray(mm[start * a:(start + count) * a]).reshape(-1, a)[:, :b]
    if info["tag"] == 3:
        return raw.copy().view("<f4" if b == 4 else "<f8")[:, 0].astype(np.float32)
    if b == 3:
        v = raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8) | (raw[:, 2].astype(np.int32) << 16)
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        return (v / float(1 << 23)).astype(np.float32)
    if b == 2:
        return (raw.copy().view("<i2")[:, 0] / 32768.0).astype(np.float32)
    return (raw.copy().view("<i4")[:, 0] / 2147483648.0).astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--windows", type=int, default=240)
    ap.add_argument("--win-s", type=float, default=1.5)
    ap.add_argument("--out")
    ap.add_argument("--skip", default="MAIN", help="comma-separated name parts to leave out (mix buses)")
    args = ap.parse_args()
    out = args.out or work("scan", os.path.basename(os.path.normpath(args.folder)))
    os.makedirs(out, exist_ok=True)

    skip = [s.upper() for s in args.skip.split(",") if s]
    stems = []
    for fn in sorted(os.listdir(args.folder)):
        if not fn.lower().endswith(".wav") or any(s in fn.upper() for s in skip):
            continue
        r = open_wav(os.path.join(args.folder, fn))
        if r is None:
            print(f"skip {fn}: not readable", file=sys.stderr)
            continue
        if not r[1]["complete"]:
            print(f"skip {fn}: incomplete (still copying?)", file=sys.stderr)
            continue
        stems.append((stem_label(fn, r[1]), *r))
    if len(stems) < 2:
        sys.exit("need at least two complete stems")
    sr = stems[0][2]["sr"]
    frames = min(s[2]["frames"] for s in stems)
    names = [s[0] for s in stems]
    K = len(stems)
    print(f"{K} stems, {frames / sr / 60:.1f} min, {sr} Hz")

    win = int(args.win_s * sr)
    hop = N // 2
    nfr = (win - N) // hop + 1
    w = np.hanning(N).astype(np.float32)
    starts = np.linspace(0, frames - win, args.windows).astype(np.int64)
    idx = np.arange(nfr)[:, None] * hop + np.arange(N)[None, :]
    nb = N // 2 + 1

    def window_spectra(st):
        X = np.empty((K, nfr, nb), np.complex64)
        for k, (_, mm, info) in enumerate(stems):
            X[k] = np.fft.rfft(read_frames(mm, info, int(st), win)[idx] * w, axis=1)
        return X

    # pass 1: frame levels -> per stem a playing level (p90), a noise floor
    # (p5), and which frames are "own source silent" / "active"
    lev = np.empty((K, len(starts), nfr))
    for wi, st in enumerate(starts):
        for k, (_, mm, info) in enumerate(stems):
            x = read_frames(mm, info, int(st), win)[idx]
            lev[k, wi] = 10 * np.log10(np.mean(x ** 2, axis=1) + 1e-20)
    # digital silence (exact zeros: before/after the show, muted inputs)
    # doesn't count for the floor
    live = [l[l > -120] for l in lev.reshape(K, -1)]
    p90 = np.array([np.percentile(l, 90) if len(l) else -200.0 for l in live])
    p5 = np.array([np.percentile(l, 5) if len(l) else -200.0 for l in live])
    zero_share = np.mean(lev.reshape(K, -1) <= -120, axis=1)
    unused = (p90 < -60) | (p90 - p5 < 6)
    for k in np.flatnonzero(unused):
        print(f"unused/noise-only: {names[k]} (p90 {p90[k]:.0f} dBFS, range {p90[k] - p5[k]:.0f} dB)")
    active = (lev > p90[:, None, None] - 12) & ~unused[:, None, None]
    # own source silent: well below its playing level but above the floor
    # (dead air between songs, where everything is quiet, says nothing)
    silent = (lev < p90[:, None, None] - 20) & (lev > p5[:, None, None] + 3) & ~unused[:, None, None]
    use = ~unused[:, None, None] & (lev > p5[:, None, None] + 3)

    # pass 2: cross-spectra as batched matrix products per bin
    #   all:    both stems above their floor
    #   silent: ref active, target's own source silent -> the leak ref -> target
    acc = {m: [np.zeros((nb, K, K), np.complex128), np.zeros((nb, K, K)), np.zeros((nb, K, K)), np.zeros((K, K))]
           for m in ("all", "silent")}
    for wi, st in enumerate(starts):
        X = window_spectra(st).transpose(2, 0, 1)         # (nb, K, F)
        P = (np.abs(X) ** 2).astype(np.float32)
        for m, (ri, tj) in (("all", (use[:, wi], use[:, wi])), ("silent", (active[:, wi], silent[:, wi]))):
            ri, tj = ri.astype(np.float32), tj.astype(np.float32)   # (K, F)
            Sxy, Sxx, Syy, cnt = acc[m]
            Sxy += np.conj(X * ri) @ (X * tj).transpose(0, 2, 1)
            Sxx += (P * ri) @ tj.T
            Syy += ri @ (P * tj).transpose(0, 2, 1)
            cnt += ri @ tj.T
        if (wi + 1) % 40 == 0:
            print(f"  window {wi + 1}/{len(starts)}", flush=True)

    res = {m: analyse(*acc[m], sr, K) for m in acc}
    used = acc["all"][3]
    lag, peak, coup = res["all"]
    slag, speak, scoup = res["silent"]
    sused = acc["silent"][3]
    sel = sused < 20     # too few frames for a silent-target estimate
    slag[sel] = speak[sel] = scoup[sel] = np.nan
    rms_all = 10 ** (p90 / 20)

    with open(os.path.join(out, "scan.csv"), "w") as fh:
        fh.write("ref,target,coupling_db,lag_ms,dist_m,peak,frames,"
                 "silent_coupling_db,silent_lag_ms,silent_peak,silent_frames\n")
        for i in range(K):
            for j in range(K):
                if i != j and used[i, j]:
                    fh.write(f"{names[i]},{names[j]},{coup[i, j]:.1f},{lag[i, j]:.2f},"
                             f"{lag[i, j] * 0.343:.2f},{peak[i, j]:.2f},{used[i, j]:.0f},"
                             f"{scoup[i, j]:.1f},{slag[i, j]:.2f},{speak[i, j]:.2f},{sused[i, j]:.0f}\n")
    json.dump(dict(names=names, inam=[s[2]["name"] for s in stems], sr=sr,
                   coupling_db=np.nan_to_num(coup, nan=-99).round(1).tolist(),
                   lag_ms=np.nan_to_num(lag).round(2).tolist(),
                   peak=np.nan_to_num(peak).round(2).tolist(),
                   silent_coupling_db=np.nan_to_num(scoup, nan=-99).round(1).tolist(),
                   silent_lag_ms=np.nan_to_num(slag).round(2).tolist(),
                   silent_peak=np.nan_to_num(speak).round(2).tolist(),
                   level_p90_db=p90.round(1).tolist(), floor_p5_db=p5.round(1).tolist(),
                   unused=unused.tolist(), zero_share=zero_share.round(3).tolist(),
                   window_starts_s=(starts / sr).round(2).tolist(),
                   window_level_db=np.median(lev, axis=2).round(1).tolist()),
              open(os.path.join(out, "scan.json"), "w"), indent=1)
    heatmap(os.path.join(out, "scan.png"), names, coup, lag, peak)
    # per pair: the stem that hears it first is the source side; report
    # how much of the later stem the earlier one explains (the leak)
    pairs = []
    for i in range(K):
        for j in range(i + 1, K):
            if np.isnan(lag[i, j]):
                continue
            a, b = (i, j) if lag[i, j] >= 0 else (j, i)
            pairs.append((coup[a, b], a, b))
    pairs.sort(reverse=True)
    print(f"{'source side':>24} -> {'leaks into':<24} leak dB  lag ms    ~m  peak")
    for c, a, b in pairs[:40]:
        print(f"{names[a]:>24} -> {names[b]:<24} {c:6.1f}  {lag[a, b]:6.2f} {lag[a, b] * 0.343:5.2f}  {peak[a, b]:.2f}")
    # per direction, measured where the target's own source is silent:
    # what remains there is bleed, so both directions of a pair show
    sl = sorted(((scoup[i, j], i, j) for i in range(K) for j in range(K)
                 if i != j and not np.isnan(scoup[i, j]) and speak[i, j] > 0.15), reverse=True)
    print(f"\nwhile the target's own source is silent (peak > 0.15):")
    print(f"{'ref':>24} -> {'target':<24} leak dB  lag ms    ~m  peak  frames")
    for c, i, j in sl[:40]:
        print(f"{names[i]:>24} -> {names[j]:<24} {c:6.1f}  {slag[i, j]:6.2f} {slag[i, j] * 0.343:5.2f}  "
              f"{speak[i, j]:.2f}  {sused[i, j]:.0f}")
    # stems nothing leaks into with a clean delay: DI candidates
    clean = [names[b] for b in range(K)
             if not any(bb == b and c > -20 and peak[a, bb] > 0.15 for c, a, bb in pairs)]
    print("hear no other stem (DI / clean reference candidates):", ", ".join(clean) or "-")
    print(f"wrote {out}/scan.csv, scan.json, scan.png")


def analyse(Sxy, Sxx, Syy, cnt, sr, K):
    """Lag (ms), GCC peak and coupling (dB) per ordered pair (ref i, target j)."""
    maxlag = int(MAX_LAG_S * sr)
    lag = np.full((K, K), np.nan)
    peak = np.full((K, K), np.nan)
    coup = np.full((K, K), np.nan)
    f = np.fft.rfftfreq(N, 1 / sr)
    band = (f > 60) & (f < 12000)
    for i in range(K):
        for j in range(K):
            if i == j or cnt[i, j] == 0:
                continue
            c, sx, sy = Sxy[:, i, j], Sxx[:, i, j], Syy[:, i, j]
            coh = np.abs(c) ** 2 / (sx * sy + 1e-30)
            # PHAT weighted by coherence: bins where the two don't share a
            # source (or only share the beat) add noise, not a delay
            wgt = np.where(band, coh, 0)
            g = np.fft.irfft(wgt * c / (np.abs(c) + 1e-30), N)
            g = np.concatenate([g[-maxlag:], g[:maxlag + 1]])
            m = int(np.argmax(np.abs(g)))
            lag[i, j] = (m - maxlag) / sr * 1000
            peak[i, j] = abs(g[m]) / (wgt.sum() + 1e-30) * N / 2  # ~1 for a pure delay
            expl = np.sum(np.abs(c[band]) ** 2 / (sx[band] + 1e-30))
            coup[i, j] = 10 * np.log10(expl / (np.sum(sy[band]) + 1e-30) + 1e-12)
    return lag, peak, coup


def heatmap(path, names, coup, lag, peak):
    K = len(names)
    cell, left, top = 46, 130, 130
    img = Image.new("RGB", (left + K * cell + 10, top + K * cell + 10), "white")
    d = ImageDraw.Draw(img)
    for k, n in enumerate(names):
        d.text((4, top + k * cell + cell // 2 - 5), n[:18], fill="black")
        tx = Image.new("RGB", (top - 4, 14), "white")
        ImageDraw.Draw(tx).text((2, 1), n[:18], fill="black")
        img.paste(tx.rotate(90, expand=True), (left + k * cell + cell // 2 - 7, 2))
    d.text((4, 4), "row = ref\ncol = target\ncoupling dB\nlag ms", fill="gray")
    for i in range(K):
        for j in range(K):
            x0, y0 = left + j * cell, top + i * cell
            if i == j or np.isnan(coup[i, j]):
                d.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], fill=(230, 230, 230))
                continue
            t = float(np.clip((coup[i, j] + 30) / 30, 0, 1))  # -30..0 dB
            col = (int(255 - 40 * t), int(255 - 200 * t), int(255 - 230 * t))
            d.rectangle([x0, y0, x0 + cell - 1, y0 + cell - 1], fill=col, outline=(200, 200, 200))
            d.text((x0 + 3, y0 + 6), f"{coup[i, j]:.0f}", fill="black")
            d.text((x0 + 3, y0 + 24), f"{lag[i, j]:.1f}", fill="black" if peak[i, j] > 0.1 else "gray")
    img.save(path)


if __name__ == "__main__":
    main()
