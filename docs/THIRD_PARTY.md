# Models and licenses

Not legal advice: this lists what the sources say (checked October 2026).

The repository contains only our own code. The network weights, the separation
code and the Python packages are **downloaded by `install.sh`** from their
original sources into `work/` (not in git), so nothing of them is redistributed
with the source.

## Network weights

| Weights | Author / source | License | Trained on | Used |
|---|---|---|---|---|
| Mel-Band RoFormer vocals (`kj_melroformer.ckpt`) | Kimberley Jensen, [huggingface.co/KimberleyJSN/melbandroformer](https://huggingface.co/KimberleyJSN/melbandroformer) | **MIT** (the author switched it to MIT; "free to use and redistribute") | ~1,400 tracks gathered by the UVR community, incl. MUSDB18 and MoisesDB; the rest is not documented ([issue #22](https://github.com/KimberleyJensen/Mel-Band-Roformer-Vocal-Model/issues/22)) | always |
| HTDemucs 6 stems (`htdemucs_6s`) | Meta, [github.com/facebookresearch/demucs](https://github.com/facebookresearch/demucs) (archived, no longer maintained) | code MIT; **no separate license stated for the weights** | MUSDB-HQ + 800 internal songs | instrument step |
| SCNet XL IHF (`scnet_xl_ihf`) | ZFTurbo, [MSST release v1.0.15](https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/tag/v1.0.15) | **none stated** | MUSDB18 only | downloaded with `--cuda`; not used by the product chain |

About the training data: [MUSDB18](https://sigsep.github.io/datasets/musdb.html)
may "only be used for academic purposes", and parts of it are CC BY-NC-SA.
MoisesDB is, as far as known, also limited to non-commercial use.
Whether such limits carry over to weights trained on the data is legally
unsettled.

The weights are not part of this repository: `install.sh` downloads each of
them from its author's own release. Check their terms before any use beyond
your own.

## Code

| Component | License | How it is used |
|---|---|---|
| ZFTurbo, Music-Source-Separation-Training (pinned commit in `install.sh`) | MIT | cloned into `work/msst`: model code and configs |
| demucs 4.1.0 | MIT | pip, model code |
| PyTorch, torchaudio | BSD-style | pip |
| numpy, scipy, scikit-learn, soundfile | BSD | pip |
| librosa | ISC | pip |
| einops, beartype, rotary-embedding-torch, openunmix | MIT | pip |
| the rest of `tools/requirements-sep.txt` | permissive (MIT / BSD / Apache / PSF) | pip |
| Qt 6 (Core, Gui, Qml, Quick, Controls, Multimedia) | LGPL-3.0 / GPL | system packages, linked dynamically |
| libsndfile | LGPL-2.1 | system package |
| Ardour 9 (`ardour9-lua`) | GPL-2.0 | separate program, called for the session export |

Our own code: `GPL-3.0-or-later`, copyright Mettronic GmbH (see [LICENSE](../LICENSE)),
like the MimoMusic plugins.
