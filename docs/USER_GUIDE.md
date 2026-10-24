# Bleed Reduction — user guide

## Install

```sh
./install.sh            # everything; safe to run again (skips what is there)
./install.sh --check    # only show what is there and what is missing
./install.sh --help     # all options (--cpu / --cuda, --no-models, --no-system)
```

It installs, once per computer:

1. the missing system packages (asks for the password once): compiler, CMake,
   Qt 6, libsndfile, Python venv, git, curl;
2. a Python environment in `work/venv-sep` with PyTorch, for the graphics card
   when there is an NVIDIA card, for an AMD chip or card (ROCm) when there is one,
   else for the processor; an AMD chip is then checked (it has to compute right
   and be faster than the processor, else the processor is used; `./install.sh
   --check-device` checks again, e.g. after a driver update);
3. the separation code and the network weights (about 1.2 GB download) in `work/`;
4. the app, with `bleed-reduction` in `~/.local/bin` and in the menu.

Importing Ardour sessions needs `ardour9-lua`, which comes with Ardour 9.
`./uninstall.sh` removes what `install.sh` added (`--dry-run` shows it first;
`--network` also the Python environment, `--system` also the system packages).

## A new project

Start `bleed-reduction` and click **New project…**:

- **Name** — anything, e.g. the band and the date.
- **Project folder** — a new, empty folder. The project file, the exported
  stems (for an Ardour session) and the renders go there. Plan for space: a
  render writes one 32-bit file per track.
- **Recording**, one of:
  - **Folder of WAV stems** — one WAV per mic, all with the same sample rate;
    the file names become the track names. The files are linked, not copied:
    leave them where they are.
  - **Ardour session** — the session folder (the one with the `.ardour` file).
    **Close the session in Ardour first.** Every audio track is exported as it
    is recorded and edited (takes, region gain, fades), without plugins, sends,
    fader, pan or mute. Stereo tracks become two tracks, `-L` and `-R`. The
    session itself is not changed.

**Create** imports. If the import fails, the reason stays in the panel on the
start page (and in `work/logs/app.<computer>.log`).

**Open…** and the list of recent projects on the start page open existing projects.

## Roles: what each track is

The track list is the main part of the window. Each track has one role, and
the role decides how it is cleaned:

| Role | Use it for | What happens |
|---|---|---|
| **Lead vocal** | the mic of a lead singer (several are fine) | only the voice is kept; the band is removed |
| **Backing vocal** | coro / backing singers' mics | only the voice is kept, and the lead singers' voices leaking in are turned down |
| **Instrument** | every instrument mic (also horns, room mics) | the singers' voices are removed, then the other instruments: the mic's own instrument stays |
| **Don't clean** | line inputs (keyboards, bass DI), unused or silent mics, tracks that are fine | left exactly as it is |

The "what happens" column says the same for each track.

- **Setting many at once:** tick the tracks (Shift+click ticks a range, the box
  in the header ticks all), then click a role in the bar above the list.
- **Suggest roles…** (optional) listens to the recording and proposes a role for
  every track you haven't set yourself; a role you chose is never changed. It
  also finds the songs (for rendering one song) and shows how much voice each
  mic carries ("voice" column, 0 dB = mostly voice). It takes a few minutes plus
  about 3 minutes per track. Suggested roles are marked "· suggested".
- Mark **every** lead singer's mic as Lead vocal. Without any lead, the backing
  vocal step has to guess who the lead is.
- **Chains** (top right) shows the processing chain per track, for trying other
  combinations. Normally the role is enough.

All settings are saved in `<project>/project.json` right away.

## Render

The **Render** box under the track list:

- **what** — **Whole recording**, **a song …** (after Suggest roles), or a range
  in seconds (**from** / **to**, 0 = to the end).
- **quality**
  - **Final** — the instrument step runs 4 times on shifted input and averages.
    No buzz in quiet passages. Use this for the real result.
  - **Draft** — that step runs once: about 4× faster, but may leave a faint
    43/86 Hz buzz where a mic is almost silent. For trying a song on a laptop.
- **▶ Render** — starts. The progress bar shows the step, the piece and the
  time left. **■ Stop render** stops it.

Good to know:

- The render works in pieces of 3 minutes. A stopped render continues from the
  last finished piece when you start it again.
- It keeps running when you close the window; opening the project again shows
  its progress.
- Speed: on the processor the networks are slow (one minute of 16 mics took
  about 4 hours in Final on an 8-core laptop). With an NVIDIA
  graphics card it is many times faster. Try a song in Draft on a laptop,
  render whole concerts on a computer with a card.

## The result

`<project>/render/<track>.wav` (**Open the render folder**): one file per track,
32-bit float WAV at the recording's sample rate, exactly as long as the rendered
range, so it lines up with the original when placed at the range's start.

**Listening in the app:** click a track. The player shows the original and the
rendered version over the same range; **0** / **1** switch between them, **Space**
plays, **Loop**, **Whole** (Esc) shows everything again.

**Back into Ardour:** import the files (Session → Import, "add files as new
tracks", position at the session start, or at the range's start for a part)
next to the original tracks. An automatic round trip (re-import changed takes,
update the cleaned tracks in the session) is planned, not built yet.

## Troubleshooting

- **"the session seems open in Ardour"** — close it in Ardour (a crashed Ardour
  can leave a `.pending` file in the session folder).
- **"ardour9-lua not found"** — install Ardour 9.
- **The render stops with an error** — the log panel at the bottom shows it, the
  whole log is in `<project>/render/render.log`.
- **A step is very slow** — check `./install.sh --check`: without a working
  graphics card setup everything runs on the processor. The render log says
  so when an AMD chip is not used, and why.
- **The computer switches off during a render** — a power supply too weak for
  the processor and the card at full load. Renders use half the processor's
  threads; fewer: `BLEED_THREADS=6 bleed-reduction`; the NVIDIA card's power:
  `sudo nvidia-smi -pl 220` (until the next restart).
