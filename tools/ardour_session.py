# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""What a project knows about the Ardour session it was exported from.

export.tsv (written next to the stems by ardour/headless/export_raw_stems.lua):
  range <first sample> <end sample> <rate>
  track <route id> <channel> <channels> <track name> <file>
"""
import os
import re

CLEANED = re.compile(r"\s(cleaned|denoised)\s*$", re.I)   # "Conga Cleaned" (or by hand "Conga denoised"): our result


def is_cleaned(name):
    return bool(CLEANED.search(name))


def original_of(name):
    """"Conga Cleaned" -> "Conga"."""
    return CLEANED.sub("", name)


def read_export(stems_dir):
    """({"start", "end", "rate"} or None, {stem name: {"route_id", "route", "channel", "channels"}}).
    Exports before export.tsv: the range from the export's log, no track ids."""
    rng, tracks = None, {}
    tsv = os.path.join(stems_dir, "export.tsv")
    if os.path.exists(tsv):
        for line in open(tsv, encoding="utf-8"):
            f = line.rstrip("\n").split("\t")
            if f[0] == "range" and len(f) == 4:
                rng = {"start": int(f[1]), "end": int(f[2]), "rate": int(f[3])}
            elif f[0] == "track" and len(f) == 6:
                tracks[os.path.splitext(f[5])[0]] = {"route_id": f[1], "channel": int(f[2]),
                                                     "channels": int(f[3]), "route": f[4]}
        return rng, tracks
    log = os.path.join(stems_dir, "export_raw_stems.log")
    if os.path.exists(log):
        for line in open(log, encoding="utf-8", errors="replace"):
            m = re.match(r"range (\d+) - (\d+) \(.* at (\d+) Hz\)", line)
            if m:
                rng = {"start": int(m[1]), "end": int(m[2]), "rate": int(m[3])}
    return rng, tracks


def session_start(pj):
    """Where the project's sample 0 is on the Ardour session's timeline (0 for stems)."""
    if (pj.get("source") or {}).get("kind") != "ardour":
        return 0
    if "ardour" in pj and "start" in pj["ardour"]:
        return pj["ardour"]["start"]
    rng = read_export(pj.get("stems_dir", ""))[0]
    return rng["start"] if rng else 0
