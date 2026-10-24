#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH
#
# Removes what ./install.sh put on this computer (its list: work/install.<host>.txt).
# Never touches the recordings, output/ or the analysis in work/ (scan, songs, results).
#
#   ./uninstall.sh            app, launcher, menu entry, Ardour actions, builds
#   ./uninstall.sh --network  also the network environment (work/venv-sep), work/msst
#                             and the weights in work/models (download again: ./install.sh),
#                             and the graphics chip's check (work/device.<host>.json)
#   ./uninstall.sh --system   also the system packages install.sh added (apt remove; asks)
#   ./uninstall.sh --dry-run  only show what would go
#
set -uo pipefail
cd "$(dirname "$0")" || exit 1
STATE=work/install.$(hostname).txt
NET=0; SYS=0; DRY=0
for a in "$@"; do
  case "$a" in
    --network) NET=1 ;;
    --system) SYS=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,/^[^#]/p' "$0" | grep '^#' | grep -v SPDX- | sed -e 's|^# \{0,1\}||'; exit 0 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done
[ -f "$STATE" ] || { echo "nothing recorded in $STATE (install.sh not run here?)"; exit 0; }
rm_path() {
  [ -e "$1" ] || return
  if [ "$DRY" = 1 ]; then echo "would remove $1"; else rm -rf -- "$1" && echo "removed $1"; fi
}
APT=""
while read -r kind what; do
  case "$kind" in
    file|build|lv2) rm_path "$what" ;;
    venv|dir) [ "$NET" = 1 ] && rm_path "$what" ;;
    apt) APT="$APT $what" ;;
  esac
done < "$STATE"
if [ "$NET" = 1 ]; then
  for f in work/models/kj_melroformer.* work/models/htdemucs_6s.* work/models/scnet_xl_ihf.* "work/device.$(hostname).json"; do rm_path "$f"; done
fi
if [ -n "$APT" ]; then
  if [ "$SYS" = 1 ] && [ "$DRY" = 0 ]; then
    echo "removing system packages:$APT"
    sudo apt-get remove$APT
  else
    echo "system packages install.sh added (kept; --system removes them):$APT"
  fi
fi
[ "$DRY" = 0 ] && [ "$NET" = 1 ] && [ "$SYS" = 1 ] && rm -f "$STATE"
echo "done"
