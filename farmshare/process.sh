#!/usr/bin/env bash
#
# Template Slurm worker: process every raw TIFF in one data subfolder.
#
# Do not submit this file directly. Run launch_jobs.sh to render concrete
# farmshare/jobs/job_0.sh, job_1.sh, ... scripts, then submit those.

#SBATCH --job-name=__JOB_NAME__
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --partition=__PARTITION__
#SBATCH --time=__TIME__
#SBATCH --mem=__MEM__
#SBATCH --output=__LOG_DIR__/__JOB_NAME__-%j.out
#SBATCH --error=__LOG_DIR__/__JOB_NAME__-%j.err

set -euo pipefail

TIF_FOLDER=__TIF_FOLDER__
FORCE=__FORCE__

if [[ ! -d "$TIF_FOLDER" ]]; then
    printf 'ERROR: not a directory: %s\n' "$TIF_FOLDER" >&2
    exit 1
fi

REPO_ROOT=__REPO_ROOT__
PIPELINE_DIR="$REPO_ROOT/pipeline"
RUNNER="$PIPELINE_DIR/run_full_pipeline_v3.py"

mkdir -p "$REPO_ROOT/farmshare/logs"

# Farmshare modules vary a bit across environments. Keep going if Fiji is
# available as a command but not as a module.
module load matlab

cd "$PIPELINE_DIR"

printf 'Job started  : %s\n' "$(date)"
printf 'Host         : %s\n' "$(hostname)"
printf 'Slurm job id : %s\n' "${SLURM_JOB_ID:-manual}"
printf 'Job name     : %s\n' "__JOB_NAME__"
printf 'TIFF folder  : %s\n' "$TIF_FOLDER"
printf 'Runner       : %s\n' "$RUNNER"
printf '\n'

shopt -s nullglob
tifs=("$TIF_FOLDER"/*.tif "$TIF_FOLDER"/*.tiff "$TIF_FOLDER"/*.TIF "$TIF_FOLDER"/*.TIFF)
shopt -u nullglob

if [[ ${#tifs[@]} -eq 0 ]]; then
    printf 'ERROR: no TIFF files found in %s\n' "$TIF_FOLDER" >&2
    exit 1
fi

printf 'Found %d TIFF file(s).\n' "${#tifs[@]}"

processed=0
skipped=0
failed=0

for tif in "${tifs[@]}"; do
    analysis_dir=${tif%.*}

    printf '\n======================================================================\n'
    printf 'Input TIFF   : %s\n' "$tif"
    printf 'Analysis dir : %s\n' "$analysis_dir"
    printf '======================================================================\n'

    if [[ "$FORCE" -eq 0 && -f "$analysis_dir/log_trajectory_v3.txt" ]] &&
        grep -q 'Pipeline complete:' "$analysis_dir/log_trajectory_v3.txt"; then
        printf 'Skipping because log_trajectory_v3.txt shows a completed run. Use --force to rerun.\n'
        skipped=$((skipped + 1))
        continue
    fi

    if python3 "$RUNNER" "$tif"; then
        processed=$((processed + 1))
    else
        rc=$?
        failed=$((failed + 1))
        printf 'ERROR: pipeline failed for %s with exit code %d\n' "$tif" "$rc" >&2
    fi
done

printf '\n======================================================================\n'
printf 'Job finished : %s\n' "$(date)"
printf 'Processed    : %d\n' "$processed"
printf 'Skipped      : %d\n' "$skipped"
printf 'Failed       : %d\n' "$failed"
printf '======================================================================\n'

if [[ "$failed" -ne 0 ]]; then
    exit 1
fi
