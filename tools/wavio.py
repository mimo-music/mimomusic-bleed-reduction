# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Minimal WAV reader/writer (PCM 16/24/32 and float 32/64), numpy only."""
import json
import os
import struct
import time
import numpy as np


def read_wav(path):
    """Returns (samples[frames, channels] as float64, sample_rate)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a RIFF/WAVE file")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
            if fmt[0] == 0xFFFE:  # WAVE_FORMAT_EXTENSIBLE: real tag in the subformat GUID
                fmt = (struct.unpack("<H", body[24:26])[0],) + fmt[1:]
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if fmt is None or raw is None:
        raise ValueError(f"{path}: missing fmt or data chunk")
    tag, ch, sr, _, _, bits = fmt
    if tag == 3:
        x = np.frombuffer(raw, dtype="<f4" if bits == 32 else "<f8").astype(np.float64)
    elif tag == 1 and bits == 16:
        x = np.frombuffer(raw, dtype="<i2") / 32768.0
    elif tag == 1 and bits == 24:
        b = np.frombuffer(raw[:len(raw) // 3 * 3], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(v >= 1 << 23, v - (1 << 24), v) / float(1 << 23)
    elif tag == 1 and bits == 32:
        x = np.frombuffer(raw, dtype="<i4") / 2147483648.0
    else:
        raise ValueError(f"{path}: unsupported format tag {tag}, {bits} bit")
    return x[: len(x) // ch * ch].reshape(-1, ch), sr


def write_wav(path, x, sr):
    """Writes float32 WAV; x is [frames] or [frames, channels].
    An identical file is left as it is (its date stays: the sync doesn't send
    it again). A listening version (*.out.wav) that really changed is noted
    in made.json next to it: the A/B listener shows it again even where it
    was rated before. Returns whether it wrote."""
    x = np.asarray(x, dtype="<f4")
    if x.ndim == 1:
        x = x[:, None]
    ch = x.shape[1]
    raw = x.tobytes()
    fmt = struct.pack("<HHIIHH", 3, ch, sr, sr * ch * 4, ch * 4, 32)
    data = (b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(raw)) + b"WAVE"
            + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(raw)) + raw)
    if os.path.exists(path) and os.path.getsize(path) == len(data):
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    with open(path, "wb") as f:
        f.write(data)
    if path.endswith(".out.wav"):
        note_made(path)
    return True


def note_made(path):
    """Notes in made.json (same folder) that this listening file changed now."""
    m = os.path.join(os.path.dirname(path) or ".", "made.json")
    try:
        d = json.load(open(m))
    except (OSError, ValueError):
        d = {}
    d[os.path.basename(path)] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(m, "w") as f:
        json.dump(dict(sorted(d.items())), f, indent=1)
