# LiveFISH Nucleus Cropping — Usage & Debugging Guide

This covers how to run the two scripts that make up Step 1 of the LiveFISH pipeline:
`crop_nuclei_sam.py` segments nuclei and writes a JSON sidecar per FOV file;
`save_crops.py` reads those JSONs and writes the actual TIFF crops.
Keeping the two steps separate means you can re-save TIFFs with different settings
(e.g. different LUT mode) without re-running the slow µSAM segmentation.

---

## Setup

### Prerequisites

- [Miniconda or Anaconda](https://docs.conda.io/en/latest/miniconda.html)
- Python 3.10+ (3.13 confirmed working)
- For Apple Silicon Macs: MPS acceleration is used automatically (`device='mps'`)
- For Linux with GPU: change `device='mps'` → `device='cuda'` in `crop_nuclei_sam.py` line ~640

### Install dependencies

All scripts run in a dedicated conda environment. Create one and install everything:

```bash
conda create -n livefish python=3.13
conda activate livefish
pip install numpy scipy scikit-image matplotlib Pillow tifffile nd2 micro-sam
```

> **Note:** `micro-sam` pulls in PyTorch automatically. On Apple Silicon the MPS backend
> is included. On Linux you may need to install a CUDA-enabled torch first —
> see [pytorch.org](https://pytorch.org) for the right install command for your CUDA version.

Once set up, all commands below use `conda run -n livefish` to invoke this environment.
If you named your environment differently, substitute that name.

### Navigate to the project folder

All paths below are relative to the root of the CS273B project folder.
Open a terminal and `cd` there first:

```bash
cd "/path/to/CS273B project"
```

On the lab machine this is:
```bash
cd "/Users/kkenajj/Downloads/CS273B project"
```

---

## Step 1 — Segment nuclei (`crop_nuclei_sam.py`)

### Single file (recommended starting point)

Always start with one file and check the visualizations before running the full batch.
Use a small or known-good file first.

```bash
conda run -n livefish python "code (being modified)/crop_nuclei_sam.py" \
    "data for analysis/FOV (.nd2 files)/<your_file>.nd2" \
    --nucleus-channel 0 --margin 30 \
    --min-area 1000 --max-area 200000 \
    --segmentation-mode apg --model-type vit_b_lm
```

Example with the confirmed good test file:
```bash
conda run -n livefish python "code (being modified)/crop_nuclei_sam.py" \
    "data for analysis/FOV (.nd2 files)/U2OS_chr3_195M-488+195.7M-565+198M-647_RNP1_H33342_Bright+Antifade_7h_0.9_4t (good).nd2" \
    --nucleus-channel 0 --margin 30 \
    --min-area 1000 --max-area 200000 \
    --segmentation-mode apg --model-type vit_b_lm
```

### Full batch (all .nd2 files in folder)

Pass the folder instead of a single file — the script finds all `.nd2` files automatically.

```bash
conda run -n livefish python "code (being modified)/crop_nuclei_sam.py" \
    "data for analysis/FOV (.nd2 files)" \
    --nucleus-channel 0 --margin 30 \
    --min-area 1000 --max-area 200000 \
    --segmentation-mode apg --model-type vit_b_lm
```

### Parameters

| Flag | Default | What it controls |
|------|---------|-----------------|
| `--nucleus-channel` | `0` | Which channel to segment on (0 = DAPI/nucleus stain) |
| `--margin` | `30` | Padding in pixels added around each nucleus bounding box |
| `--min-area` | `1000` | Minimum nucleus area in pixels — smaller masks discarded as debris |
| `--max-area` | `200000` | Maximum nucleus area in pixels — larger masks discarded |
| `--segmentation-mode` | `apg` | APG (recommended for touching nuclei); AMG is the plain SAM alternative |
| `--model-type` | `vit_b_lm` | µSAM model fine-tuned on fluorescence microscopy; `vit_l_lm` is larger/slower |
| `--border-margin` | `5` | Min distance (px) from image border to nucleus centroid; smaller masks at edges discarded |

### Outputs (per .nd2 file)

Results are written next to each input file, in a folder named after the file stem:

```
data for analysis/FOV (.nd2 files)/<stem>/
├── <stem>_crops.json              ← bbox + suppression coords consumed by save_crops.py
└── visualizations/
    ├── seg_overview.png           ← 4-panel: raw image | µSAM raw | after filter+merge | final
    ├── crop_grid.png              ← thumbnail of every accepted nucleus crop
    ├── suppression_demo.png       ← before/after neighbour suppression for first 6 crops
    └── all_channels_demo.png      ← all 4 channels for first 4 crops
```

**Always open `seg_overview.png` first** — it's the fastest way to tell if segmentation worked.

---

## Step 2 — Save TIFFs (`save_crops.py`)

Recursively finds all `*_crops.json` files under the given directory and writes one
TIFF per crop. Run this after Step 1 completes (for one file or the whole batch).

```bash
conda run -n livefish python "code (being modified)/save_crops.py" \
    "data for analysis/FOV (.nd2 files)"
```

### Outputs (per .nd2 file)

```
data for analysis/FOV (.nd2 files)/<stem>/
├── <stem>_1.tif    ← (T, C, Y, X) uint16, neighbours zeroed, per-channel LUTs embedded
├── <stem>_2.tif
└── ...
```

TIFFs open in Fiji with per-channel colors matching the original .nd2. Each file is a
(T, C, Y, X) hyperstack ready for Xinyi's `headless_Macro_first_steps_for_published.ijm`.

---

## Debugging

The visualizations are your main diagnostic tool. Here's how to read the common failure modes:

### "Too many crops — there's obvious debris or tiny fragments in the grid"

Open `seg_overview.png` and look at panel 3 (after filter+merge). If small bright spots
or partial cells at the image edge are making it through, raise `--min-area`.
Try 2000 first, then 3000 if debris persists. The right value is where the crop grid
shows only clean oval nuclei.

### "Too few crops — some nuclei are clearly missing"

If dim or small nuclei are being dropped, lower `--min-area` (try 500).
If nuclei near the image border are missing, that's intentional — the border filter drops any nucleus whose centroid is within `--border-margin` px of the edge (default 5) to avoid partial crops. Raise this if you want to be more conservative about edge nuclei, lower to 0 to keep them all.

### "Two touching nuclei are showing up as one crop"

APG mode handles most touching pairs automatically via watershed splitting.
If a merged pair is still slipping through, look at the solidity of the combined mask —
if it's above `MIN_SOLIDITY` (0.70 in the script), the split won't even be attempted.
Lower `MIN_SOLIDITY` slightly (try 0.65) to trigger the split on more masks.
If the split is being attempted but failing, lower `SPLIT_MIN_DIST` (currently 20 px)
so the peak detector can find two centres that are closer together.

### "One nucleus is split into two separate crops"

This means µSAM fragmented a single nucleus into two masks. `merge_adjacent_masks`
should catch this, but it only merges masks within `MERGE_PROXIMITY` px of each other
(currently 2 px). If the gap between fragments is larger, raise `MERGE_PROXIMITY` (try 5–10).
Check `seg_overview.png` panel 2 (µSAM raw) to confirm it's fragmentation and not
two genuinely separate nuclei that happen to be close.

### "The target nucleus is partially zeroed in a crop"

The neighbour suppression is zeroing pixels that belong to the target nucleus.
This usually means µSAM drew the mask boundary too tightly, leaving some nucleus pixels
outside the mask — those pixels then get zeroed as "not belonging to any nucleus."
Increasing `--margin` won't fix this; the issue is the mask boundary itself.
Check `suppression_demo.png` to confirm. If it's systematic, try `--model-type vit_l_lm`
(larger model, better boundaries) or lower `MIN_SOLIDITY` in the script to let the
watershed refine the boundary.

### "A neighbouring nucleus is visible in a crop (not zeroed)"

This means the neighbour's mask wasn't accepted by the filter — it was dropped as too
small, too large, or a border nucleus — so there was nothing to suppress it with.
Check `seg_overview.png` panel 3 to see if the offending neighbour has a mask at all.
If not, adjust `--min-area` or `--border_margin` so it gets accepted.

### "Script crashes on one file but works on others"

Each file is wrapped in a try/except so the batch continues — check stderr for the
traceback. Common causes: corrupted .nd2 file, unexpected axis order in the nd2 metadata,
or a file with a different number of channels than expected. The axes string is printed
on load (`nd2 axes string: ...`) — verify it matches `TZCYX` or a close variant.

---

## Repeatable results checklist

1. Use the same named conda environment every time — packages must match exactly.
2. Run single-file first, inspect `seg_overview.png` and `crop_grid.png` before batching.
3. **Record the parameters you used** — the JSON sidecar does not store them.
4. If you change parameters, re-run Step 1 before Step 2 — save_crops.py reads from the JSON sidecars, so TIFFs reflect whatever segmentation last wrote them. (If a Step 1 run crashed partway through, the JSONs from files that didn't get re-processed will still hold old parameters — delete them or re-run those specific files to be safe.)

   `*_crops.json` files and re-run Step 1 before re-running Step 2, or you will get
   TIFFs from stale segmentation data.
