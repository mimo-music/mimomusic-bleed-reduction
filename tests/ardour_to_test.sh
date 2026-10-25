#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH
# tools/to_ardour.py in real Ardour (ardour9-lua, dummy backend), the whole way:
#   bash tests/ardour_to_test.sh
# A test session (tests/ardour_export_raw_setup.lua) -> a project from it -> a stand-in render
# (the stems at a quarter of their level, so it is told apart) -> into Ardour: "Mono Cleaned"
# and "Stereo Cleaned" made below the originals (plugins, fader, outputs copied; the originals
# muted), at the recording's start -> again with another render: the same tracks, the regions
# replaced (one renamed "Stereo denoised" as made by hand, and the project forgetting which
# tracks it made: found by their names) -> re-import: the Cleaned tracks are not exported, the settings stay. The
# recordings are never written to. In /tmp; removed at the end.
cd "$(dirname "$0")/.." || exit 1
T="$(mktemp -d "${TMPDIR:-/tmp}/bleed-to-ardour.XXXXXX")" || exit 1
trap 'rm -rf "$T"' EXIT
S="$T/session"
BLEED_TEST_DIR="$S" ardour9-lua tests/ardour_export_raw_setup.lua 2>&1 | grep -E "^setup"
recs() { (cd "$S/interchange" && find . -type f -name '*.wav' ! -name '*Cleaned*' ! -name '*denoised*' -exec md5sum {} + | sort); }
before="$(recs)"
python3 tools/project.py new "$T/project" --name test --ardour "$S" | tail -1 || exit 1
PY=python3; [ -x work/venv-sep/bin/python ] && PY=work/venv-sep/bin/python

render() {   # a stand-in for tools/render.py: every stem times $1, with render.json
  "$PY" - "$T/project" "$1" <<'EOF'
import json, os, sys
sys.path.insert(0, "tools")
from render import WavStream
from scan import open_wav, read_frames
from ardour_session import session_start
proj, g = sys.argv[1], float(sys.argv[2])
pj = json.load(open(os.path.join(proj, "project.json")))
os.makedirs(os.path.join(proj, "render"), exist_ok=True)
for n, t in pj["tracks"].items():
    mm, info = open_wav(t["file"])
    w = WavStream(os.path.join(proj, "render", n + ".wav"), info["sr"], time_ref=session_start(pj))
    w.write(read_frames(mm, info, 0, info["frames"]) * g)
    w.close()
json.dump({"start": 0, "end": info["frames"] / info["sr"], "rate": info["sr"], "finished": "now",
           "chains": {n: "novocal_guided_cat" for n in pj["tracks"]}}, open(os.path.join(proj, "render", "render.json"), "w"))
EOF
}
check() {
  BLEED_TEST_DIR="$S" BLEED_TEST_NAME=rawtest ardour9-lua tests/ardour_to_check.lua 2>/dev/null | grep -E "^(TRACK|REGION|DONE|ERROR)" > "$T/check.$1"
}

render 0.25
python3 tools/to_ardour.py "$T/project" | sed 's/^/  /' || exit 1
check 1
render 0.125
# as if made by hand: "Stereo Cleaned" renamed "Stereo denoised", and the project forgets which
# tracks it made: both are found by their names, the hand-named one keeps its name
"$PY" -c '
import json, re, sys
s = open(sys.argv[1]).read()
s, n = re.subn(r"(<Route [^>]*name=.)Stereo Cleaned(?=.)", r"\1Stereo denoised", s)
assert n == 1
open(sys.argv[1], "w").write(s)
pj = json.load(open(sys.argv[2]))
pj["ardour"]["cleaned"] = {}
json.dump(pj, open(sys.argv[2], "w"), indent=1)
' "$S/rawtest.ardour" "$T/project/project.json" || exit 1
python3 tools/to_ardour.py "$T/project" | tail -1 | sed 's/^/  /' || exit 1
check 2
python3 tools/project.py reimport "$T/project" > "$T/reimport.out" 2>&1; echo "  re-import: exit $?"
after="$(recs)"

"$PY" - "$T" "$([ "$before" = "$after" ] && echo same || echo changed)" <<'EOF'
import glob, json, os, re, sys
import numpy as np, soundfile as sf
T, recs = sys.argv[1], sys.argv[2]
fails = 0
def check(ok, what):
    global fails
    print(("PASS " if ok else "FAIL ") + what)
    fails += not ok
def parse(k):
    tr, rg = {}, {}
    for line in open(f"{T}/check.{k}"):
        kind, _, rest = line.rstrip("\n").partition(" ")
        f = rest.split("|")
        if kind == "TRACK":
            tr[f[0]] = dict(order=int(f[1]), muted=int(f[2]), inputs=int(f[3]), gain=float(f[4]), plugins=f[5], outs=int(f[6]))
        elif kind == "REGION":
            rg.setdefault(f[0], []).append(dict(pos=int(f[1]), len=int(f[2]), ch=int(f[3]), srcs=f[4].split(",")))
    return tr, rg
pj = json.load(open(f"{T}/project/project.json"))
start = pj["ardour"]["start"]
audio = glob.glob(f"{T}/session/interchange/*/audiofiles")[0]
for k, g, sc in ((1, 0.25, "Stereo Cleaned"), (2, 0.125, "Stereo denoised")):
    tr, rg = parse(k)
    check(set(tr) == {"Mono", "Mono Cleaned", "Stereo", sc}, f"run {k}: tracks {sorted(tr)}")
    if set(tr) != {"Mono", "Mono Cleaned", "Stereo", sc}:
        continue
    tr["Stereo Cleaned"] = tr.pop(sc)
    rg["Stereo Cleaned"] = rg.pop(sc, [])
    check(tr["Mono Cleaned"]["order"] == tr["Mono"]["order"] + 1 and tr["Stereo Cleaned"]["order"] == tr["Stereo"]["order"] + 1,
          f"run {k}: each right below its original: " + ", ".join(f"{n} {t['order']}" for n, t in tr.items()))
    check(tr["Mono"]["muted"] == 1 and tr["Stereo"]["muted"] == 1 and tr["Mono Cleaned"]["muted"] == 0, f"run {k}: the originals muted, the Cleaned not")
    d = tr["Mono Cleaned"]
    check(d["plugins"] == tr["Mono"]["plugins"] == "ACE Amplifier" and abs(d["gain"] - 0.1) < 1e-3 and d["outs"] == tr["Mono"]["outs"] > 0,
          f"run {k}: Mono Cleaned as Mono: plugins {d['plugins']}, fader {d['gain']:.2f}, {d['outs']} outputs connected")
    check(tr["Stereo Cleaned"]["inputs"] == 2, f"run {k}: Stereo Cleaned has 2 channels")
    for n in ("Mono Cleaned", "Stereo Cleaned"):
        r = rg.get(n, [])
        ok = len(r) == 1 and r[0]["pos"] == start and all(s.endswith(f"@{start}") for s in r[0]["srcs"])
        check(ok, f"run {k}: {n}: one region at the recording's start ({start}), the source's original position there: {r}")
        if r:
            f = os.path.join(audio, r[0]["srcs"][0].rsplit("@", 1)[0])
            y = sf.read(f)[0]
            x = sf.read(pj["tracks"][{"Mono Cleaned": "01 Mono", "Stereo Cleaned": "02 Stereo-L"}[n]]["file"])[0]
            check(len(y) == r[0]["len"] and np.allclose(y, x * g, atol=1e-6), f"run {k}: {n}: the render's samples ({g} x the stem)")
check(len(glob.glob(f"{audio}/Mono Cleaned*.wav")) == 2, "run 2 copied a new file, the first one kept: " + ", ".join(sorted(os.path.basename(p) for p in glob.glob(f"{audio}/*Cleaned*"))))
sd = pj["stems_dir"]
check("reimported" in pj and os.path.isfile(os.path.join(sd, "export.tsv")) and not any(re.search("cleaned|denoised", f, re.I) for f in os.listdir(sd))
      and sorted(pj["tracks"]) == ["01 Mono", "02 Stereo-L", "02 Stereo-R"],
      f"re-import: the Cleaned tracks not exported, the numbers as before: {sorted(pj['tracks'])}")
check(all("ardour" in t for t in pj["tracks"].values()), "re-import: every track knows its Ardour track")
check(recs == "same", "the session's recordings unchanged")
check(os.path.exists(glob.glob(f"{T}/session/*.ardour")[0] + ".bleed-backup"), "the session file before is kept (.bleed-backup)")
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
EOF
