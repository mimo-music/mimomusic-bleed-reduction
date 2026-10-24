#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH
#
# The whole chain on a made-up recording (tools/make_demo.py, nothing real): a project from
# its stems, roles set (lead, backing, instrument), a Draft render, then the app's self-test
# on it (real mouse and key events, offscreen). Exit code 0 = everything passed.
#
#   bash tests/demo_test.sh [--no-render] [--screenshots DIR] [--keep]
#
#   --no-render        skip the render (no networks; the self-test then checks less)
#   --screenshots DIR  save the app's views as PNG there
#   --keep             keep the temporary folder (its path is printed)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
RENDER=1; SHOTS=""; KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --no-render) RENDER=0; shift ;;
    --screenshots) SHOTS="$(realpath -m "$2")"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
done
BUILDS="${MIMOMUSIC_BUILDS_ROOT:-$ROOT/../builds}/bleed_reduction/app"
if [ -x "$BUILDS/bleed-reduction" ]; then APP=("$BUILDS/bleed-reduction")
elif [ -x "$BUILDS/bleed-workbench" ]; then APP=("$BUILDS/bleed-workbench" --product)
else echo "no app in $BUILDS: ./install.sh builds it"; exit 2; fi

T=$(mktemp -d /tmp/bleed-demo.XXXXXX)
[ "$KEEP" = 1 ] && echo "folder: $T" || trap 'rm -rf "$T"' EXIT
python3 tools/make_demo.py "$T/stems"
python3 tools/project.py new "$T/project" --name "Demo band" --stems "$T/stems"
python3 - "$T/project/project.json" <<'EOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
for n, t in d["tracks"].items():
    t.update(role="vocal" if "Vocal" in n else "instrument", lead="Lead" in n, role_set=True)
json.dump(d, open(p, "w"), indent=1)
EOF
if [ "$RENDER" = 1 ]; then
  python3 tools/render.py "$T/project" --quality draft 2>&1 | grep -v -i warning | tail -3
fi
cp -r "$T/project" "$T/testcopy"      # the self-test changes roles and files
[ -n "$SHOTS" ] && mkdir -p "$SHOTS"
QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" "${APP[@]}" --project "$ROOT" --gui-test \
  --test-project "$T/testcopy" ${SHOTS:+--screenshots "$SHOTS"} 2>&1 | grep -E 'product-test|QML' | sed 's/^debug //'
exit "${PIPESTATUS[0]}"
