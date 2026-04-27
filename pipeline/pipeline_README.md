# SPT Pipeline: ROI Segmentation → Single Particle Tracking → Trajectory Export

## Overview

This pipeline takes the output of `auto_roi_for_published_v2.7.py` (which identifies green loci ROIs) and runs a full MATLAB-based Single Particle Tracking (SPT) analysis on each cropped ROI region.

**Full workflow:**
```
auto_roi_for_published_v2.7.py   →   run_pipeline.py   →   matlab_trajectory/*.csv
        (run separately)               (this pipeline)
```

---

## Prerequisites

1. **Run `auto_roi_for_published_v2.7.py` first** on your input directory:
   ```
   python3 auto_roi_for_published_v2.7.py /path/to/<stem>_Nucleus.tif
   ```
   This produces `RoiSet_green.zip` and `G/P/R_loci*_trajectory.csv` in the input directory.

2. **Input directory must contain** (produced by the ImageJ first-steps macro):
   - `<stem>_green.tif`
   - `<stem>_red.tif`
   - `<stem>_purple.tif`
   - `<stem>_Nucleus.tif`
   - `RoiSet_green.zip`

3. **MATLAB** must be on `$PATH` (test with `matlab -batch "disp('ok')"`)

4. **Python dependencies**: `pip install Pillow numpy scipy`

---

## Running the Pipeline

```bash
python3 run_pipeline.py /path/to/input_dir/
```

---

## Pipeline Steps

### Step 1 — Parse ROIs from `RoiSet_green.zip`

Reads the ImageJ binary `.roi` files from the zip produced by `auto_roi`. Each file encodes a rectangle as a 64-byte big-endian struct with `top/left/bottom/right` at byte offsets 8/10/12/14.

**QC check:** Printed ROI coordinates and pixel dimensions for each locus.

---

### Step 2 — Crop all channel TIFFs to each ROI

For each locus and each of the 4 channels (green, red, purple, Nucleus), every frame is cropped to the ROI bounding box and saved as a new multi-frame TIFF inside a `lociN/` subfolder.

Filenames contain the channel name (e.g. `loci1_green.tif`) so downstream code can auto-detect the channel prefix.

**QC check:** Printed crop dimensions and frame count per channel per locus.

---

### Step 3 — Run `spt_batch.m` headlessly via `matlab -batch`

**Script:** `spt_batch.m` (in `practice_analysis/`) — do not confuse with `spt.m` (original, unmodified).

For each cropped TIFF (green, red, purple per locus), MATLAB is invoked non-interactively:

```bash
matlab -batch "addpath('...SPT...'); addpath('...Matlab Tools...'); \
               addpath('...practice_analysis...'); spt_batch('/path/to/loci1_green.tif')"
```

#### Parameters set automatically

| Parameter | Value | Source |
|---|---|---|
| `frame_rate` | 1 / finterval | TIFF ImageJ metadata (`finterval` tag) |
| `pixl` | 1 / XResolution (µm/px) | TIFF metadata (XResolution tag = px/µm) |
| `thresh` | mean + K×std of bandpass-filtered first frame | Auto-computed (see below) |
| `dia` | 7 px | Fixed (particle diameter, must be odd) |
| `boxr` | 11 px | Fixed (centroid fit window, must be odd) |
| `estD` | 0.0001 µm²/s | Fixed (estimated diffusion constant) |
| `mtl` | 5 frames | Fixed (minimum trajectory length) |
| `fitmethod` | 0 | Fixed (2D Gaussian sub-pixel fitting) |
| `trackMem` | 2 frames | Fixed (blink-off tolerance) |
| `max_disp` | derived | `round(3 × sqrt(4×estD/f_rate) / pixl)` |

#### Auto-threshold method

Instead of manually entering a threshold via the MATLAB GUI, the threshold is computed from the image:

1. Load the first frame
2. Apply the same bandpass filter as `spt_fndpos.m`: `bpass(frame, 1, dia+2, 0, 'single')`
3. Compute: `thresh = mean(filtered_pixels) + K × std(filtered_pixels)`

K values (matching `auto_roi_for_published_v2.7.py`):
- **K = 2.0** for green channel
- **K = 1.5** for red and purple channels

The threshold value is printed for every channel for QC.

#### Output

`spt_batch.m` saves `loci1_green.mat` (etc.) alongside the input TIFF. The `.mat` contains:
- `traj` — 1×N struct array of trajectories, each with `pos` (N×3: x_px, y_px, frame)
- `sptpara` — all parameters used (frame rate, pixel size, threshold, etc.)
- `im` — image attributes and bandpass-filtered image

**QC check:** Printed frame rate, pixel size, auto-threshold, and trajectory count per channel.

---

### Step 4 — Export trajectories to CSV

For each `.mat` file, reads the `traj` struct and writes one CSV per trajectory into a `matlab_trajectory/` subfolder inside the same `lociN/` directory.

#### CSV format

```
frame,x_nm,y_nm
1,183.45,220.11
2,185.02,219.87
...
```

- `frame`: 1-based integer frame number
- `x_nm`, `y_nm`: position in nanometres, converted from pixels using `pixl × 1000`

#### Naming convention

```
matlab_trajectory/{prefix}_loci{ROI}_m2DGaussian_traj{N}.csv
```

- `prefix`: G (green), R (red), P (purple)
- `ROI`: locus index from `RoiSet_green.zip`
- `m2DGaussian`: marks the sub-pixel fitting method used in spt.m
- `N`: trajectory index within the SPT output for that crop (1-based)

---

## Output Directory Structure

```
input_dir/
├── <stem>_green.tif              (original, untouched)
├── <stem>_red.tif
├── <stem>_purple.tif
├── <stem>_Nucleus.tif
├── RoiSet_green.zip              (from auto_roi)
├── G_loci1_trajectory.csv        (from auto_roi — ROI-relative coordinates)
├── ...
├── loci1/
│   ├── loci1_green.tif           (cropped, all frames)
│   ├── loci1_red.tif
│   ├── loci1_purple.tif
│   ├── loci1_Nucleus.tif
│   ├── loci1_green.mat           (spt output — contains sptpara with all params)
│   ├── loci1_red.mat
│   ├── loci1_purple.mat
│   └── matlab_trajectory/
│       ├── G_loci1_m2DGaussian_traj1.csv
│       ├── G_loci1_m2DGaussian_traj2.csv   (if SPT found 2 green trajectories)
│       ├── R_loci1_m2DGaussian_traj1.csv
│       └── P_loci1_m2DGaussian_traj1.csv
├── loci2/
│   └── ...
└── ...
```

**Note:** Coordinates in `G_loci1_trajectory.csv` (auto_roi output) are relative to the ROI top-left corner. Coordinates in `G_loci1_m2DGaussian_traj1.csv` (SPT output) are relative to the cropped image origin — which is the same corner, so the two sets are directly comparable.

---

## QC Checklist

| Step | What to verify |
|---|---|
| Step 1 | ROI count matches expected loci; bounding box sizes look reasonable |
| Step 2 | Crop dimensions match ROI size; frame count matches original |
| Step 3 | `frame_rate` ≈ 0.04 Hz (finterval ≈ 25 s); `pixl` ≈ 0.183 µm/px; threshold in a sensible range |
| Step 4 | CSVs have `frame,x_nm,y_nm` header; frame numbers are integers; coordinates are in hundreds of nm |

---

## File Dependencies

| File | Role | Modify? |
|---|---|---|
| `auto_roi_for_published_v2.7.py` | ROI detection and trajectory CSV (step 0) | No |
| `run_pipeline.py` | Pipeline orchestrator | Yes (tuning) |
| `spt_batch.m` | Headless MATLAB SPT | Yes (tuning) |
| `Single Particle Tracking/spt.m` | Original SPT (reference only) | No |
| `Single Particle Tracking/spt_fndpos.m` | Called by spt_batch.m | No |
| `Single Particle Tracking/spt_track.m` | Called by spt_batch.m | No |
| `Single Particle Tracking/Matlab Tools/bpass.m` | Bandpass filter | No |
| `Single Particle Tracking/Matlab Tools/pkfnd.m` | Peak finding | No |
| `Single Particle Tracking/Matlab Tools/centfind.m` | Sub-pixel centroid | No |
