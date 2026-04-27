# LIVEFISH Analysis Pipeline — v2.12

Automated reference-trajectory extraction and single-particle tracking (SPT) pipeline for live-cell FISH imaging. Tracks DNA loci labelled with green (reference), red, and purple fluorophores across 30-frame time-lapse acquisitions.

---

## Table of Contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [Input files](#input-files)
4. [Pipeline scripts](#pipeline-scripts)
5. [Running the pipeline](#running-the-pipeline)
6. [Parameters](#parameters)
7. [Output files](#output-files)
8. [Algorithm details](#algorithm-details)
9. [Utility scripts](#utility-scripts)

---

## Overview

The pipeline has three stages:

```
Stage 1  auto_roi_for_published_v2.12.py
         ↳ Detects green loci, tracks green/purple/red reference trajectories,
           saves per-locus reference CSVs.

Stage 2  run_pipeline_v2.py
         ↳ Calls MATLAB spt_batch.m on each channel TIFF → .mat files,
           then exports every MATLAB trajectory to CSV.

Stage 3  match_m2DGaussian_to_reference.py
         ↳ Matches each MATLAB trajectory to the reference track of the same
           locus by spatial overlap, saves the cleaned final trajectory.
```

The full pipeline (all three stages) is orchestrated by `run_full_pipeline_v2.12.py`. Multiple datasets can be processed simultaneously using `run_parallel_v2.12.py`.

---

## Requirements

### Python packages

```
Pillow==12.1.0
numpy==2.4.2
scipy==1.17.1
```

Install with:

```bash
pip install -r requirements.txt
```

All other imports (`csv`, `math`, `pathlib`, `subprocess`, `struct`, `zipfile`, `re`, `collections`, `datetime`) are Python standard library.

### External dependency

**MATLAB** with the `spt_batch.m` Single Particle Tracking toolbox must be installed and accessible at:

```
/Applications/MATLAB_R2026a.app/bin/matlab
```

The SPT toolbox directory is hardcoded in `run_pipeline_v2.py`:

```python
SPT_DIR       = Path('/Users/chenxinyi/Desktop/LIVEFISH analysis/Single Particle Tracking')
SPT_TOOLS_DIR = SPT_DIR / 'Matlab Tools'
```

---

## Input files

Each analysis directory must contain the following files with a common stem `<stem>`:

| File | Description |
|------|-------------|
| `<stem>_Nucleus.tif` | Multi-frame nucleus channel (Hoechst/DAPI), used for nucleus boundary masking |
| `<stem>_green.tif` | Multi-frame green channel (reference locus marker) |
| `<stem>_red.tif` | Multi-frame red channel (locus of interest) |
| `<stem>_purple.tif` | Multi-frame purple channel (locus of interest) |

All TIFFs must carry ImageJ-format metadata with `finterval` (frame interval in seconds) and `XResolution` (pixels per µm) tags.

---

## Pipeline scripts

| Script | Role |
|--------|------|
| `auto_roi_for_published_v2.12.py` | Stage 1 — reference trajectory extraction |
| `run_pipeline_v2.py` | Stage 2 — MATLAB SPT + CSV export |
| `match_m2DGaussian_to_reference.py` | Stage 3 — trajectory matching and final output |
| `run_full_pipeline_v2.12.py` | Runs all three stages sequentially for one dataset |
| `run_parallel_v2.12.py` | Runs all three stages in parallel for all 5 datasets |
| `clean_outputs.py` | Deletes stale output CSVs before a fresh run |

---

## Running the pipeline

### Single dataset

```bash
python3 run_full_pipeline_v2.12.py "<path_to_analysis_dir>"
```

Example:

```bash
python3 run_full_pipeline_v2.12.py \
  "/Users/chenxinyi/Desktop/LIVEFISH analysis/published/published_3/FOV5_analyzed_1_copy12_count/try_analysis"
```

A log file `log_trajectory_v2.12.txt` is written to the analysis directory.

### All 5 datasets in parallel

```bash
# Step 1 — remove stale outputs from previous runs
python3 clean_outputs.py

# Step 2 — run all 5 pipelines simultaneously
python3 run_parallel_v2.12.py
```

Each dataset writes its own `log_trajectory_v2.12.txt`. The terminal prints a one-line summary per dataset when all finish.

---

## Parameters

All tunable parameters are at the top of `auto_roi_for_published_v2.12.py`.

### Detection thresholds

| Parameter | Default | Description |
|-----------|---------|-------------|
| `K_SIGNAL['green']` | `2.0` | Threshold multiplier for green channel: `mean + k × std` |
| `K_SIGNAL['red']` | `0.5` | Threshold multiplier for red channel |
| `K_SIGNAL['purple']` | `0.5` | Threshold multiplier for purple channel |

### Nucleus masking

| Parameter | Default | Description |
|-----------|---------|-------------|
| `NUCLEUS_SIGMA` | `2.0` | Gaussian blur σ (px) before Otsu thresholding of nucleus channel |
| `NUCLEUS_OUTSIDE_FRAC` | `0.10` | Maximum fraction of frames a green locus may be outside the nucleus before it is rejected |
| `FILL_RATIO` | `0.85` | Drift-correction fill detection: pixels below `75th-percentile × FILL_RATIO` on the image border are masked as fill |

### Spot detection

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MIN_SPOT_PX` | `10` | Minimum connected-component area (px) for a candidate to be accepted |
| `N_MAX` | `5` | Maximum number of green loci to detect |
| `PADDING` | `20` | Pixels added around the green trajectory bounding box on each side to define the per-locus ROI |

### Tracking constraints

| Parameter | Default | Description |
|-----------|---------|-------------|
| `PIXEL_SIZE_UM` | `5.45` | Pixel size in px/µm (read from TIFF metadata; used to convert nm ↔ px) |
| `INTER_FRAME_MAX_NM` | `500` | Maximum frame-to-frame displacement (nm) for purple tracking |
| `INTER_FRAME_MAX_NM_RED` | `750` | Maximum frame-to-frame displacement (nm) for red tracking (relaxed; red loci are more mobile) |
| `GREEN_PROX_MAX_UM` | `3.0` | Maximum distance (µm) from the green locus for a purple/red candidate to be accepted |
| `SEED_MAX_FRAME` | `5` | Number of early frames searched to find the initial seed position |

### Adaptive k for merged blobs (overlap groups only)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_BLOB_PX` | `120` | Connected-component area threshold (px) above which a blob is considered potentially merged |
| `_ADAPTIVE_K_STEPS` | `[1.0, 1.5, 2.0]` | Progressive k values tried to split a large blob into sub-components |

### Matching (Stage 3)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MIN_OVERLAP_FRAMES` | `5` | Minimum shared frames between reference and MATLAB trajectory for a match to be considered |
| `MAX_AVG_DIST_NM` | `2000` | Maximum average distance (nm) between matched trajectories; pairs exceeding this are rejected |

---

## Output files

All output files are written to the analysis directory.

### From Stage 1

| File | Description |
|------|-------------|
| `Nucleus_masks.tif` | Per-frame binary nucleus masks |
| `RoiSet_green.zip` | ImageJ ROI zip containing the per-locus green bounding boxes |
| `G_loci{N}_traj_rela2wholeimg.csv` | Green reference trajectory for locus N (whole-image coordinates) |
| `P_loci{N}_traj_rela2wholeimg.csv` | Purple reference trajectory for locus N |
| `R_loci{N}_traj_rela2wholeimg.csv` | Red reference trajectory for locus N |

### From Stage 2

| File | Description |
|------|-------------|
| `matlab_result/<stem>_green.mat` | MATLAB SPT output for green channel |
| `matlab_result/<stem>_red.mat` | MATLAB SPT output for red channel |
| `matlab_result/<stem>_purple.mat` | MATLAB SPT output for purple channel |
| `matlab_result/matlab_trajectory/G_m2DGaussian_traj{N}.csv` | Individual MATLAB-tracked green trajectories |
| `matlab_result/matlab_trajectory/R_m2DGaussian_traj{N}.csv` | Individual MATLAB-tracked red trajectories |
| `matlab_result/matlab_trajectory/P_m2DGaussian_traj{N}.csv` | Individual MATLAB-tracked purple trajectories |

### From Stage 3 (final outputs)

| File | Description |
|------|-------------|
| `G_loci{N}_traj_m2DGaussian_cleaned.csv` | Final green trajectory for locus N |
| `P_loci{N}_traj_m2DGaussian_cleaned.csv` | Final purple trajectory for locus N |
| `R_loci{N}_traj_m2DGaussian_cleaned.csv` | Final red trajectory for locus N |

All trajectory CSVs have three columns: `frame` (1-indexed), `x_nm`, `y_nm`.

### Log file

| File | Description |
|------|-------------|
| `log_trajectory_v2.12.txt` | Full console output from all three stages |

---

## Algorithm details

### Stage 1 — Reference trajectory extraction

**Pass 1 — Green tracking**

1. The time-averaged green image is thresholded at `mean + K_SIGNAL['green'] × std` to detect up to `N_MAX` green loci clusters.
2. Each cluster is tracked frame-by-frame across the stack using a nearest-neighbour approach anchored to the cluster centroid.
3. Loci whose tracked positions are outside the nucleus mask in more than `NUCLEUS_OUTSIDE_FRAC` of frames are rejected.
4. Each accepted locus gets a bounding-box ROI: the convex hull of its trajectory ± `PADDING` pixels.

**Overlap detection**

ROIs that overlap by more than `ADJACENCY_PX` pixels are grouped. Loci in the same group share a union ROI for seed finding (joint seeding). Loci with no overlap are tracked independently (singletons).

**Pass 2 — Purple and red tracking**

*Overlap groups — joint seeding:*

1. A union mask is computed from all ROIs in the group.
2. Candidates are detected in each seed frame within the union mask. Large connected components (area > `MAX_BLOB_PX`) are re-examined locally at higher k values (`_ADAPTIVE_K_STEPS = [1.0, 1.5, 2.0]`) to split potentially merged blobs. Other components keep the base-k detection.
3. Candidates are linked greedily across seed frames into seed trajectories (inter-frame gap ≤ 1 frame, displacement ≤ inter-frame limit).
4. Seed trajectories are assigned to loci one-to-one using the Hungarian algorithm (minimising average distance to each locus's green trajectory).
5. Each assigned seed trajectory is then propagated forward through the full stack from `propagate_from_seed`:
   - **Primary**: accept a candidate that is within the inter-frame displacement limit AND within `GREEN_PROX_MAX_UM` of the green locus.
   - **Fallback**: if no candidate passes the inter-frame constraint, accept the candidate closest to the green locus (within `GREEN_PROX_MAX_UM`). This handles highly mobile loci whose frame-to-frame displacement exceeds the limit but whose signal stays near the green anchor.

*Singletons — standard tracking:*

`track_channel_in_roi` applies the same primary + fallback logic as above, starting from a seed found in the first `SEED_MAX_FRAME` frames.

### Stage 2 — MATLAB SPT

MATLAB `spt_batch.m` runs 2D-Gaussian fitting on the full-field channel TIFFs to detect and link sub-diffraction spots independently of any ROI. Parameters are set automatically from the TIFF metadata. Each channel produces a `.mat` file whose trajectories are then exported to individual CSVs.

### Stage 3 — Trajectory matching

For each reference locus track (from Stage 1), the best-matching MATLAB trajectory (from Stage 2) of the same channel is found by:

1. Computing the average Euclidean distance between the two tracks over all shared frames.
2. Requiring at least `MIN_OVERLAP_FRAMES` shared frames.
3. Performing greedy one-to-one assignment (lowest average distance first).
4. Rejecting pairs whose average distance exceeds `MAX_AVG_DIST_NM`.
5. **For red channel only**: rejecting matched MATLAB trajectories that have no points in frames 1–3 (1-indexed), as these indicate the track started too late to be reliable.

The matched MATLAB trajectory is written as the final `*_traj_m2DGaussian_cleaned.csv`.

---

## Utility scripts

| Script | Description |
|--------|-------------|
| `clean_outputs.py` | Deletes `*_cleaned.csv` and `*_rela2wholeimg.csv` from all 5 analysis directories before a fresh run |
| `troubleshoot_loci2_red.py` | Frame-by-frame diagnostic for red singleton tracking; saves PNG overlays per frame to `diag_loci2_red/` |
| `troubleshoot_merged_purple.py` | Tests four methods for separating merged purple blobs; read-only, no pipeline files modified |
