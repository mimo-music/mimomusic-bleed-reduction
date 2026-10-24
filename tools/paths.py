# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Mettronic GmbH

"""Where the tools keep their files.

WORK: analysis results and caches (scan, timeline, groups, song cuts),
the neural network (model, code, Python environment) and logs: work/ in
the project folder, so copying or syncing the folder takes everything
along. Not in git.
Override with the BLEED_WORK environment variable.

LISTEN: listening material (cleaned songs, group clips), in output/.
The tools only write there and never read back from it.
"""
import os

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.environ.get("BLEED_WORK", os.path.join(PROJECT, "work"))
VENV_PY = os.path.join(WORK, "venv-sep", "bin", "python")
LISTEN = os.path.join(PROJECT, "output")


def work(*parts):
    return os.path.join(WORK, *parts)


def listen(*parts):
    return os.path.join(LISTEN, *parts)
