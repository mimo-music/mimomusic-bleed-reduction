#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH
#
# Installs everything the bleed reduction tools need on this computer, once;
# safe to repeat (skips what is there). Undo with ./uninstall.sh.
#
#   ./install.sh                 everything
#   ./install.sh --check         only show what is there and what is missing
#   ./install.sh --no-system     skip the system packages (no sudo)
#   ./install.sh --no-models     skip the network weights (1.2 GB download)
#   ./install.sh --cpu | --cuda | --rocm   torch for the processor / NVIDIA card / AMD chip
#                                (default: NVIDIA if nvidia-smi works, else AMD if there is one)
#   ./install.sh --check-device  only check the graphics chip again (step 4b)
#
# Steps:
#  1. system packages (apt, asks for the password once): compiler, CMake, ninja,
#     libsndfile, Qt 6 with QML and Multimedia, python3-venv, git, curl;
#     only the missing ones, and the list of what it added is kept for uninstall.sh
#  2. network environment work/venv-sep (Python packages from tools/requirements-sep.txt;
#     torch for the card, the AMD chip (ROCm) or the processor)
#  3. separation code work/msst (ZFTurbo's Music-Source-Separation-Training, fixed version)
#  4. network weights work/models: vocals (Mel-RoFormer, KJ), instrument categories
#     (HTDemucs 6 stems; SCNet XL only with an NVIDIA card: too slow on the processor)
#  4b. an AMD graphics chip: only used when it computes right and faster than the
#     processor (tools/device_check.py; verdict in work/device.<host>.json, the app follows it)
#  5. the app (app/, Qt 6), built outside the project in ../builds/bleed_reduction:
#     `bleed-reduction`, also in the menu (in the development tree also `bleed-workbench`)
#  6. Ardour: checks for ardour9-lua (importing an Ardour session needs it)
# Everything is logged to work/logs/install.<host>.log. Memory is checked before
# compiling (the number of compile jobs follows free memory).
#
set -uo pipefail
cd "$(dirname "$0")" || exit 1
ROOT=$(pwd)
HOST=$(hostname)
BUILDS="${MIMOMUSIC_BUILDS_ROOT:-$ROOT/../builds}/bleed_reduction"
STATE=work/install.$HOST.txt          # what this script added (for uninstall.sh)
LOG=work/logs/install.$HOST.log
VENV=work/venv-sep
MSST_REV=6fdad13
mkdir -p work/logs work/models
exec > >(tee -a "$LOG") 2>&1

CHECK=0; SYSTEM=1; MODELS=1; TORCH=auto; ONLY_DEVICE=0
ROCM_INDEX=https://download.pytorch.org/whl/rocm7.2
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --no-system) SYSTEM=0 ;;
    --no-models) MODELS=0 ;;
    --cpu) TORCH=cpu ;;
    --cuda) TORCH=cuda ;;
    --rocm) TORCH=rocm ;;
    --check-device) ONLY_DEVICE=1 ;;
    -h|--help) sed -n '2,/^[^#]/p' "$0" | grep '^#' | grep -v SPDX- | sed -e 's|^# \{0,1\}||'; exit 0 ;;
    *) echo "unknown option: $a (see ./install.sh --help)"; exit 2 ;;
  esac
done

say()  { echo; echo "== $*"; }
ok()   { echo "   ok: $*"; }
miss() { echo "   missing: $*"; MISSING=$((MISSING + 1)); }
note() { grep -qxF "$1" "$STATE" 2>/dev/null || echo "$1" >> "$STATE"; }
MISSING=0
echo "---- $(date '+%F %T') install.sh $* on $HOST"

# an AMD graphics chip or card (PCI vendor 1002), e.g. a laptop's Radeon 880M
amd_gpu() {
  local v
  for v in /sys/class/drm/card*/device/vendor; do
    [ -r "$v" ] && [ "$(cat "$v")" = 0x1002 ] && return 0
  done
  return 1
}

# 4b: is the graphics chip worth using? (device.py follows the verdict)
check_device() {
  say "4b. graphics chip"
  if [ ! -x "$VENV/bin/python" ]; then echo "   no network environment yet"; return; fi
  "$VENV/bin/python" tools/device_check.py || echo "   the check failed: the networks use the processor"
}
if [ "$ONLY_DEVICE" = 1 ]; then check_device; exit 0; fi

# jobs for compiling: one per 1.5 GB of available memory, at most the cores
jobs() {
  local av; av=$(awk '/MemAvailable/{print int($2/1024/1024)}' /proc/meminfo 2>/dev/null || echo 4)
  local n=$(( av * 2 / 3 )); [ "$n" -lt 1 ] && n=1
  [ "$n" -gt "$(nproc)" ] && n=$(nproc)
  echo "$n"
}

# --- 1. system packages ----------------------------------------------------
PKGS="build-essential cmake ninja-build pkg-config git curl libsndfile1-dev libfftw3-dev
  python3-venv qt6-base-dev libqt6test6 qt6-declarative-dev qt6-multimedia-dev qt6-tools-dev qt6-qpa-plugins
  libgl-dev qml6-module-qtquick qml6-module-qtquick-controls qml6-module-qtquick-layouts
  qml6-module-qtquick-dialogs qml6-module-qtquick-templates qml6-module-qtquick-window
  qml6-module-qtquick-shapes qml6-module-qtqml-workerscript qml6-module-qtmultimedia"
say "1. system packages"
NEED=""
for p in $PKGS; do
  dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || NEED="$NEED $p"
done
if [ -z "$NEED" ]; then ok "all there"
elif [ "$CHECK" = 1 ] || [ "$SYSTEM" = 0 ]; then miss "$NEED"
  echo "   install with: sudo apt install$NEED"
else
  echo "   installing:$NEED"
  if sudo apt-get install -y $NEED; then
    for p in $NEED; do note "apt $p"; done
  else
    echo "   apt failed: install them by hand (sudo apt install$NEED) and run this again"; exit 1
  fi
fi

# --- 2. network environment ---------------------------------------------------
say "2. network environment ($VENV)"
if [ "$TORCH" = auto ]; then
  if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then TORCH=cuda
  elif amd_gpu; then TORCH=rocm
  else TORCH=cpu; fi
fi
echo "   torch for: $TORCH"
if [ "$CHECK" = 1 ]; then
  if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import torch, soundfile, scipy, demucs" 2>/dev/null; then
    ok "$("$VENV/bin/python" -c 'import torch; print("torch", torch.__version__, "card" if torch.cuda.is_available() else "processor")')"
    [ -s "work/device.$HOST.json" ] && ok "graphics chip checked: $(python3 -c "import json; d=json.load(open('work/device.$HOST.json')); print(d['device'], d.get('why') or '')")" \
      || { [ "$TORCH" = rocm ] && miss "graphics chip check (./install.sh --check-device)"; }
  else miss "network environment"; fi
else
  if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV" || { echo "   python3 -m venv failed (python3-venv missing?)"; exit 1; }
    note "venv $VENV"
  fi
  PY="$VENV/bin/python"
  "$PY" -m pip install -q --upgrade pip || true
  if [ "$TORCH" = cuda ]; then
    "$PY" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null \
      || "$PY" -m pip install torch==2.14.1 torchaudio || echo "   torch (CUDA) failed: an older NVIDIA driver needs an older torch (pip install torch==<version> --index-url https://download.pytorch.org/whl/cu126)"
  elif [ "$TORCH" = rocm ]; then
    # ROCm build (a few GB); whether the chip is used decides step 4b. A torch of another build is replaced.
    "$PY" -c "import torch, sys; sys.exit(0 if torch.version.hip else 1)" 2>/dev/null \
      || { "$PY" -m pip install --force-reinstall torch==2.14.1 torchaudio==2.11.0 --index-url "$ROCM_INDEX" \
           && rm -f "work/device.$HOST.json"; } \
      || echo "   torch (ROCm) failed: ./install.sh --cpu uses the processor"
  else
    "$PY" -c "import torch" 2>/dev/null \
      || "$PY" -m pip install torch==2.14.1 torchaudio --index-url https://download.pytorch.org/whl/cpu
  fi
  "$PY" -m pip install -q -r tools/requirements-sep.txt || echo "   some Python packages failed (see the log)"
  "$PY" -m pip install -q --no-deps demucs==4.1.0 || true
  "$PY" -c "import torch, soundfile, scipy, demucs; print('   ok: torch', torch.__version__, 'card' if torch.cuda.is_available() else 'processor')"
fi

# --- 3. separation code --------------------------------------------------------
say "3. separation code (work/msst)"
if [ -d work/msst/.git ]; then ok "work/msst at $(git -C work/msst rev-parse --short HEAD)"
elif [ "$CHECK" = 1 ]; then miss "work/msst"
else
  git clone -q https://github.com/ZFTurbo/Music-Source-Separation-Training.git work/msst \
    && git -C work/msst checkout -q "$MSST_REV" && note "dir work/msst" && ok "cloned at $MSST_REV"
fi

# --- 4. network weights ---------------------------------------------------------
say "4. network weights (work/models)"
get() {   # file url [min size in bytes]
  local f="work/models/$1"
  if [ -s "$f" ] && [ "$(stat -c %s "$f")" -ge "${3:-1}" ]; then ok "$1"; return; fi
  if [ "$CHECK" = 1 ] || [ "$MODELS" = 0 ]; then miss "$1"; return; fi
  echo "   downloading $1"
  curl -fL --retry 3 -o "$f.part" "$2" && mv "$f.part" "$f" && note "file $f" || { rm -f "$f.part"; echo "   failed: $1"; }
}
MS=https://github.com/ZFTurbo/Music-Source-Separation-Training
get kj_melroformer.ckpt https://huggingface.co/KimberleyJSN/melbandroformer/resolve/main/MelBandRoformer.ckpt 900000000
get kj_melroformer.yaml https://raw.githubusercontent.com/ZFTurbo/Music-Source-Separation-Training/main/configs/KimberleyJensen/config_vocals_mel_band_roformer_kj.yaml
get htdemucs_6s.ckpt https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th 50000000
get htdemucs_6s.yaml https://raw.githubusercontent.com/ZFTurbo/Music-Source-Separation-Training/main/configs/config_htdemucs_6stems.yaml
if [ "$TORCH" = cuda ]; then
  get scnet_xl_ihf.ckpt $MS/releases/download/v1.0.15/model_scnet_ep_36_sdr_10.0891.ckpt 200000000
  get scnet_xl_ihf.yaml $MS/releases/download/v1.0.15/config_musdb18_scnet_xl_more_wide_v5.yaml
fi

# --- 4b. graphics chip ------------------------------------------------------------
# only an AMD chip (NVIDIA is used anyway); once, and again after a new torch
if [ "$CHECK" = 0 ] && [ "$TORCH" = rocm ]; then
  if [ -s "work/device.$HOST.json" ]; then
    say "4b. graphics chip"; ok "checked before (./install.sh --check-device checks again)"
  else check_device; fi
fi

# --- 5. the app -------------------------------------------------------------
say "5. the app"
WORKBENCH=0; [ -f app/qml/Main.qml ] && WORKBENCH=1      # the development tree: also the Workbench
if [ "$WORKBENCH" = 1 ]; then APPBIN="$BUILDS/app/bleed-workbench"; else APPBIN="$BUILDS/app/bleed-reduction"; fi
# launcher and menu entry: name, title, comment, extra arguments
launcher() {
  printf '#!/bin/sh\n# %s; the tools are in %s\nexec "%s" %s--project "%s" "$@"\n' \
    "$2" "$ROOT" "$APPBIN" "$4" "$ROOT" > "$HOME/.local/bin/$1"
  chmod +x "$HOME/.local/bin/$1"
  printf '[Desktop Entry]\nType=Application\nName=%s\nComment=%s\nExec=%s\nIcon=audio-x-generic\nTerminal=false\nCategories=AudioVideo;Audio;\n' \
    "$2" "$3" "$HOME/.local/bin/$1" > "$HOME/.local/share/applications/$1.desktop"
  note "file $HOME/.local/bin/$1"
  note "file $HOME/.local/share/applications/$1.desktop"
}
if [ ! -f app/CMakeLists.txt ]; then echo "   (no app/ yet)"
elif [ "$CHECK" = 1 ]; then [ -x "$APPBIN" ] && ok "$APPBIN" || miss "app (./install.sh builds it)"
else
  if ! dpkg-query -W -f='${Status}' qt6-declarative-dev 2>/dev/null | grep -q "install ok installed"; then
    echo "   Qt 6 is missing (step 1): skipped"
  else
    echo "   compiling with $(jobs) jobs"
    cmake -S app -B "$BUILDS/app" -G Ninja -DCMAKE_BUILD_TYPE=Release -Wno-dev >/dev/null 2>&1 \
      && cmake --build "$BUILDS/app" -j "$(jobs)" && note "build $BUILDS/app" || { echo "   app build failed"; exit 1; }
    mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
    if [ "$WORKBENCH" = 1 ]; then
      launcher bleed-reduction "Bleed Reduction" "Clean the bleed out of every mic of a multitrack recording" "--product "
      launcher bleed-workbench "Bleed Workbench" "Listen, compare, mark and rate the bleed reduction versions" ""
      ok "start with: bleed-reduction (projects) or bleed-workbench (tests, feedback); also in the menu"
    else
      launcher bleed-reduction "Bleed Reduction" "Clean the bleed out of every mic of a multitrack recording" ""
      ok "start with: bleed-reduction; also in the menu"
    fi
  fi
fi

# --- 6. Ardour ------------------------------------------------------------------------
say "6. Ardour"
if command -v ardour9-lua >/dev/null || command -v ardour8-lua >/dev/null; then
  ok "$(command -v ardour9-lua || command -v ardour8-lua)"
else echo "   ardour9-lua not found: importing an Ardour session needs it (comes with Ardour 9)"; fi

say "summary"
if [ "$CHECK" = 1 ]; then echo "   $MISSING part(s) missing"; else
  [ -f tools/run_all.py ] && { python3 tools/run_all.py --dry-run 2>&1 | sed -n '1,4p' | grep -v "== concert " || true; }
  echo "   log: $LOG"
fi
