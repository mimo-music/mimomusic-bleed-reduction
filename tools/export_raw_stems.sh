#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH
# Every track of an Ardour session as an unprocessed stem (see ardour/headless/export_raw_stems.lua):
#   sh tools/export_raw_stems.sh <session folder> <output folder> [snapshot name]
# Close the session in Ardour first. Needs ardour9-lua (comes with Ardour 9).
# The session folder is only read: Ardour opens a stand-in in a temporary folder (the session file, MIDI, plugin
# state and peaks copied, the recordings linked; Ardour opens existing recordings read-only), and
# with a copy of its settings (else the stand-in lands in Ardour's recent sessions). The bounces,
# peaks and window state Ardour writes stay in there; it is removed at the end, also on failure.
HERE="$(cd "$(dirname "$0")" && pwd)/ardour/headless"
DIR="$1"; OUT="$2"; NAME="$3"
[ -d "$DIR" ] && [ -n "$OUT" ] || { echo "usage: sh $0 <session folder> <output folder> [snapshot name]"; exit 2; }
DIR="$(cd "$DIR" && pwd)"
if [ -z "$NAME" ]; then
  NAME="$(basename "$DIR")"
  [ -f "$DIR/$NAME.ardour" ] || NAME="$(ls "$DIR"/*.ardour 2>/dev/null | grep -v '\.bak$' | head -1 | xargs -r -d '\n' basename | sed 's/\.ardour$//')"
fi
[ -f "$DIR/$NAME.ardour" ] || { echo "no session file $DIR/$NAME.ardour"; exit 2; }
LUA="$(command -v ardour9-lua || command -v ardour8-lua)"
[ -n "$LUA" ] || { echo "ardour9-lua not found (it comes with Ardour 9)"; exit 2; }
if ls "$DIR"/*.pending >/dev/null 2>&1 || pgrep -af "[a]rdour.*$NAME" 2>/dev/null | grep -v -e project.py -e export_raw_stems -e bleed-reduction -e bleed-workbench | grep -q .; then
  echo "the session seems open in Ardour: close it first"; exit 2
fi
mkdir -p "$OUT" && OUT="$(cd "$OUT" && pwd)"
echo "exporting $DIR ($NAME) -> $OUT"
LOG="$OUT/export_raw_stems.log"

TMPS="$(mktemp -d "${TMPDIR:-/tmp}/bleed_export.XXXXXX")" || exit 1
trap 'rm -rf "$TMPS"' EXIT
trap 'exit 1' INT TERM HUP
SH="$TMPS/$(basename "$DIR")"
mkdir -p "$SH" || exit 1
cp -p "$DIR/$NAME.ardour" "$SH/" || exit 1
for d in "$DIR"/interchange/*/; do
  i="$SH/interchange/$(basename "$d")"
  mkdir -p "$i"
  for s in audiofiles videofiles; do [ -d "$d$s" ] && { cp -rs "$d$s" "$i/" || exit 1; }; done
  [ -d "${d}midifiles" ] && { cp -rp "${d}midifiles" "$i/" || exit 1; }   # MIDI sources can be written
done
[ -d "$DIR/externals" ] && { cp -rs "$DIR/externals" "$SH/" || exit 1; }
for s in plugins peaks; do [ -d "$DIR/$s" ] && { cp -rp "$DIR/$s" "$SH/" || exit 1; }; done
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"
mkdir -p "$TMPS/config"
for c in "$CFG"/ardour9 "$CFG"/ardour8; do [ -d "$c" ] && cp -rp "$c" "$TMPS/config/"; done

XDG_CONFIG_HOME="$TMPS/config" BLEED_SESSION_DIR="$SH" BLEED_SESSION_NAME="$NAME" BLEED_OUT="$OUT" \
  "$LUA" "$HERE/export_raw_stems.lua" > "$LOG" 2>&1
grep -E "^(range|skip|DONE|ERROR)|: $OUT/" "$LOG"
grep -q "^DONE" "$LOG" && ! grep -q "^ERROR" "$LOG"
