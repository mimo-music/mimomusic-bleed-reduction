# How it works

Bleed Reduction cleans each mic with pretrained source separation networks,
guided by what the other mics of the same recording contain. Nothing is
learned per recording: the networks are used as they are, and the recording's
other mics decide where and how much is removed.

## The networks

| Network | Splits a signal into | Used for |
|---|---|---|
| **Mel-Band RoFormer** (vocals, Kimberley Jensen's weights) | voice / everything else | every track that gets cleaned |
| **HTDemucs 6 stems** (Meta) | drums, bass, guitar, piano, vocals, other | the instrument step |

Both run at 44.1 kHz stereo: a mono mic is resampled, duplicated to two
channels, and the result averaged back to mono at the recording's rate. Long
stretches of exact digital silence (where a DAW track has no region) are cut
out before a network runs and put back after (`tools/steps/silence.py`):
a window of mostly zeros made the vocal network pass whole regions through
untouched. They run
on an NVIDIA graphics card when there is one, on an AMD chip when the install
check found it right and faster (`tools/device.py`), else on the processor. Sources and
licenses: [THIRD_PARTY.md](THIRD_PARTY.md).

## The chain per role

```
                         ┌─────────────── voice network ───────────────┐
 Lead vocal     original ─► voice ─────────────────────────────────────────────► result   (neural)
 Backing vocal  original ─► voice ─► lead singers' leak turned down ───────────► result   (neural_xvoc)
 Instrument     original ─► voice removed where the vocal mics explain it
                           ─► category network: keep the mic's own category ──► result   (novocal_guided_cat)
 Don't clean    original ──────────────────────────────────────────────────────► result   (original)
```

The name in brackets is the chain (shown with **Chains** in the app).

**Voice (neural).** The vocal network's voice estimate of the mic. On a vocal mic
the voice is what the mic is for; everything else (band, room) is the bleed.

**Backing vocal (neural_xvoc).** The lead singer reaches the coro mics 9–15 ms late
and mostly as room sound, so subtracting does little. Instead the leak from the
lead mics into each coro mic is measured per half octave (in the passages where
the lead sings and the coro singer doesn't), and every time-frequency bin of the
coro mic is turned down by how much of it the lead's leak explains (a Wiener-like
gain, smoothed over 3 bins × 3 frames, at most −20 dB). Coro singers singing
together are not separated from each other. The lead mics themselves are not
gated: there it was audible.

**Instrument, step 1: the voice out (novocal_guided).** The vocal network alone
also takes horns for a voice (a sax solo lost 10–15 dB). So its removed part is
only taken out where the singers explain it: the leak of each vocal mic's clean
voice into this mic is measured from the cross spectrum, and the removal is
limited to 6 dB above that predicted leak. Where nobody sings, nothing is removed;
where the sax is louder than the voice leak, the sax stays.

**Instrument, step 2: the other instruments out (cat).** The 6-stem network splits
the voice-free signal into categories; the mic keeps its own category, the loudest
one that isn't vocals (percussion → drums, tres → guitar, bass → bass, horns and
violin → other). Limitation: instruments of the **same** category bleeding into
each other stay (a conga in the bongo mic: both are drums).

**Don't clean (original).** A copy of the original over the range, so every track
has a result file.

The roles come from listening tests on concert recordings:
this chain was rated best on instrument mics (violin, bongo, trumpet 5 of 5),
ahead of reference-based subtraction and of the voice removal alone.

## Suggest roles (the analysis)

Optional; only needed for suggestions and the song list:

1. `scan.py` — for every pair of mics, the delay and how much of one is explained
   by the other (GCC-PHAT on sampled windows).
2. `timeline.py` — a level timeline of every track: the songs (where the band
   plays), mutes, and per track the passages where its own source is silent.
3. `vocal_share.py` — each track's loudest moments through the vocal network:
   the share of voice. Over −3 dB → vocal, under −12 dB → instrument, between →
   instrument too (horns, room); near silent → don't clean. Of the vocal mics, the
   one with the most voice is suggested as lead.

Roles you set yourself are marked (`role_set` in `project.json`) and never replaced.

## The render

`tools/render.py <project>` (the app starts it detached):

- A segment is only reused if it was made with the same roles / chains, quality and
  processing version (`VERSION` in `render.py`); otherwise it is rendered again.
- The range is cut into **segments of 3 minutes** plus 4 s of overlap on each side,
  processed one after another in `<project>/work/segNNN/`. Memory stays small,
  and a finished segment is kept (`done.json`), so a stopped render resumes.
- Per segment: cut the tracks → voice network on every track that needs it (the
  vocal mics always, when a guided or backing chain needs their voices) → voice /
  voice-removed versions → backing vocal step → guided voice removal → category
  network → the chain's result per track.
- The segments are joined with linear crossfades over the overlaps (all chain
  outputs are sample-aligned with their input; an untouched track comes out equal
  to the original within 1e-8).
- Output: `<project>/render/<track>.wav`, 32-bit float, the recording's sample rate,
  exactly the length of the range. Progress in `render/progress.json`, log in
  `render/render.log`, what was rendered in `render/render.json`.

### Quality: Final and Draft

HTDemucs works in frames, and in nearly silent passages its output carries a faint
buzz at its frame rate (43 / 86 Hz). **Final** runs the category network 4 times on
input shifted by a quarter frame each and averages: the buzz is gone (measured
4.7 / 2.9 dB over the input instead of 15 / 19 dB). **Draft** runs it once, about 4×
faster for that step. A segment rendered at the other quality is done again.

## The project file

`<project>/project.json`:

```json
{
  "name": "…", "id": "…", "stems_dir": "…", "created": "…",
  "tracks": { "<track>": { "file": "…", "role": "vocal|instrument|keep", "lead": false,
                           "role_set": true, "chain": "auto", "share_db": -12.3 } },
  "analysis": { "done": true, "songs": [[start, end], …], "rate": 48000, "seconds": 361.4 },
  "render": { "start": 0, "end": null, "quality": "final" }
}
```

`chain: "auto"` follows the role (lead → neural, backing → neural_xvoc,
instrument → novocal_guided_cat, keep → original). Older projects with the roles
`line` / `silent` (→ keep) and `mixed` (→ instrument) are read the same way.

Command line: `python3 tools/project.py new|analyse|show …`,
`python3 tools/render.py <project> [--plan] [--quality draft|final] [--start S --end S] [--tracks A,B]`.
