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


def bext_chunk(time_ref, description=""):
    """A BWF bext chunk: where the file starts on the timeline (in samples). Ardour reads it on
    import: "Move to Original Position" puts the region there."""
    now = time.localtime()
    body = (description.encode("utf-8")[:256].ljust(256, b"\0") + b"Bleed Reduction".ljust(32, b"\0")
            + b"\0" * 32 + time.strftime("%Y-%m-%d", now).encode() + time.strftime("%H:%M:%S", now).encode()
            + struct.pack("<QH", int(time_ref), 1) + b"\0" * (64 + 10 + 180))
    return b"bext" + struct.pack("<I", len(body)) + body


def copy_with_bext(src, dst, time_ref, description=""):
    """src (a RIFF WAV) to dst with a bext chunk saying it starts at sample time_ref; the samples
    as they are. dst must not exist (never written over)."""
    with open(src, "rb") as f:
        if f.read(12)[8:12] != b"WAVE":
            raise ValueError(f"{src}: not a RIFF/WAVE file")
        fmt, data = None, None
        while data is None:
            h = f.read(8)
            if len(h) < 8:
                raise ValueError(f"{src}: no data chunk")
            cid, n = h[:4], struct.unpack("<I", h[4:])[0]
            if cid == b"fmt ":
                fmt = f.read(n)
                f.seek(n & 1, 1)
            elif cid == b"data":
                data = (f.tell(), min(n, os.path.getsize(src) - f.tell()))
            else:
                f.seek(n + (n & 1), 1)
        if fmt is None:
            raise ValueError(f"{src}: no fmt chunk")
        bext = bext_chunk(time_ref, description)
        fmt_chunk = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"\0" * (len(fmt) & 1)
        n = data[1]
        with open(dst, "xb") as o:
            o.write(b"RIFF" + struct.pack("<I", 4 + len(fmt_chunk) + len(bext) + 8 + n + (n & 1)) + b"WAVE"
                    + fmt_chunk + bext + b"data" + struct.pack("<I", n))
            f.seek(data[0])
            left = n
            while left:
                b = f.read(min(left, 1 << 24))
                if not b:
                    raise ValueError(f"{src}: shorter than its header says")
                o.write(b)
                left -= len(b)
            if n & 1:
                o.write(b"\0")
