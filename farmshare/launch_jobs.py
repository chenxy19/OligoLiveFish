"""
Render one standalone Slurm job script per TIFF folder.

This intentionally does not submit anything. Inspect the generated scripts in
farmshare/jobs/, then submit manually with:

    sbatch farmshare/jobs/job_0.sh
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import stat
from pathlib import Path


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    parser = argparse.ArgumentParser(
        description="Generate Slurm job scripts for OligoLiveFish TIFF folders."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=repo_root / "data",
        help="Directory containing one subfolder per TIFF group. Default: ../data.",
    )
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        default=script_dir / "jobs",
        help="Output directory for job_0.sh, job_1.sh, ... Default: farmshare/jobs.",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=script_dir / "process.sh",
        help="Template process script. Default: farmshare/process.sh.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Generate at most N job scripts. Default: 0 means no limit.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Render jobs that rerun TIFFs even when completed logs exist.",
    )
    parser.add_argument("--partition", default="normal", help="Slurm partition.")
    parser.add_argument("--time", default="24:00:00", help="Slurm time limit.")
    parser.add_argument("--mem", default="16G", help="Slurm memory request.")
    parser.add_argument(
        "--prefix",
        default="oligo",
        help="Prefix for Slurm job names. Default: oligo.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing job_*.sh files in --jobs-dir before rendering.",
    )
    return parser.parse_args()


def safe_job_name(name: str, prefix: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-")
    if not safe:
        safe = "folder"
    return f"{prefix}-{safe}"[:100]


def has_tiffs(folder: Path) -> bool:
    suffixes = {".tif", ".tiff"}
    return any(p.is_file() and p.suffix.lower() in suffixes for p in folder.iterdir())


def tiff_folders(data_dir: Path) -> list[Path]:
    return sorted(
        folder
        for folder in data_dir.iterdir()
        if folder.is_dir() and has_tiffs(folder)
    )


def render_template(template: str, replacements: dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"__{key}__", value)
    missing = sorted(set(re.findall(r"__[A-Z0-9_]+__", rendered)))
    if missing:
        raise ValueError(f"Unreplaced template placeholder(s): {', '.join(missing)}")
    return rendered


def make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> None:
    args = parse_args()

    data_dir = args.data_dir.resolve()
    jobs_dir = args.jobs_dir.resolve()
    template_path = args.template.resolve()
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.resolve()
    log_dir = (script_dir / "logs").resolve()

    if not data_dir.is_dir():
        raise SystemExit(f"ERROR: data directory not found: {data_dir}")
    if not template_path.is_file():
        raise SystemExit(f"ERROR: template not found: {template_path}")

    template = template_path.read_text()
    folders = tiff_folders(data_dir)
    if args.limit > 0:
        folders = folders[: args.limit]

    jobs_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    if args.clean:
        for old_job in jobs_dir.glob("job_*.sh"):
            old_job.unlink()

    manifest_path = jobs_dir / "manifest.tsv"
    manifest_rows = ["job_index\tjob_script\tjob_name\ttif_folder\n"]

    for idx, folder in enumerate(folders):
        job_name = safe_job_name(folder.name, args.prefix)
        job_script = jobs_dir / f"job_{idx}.sh"
        rendered = render_template(
            template,
            {
                "JOB_NAME": job_name,
                "PARTITION": args.partition,
                "TIME": args.time,
                "MEM": args.mem,
                "LOG_DIR": shlex.quote(os.fspath(log_dir)),
                "TIF_FOLDER": shlex.quote(os.fspath(folder.resolve())),
                "FORCE": "1" if args.force else "0",
                "REPO_ROOT": shlex.quote(os.fspath(repo_root)),
            },
        )
        job_script.write_text(rendered)
        make_executable(job_script)
        manifest_rows.append(
            f"{idx}\t{job_script}\t{job_name}\t{folder.resolve()}\n"
        )

    manifest_path.write_text("".join(manifest_rows))

    print(f"Rendered {len(folders)} job script(s) in {jobs_dir}")
    print(f"Manifest: {manifest_path}")
    if folders:
        print()
        print("Submit manually, for example:")
        print(f"  sbatch {jobs_dir / 'job_0.sh'}")
        print()
        print("Or submit all generated jobs:")
        print(f"  for job in {jobs_dir}/job_*.sh; do sbatch \"$job\"; done")


if __name__ == "__main__":
    main()
