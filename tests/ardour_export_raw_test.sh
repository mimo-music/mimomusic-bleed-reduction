#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH
# tools/export_raw_stems.sh in real Ardour (ardour9-lua, dummy backend):
#   bash tests/ardour_export_raw_test.sh
# Builds a session (tests/ardour_export_raw_setup.lua), exports it, checks: one file per track
# channel, the take as edited (moved, region gain) and nothing of the track's processing
# (plugin, fader, mute), the session's sample format; the session file and folder unchanged.
cd "$(dirname "$0")/.." || exit 1
T="${TMPDIR:-/tmp}/bleed_reduction_export_raw_test"
rm -rf "$T" && mkdir -p "$T"
BLEED_TEST_DIR="$T/session" ardour9-lua tests/ardour_export_raw_setup.lua 2>&1 | grep -E "^(setup|range)"
before="$(cd "$T/session" && find . -type f ! -name '*.bak' ! -name '*.history' -exec md5sum {} + | sort)"
sh tools/export_raw_stems.sh "$T/session" "$T/stems" || { echo "FAIL export"; exit 1; }
after="$(cd "$T/session" && find . -type f ! -name '*.bak' ! -name '*.history' -exec md5sum {} + | sort)"
[ "$before" = "$after" ] && echo "PASS session unchanged (files and contents)" || { echo "FAIL session changed:"; diff <(echo "$before") <(echo "$after"); }
PY=python3; [ -x work/venv-sep/bin/python ] && PY=work/venv-sep/bin/python
"$PY" - "$T" <<'EOF'
import sys, glob, os
import numpy as np, soundfile as sf
T = sys.argv[1]
fails = 0
def check(ok, what):
    global fails
    print(("PASS " if ok else "FAIL ") + what)
    fails += not ok
files = sorted(os.path.basename(p) for p in glob.glob(T + "/stems/*.wav"))
check(files == ["01 Mono.wav", "02 Stereo-L.wav", "02 Stereo-R.wav"], f"files: {files}")
src = sf.read(glob.glob(T + "/session/interchange/*/audiofiles/Mono*.wav")[0], dtype="float64")[0]
info = sf.info(T + "/stems/01 Mono.wav")
y = sf.read(T + "/stems/01 Mono.wav", dtype="float64")[0]
check(info.subtype == "FLOAT" and info.samplerate == 48000, f"the session's format: {info.format} {info.subtype} {info.samplerate} Hz")
n = min(len(y) - 48000, len(src))
F = 64     # Ardour's default region fades at the take's edges (part of the edit)
err = np.max(np.abs(y[48000 + F:48000 + n - F] - 0.5 * src[F:n - F]))
check(np.max(np.abs(y[:48000])) == 0 and err < 1e-6,
      f"the take as edited (moved to 1 s, region gain 0.5, its fades), no plugin/fader/mute: max error {err:.1e}, level {20*np.log10(np.std(y[48000:]) + 1e-12):.1f} dBFS")
l = sf.read(T + "/stems/02 Stereo-L.wav")[0]; r = sf.read(T + "/stems/02 Stereo-R.wav")[0]
check(len(l) == len(y) == len(r) and np.std(l) > 0.01 and np.std(r) > 0.01, f"stereo: two channels with signal, all {len(y)} samples long (the session range)")
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
EOF
