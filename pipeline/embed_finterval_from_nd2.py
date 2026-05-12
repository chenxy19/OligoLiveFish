#!/usr/bin/env python3
"""
Embed ImageJ finterval metadata in TIFFs exported from matching ND2 files.

Expected layout:
    data/kenaj_nd2_tif/
      sample.nd2
      sample/
        sample_1.tif
        sample_2.tif

The script pairs each top-level ND2 with its sibling directory of the same stem,
infers the projected-frame interval from the ND2 AcqTimesCache, and writes
`finterval=<seconds>` into each direct TIFF in that directory.

Dry run by default:
    python3 embed_finterval_from_nd2.py /path/to/data/kenaj_nd2_tif

Apply changes:
    python3 embed_finterval_from_nd2.py /path/to/data/kenaj_nd2_tif --apply
"""

from __future__ import annotations

import argparse
import math
import mmap
import re
import shutil
import statistics
import struct
import sys
from pathlib import Path

from PIL import Image


ACQ_TIMES = b'CustomData|AcqTimesCache!'
ACQ_TIMES_2 = b'CustomData|AcqTimes2Cache!'


def _read_description(path: Path) -> str:
    with Image.open(path) as img:
        desc = img.tag_v2.get(270, '')
    if isinstance(desc, bytes):
        return desc.decode('utf-8', errors='replace')
    if isinstance(desc, tuple):
        return str(desc[0]) if desc else ''
    return str(desc)


def _read_imagej_shape(path: Path) -> tuple[int | None, int | None]:
    desc = _read_description(path)
    frames_m = re.search(r'(?m)^frames=([0-9]+)\s*$', desc)
    slices_m = re.search(r'(?m)^slices=([0-9]+)\s*$', desc)
    frames = int(frames_m.group(1)) if frames_m else None
    slices = int(slices_m.group(1)) if slices_m else None
    return frames, slices


def _extract_acq_time_ms(nd2_path: Path) -> list[float]:
    """Extract plausible millisecond timestamps from Nikon ND2 AcqTimesCache."""
    with nd2_path.open('rb') as fh:
        mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            start = mm.find(ACQ_TIMES)
            end = mm.find(ACQ_TIMES_2, start + 1) if start >= 0 else -1
            if start < 0 or end <= start:
                return []
            block = mm[start:end]
        finally:
            mm.close()

    values = []
    for i in range(0, len(block) - 7, 8):
        value = struct.unpack('<d', block[i:i + 8])[0]
        if math.isfinite(value) and 0 < value < 1e7:
            values.append(value)
    return values


def infer_frame_interval_s(nd2_path: Path, slices: int | None) -> tuple[float, dict]:
    """
    Infer projected-frame interval from ND2 plane timestamps.

    ND2 exports here store one timestamp per Z plane. The time between plane i
    and plane i + slices is therefore the projected frame-to-frame interval.
    """
    times = _extract_acq_time_ms(nd2_path)
    if not times:
        raise ValueError('AcqTimesCache not found or contained no timestamps')

    if not slices or slices <= 0:
        slices = 1

    raw_deltas_s = [
        (times[i + slices] - times[i]) / 1000.0
        for i in range(len(times) - slices)
        if times[i + slices] > times[i]
    ]
    # Keep biologically/acquisition-plausible projected frame intervals while
    # dropping partial-cache jumps or malformed double reads.
    deltas_s = [d for d in raw_deltas_s if 0.5 <= d <= 300.0]
    if not deltas_s:
        raise ValueError(
            f'not enough timestamps to infer interval with slices={slices}'
        )

    rough_interval = statistics.median(deltas_s)
    tolerance = max(2.0, rough_interval * 0.25)
    central_deltas_s = [
        d for d in deltas_s
        if abs(d - rough_interval) <= tolerance
    ]
    if central_deltas_s:
        deltas_s = central_deltas_s

    # ImageJ/Bio-Formats writes finterval as a scalar calibration value. For
    # irregular real timestamps, the filtered mean best reproduces that nominal
    # frame interval.
    interval = statistics.mean(deltas_s)
    return interval, {
        'n_timestamps': len(times),
        'n_raw_deltas': len(raw_deltas_s),
        'n_deltas': len(deltas_s),
        'median_delta': statistics.median(deltas_s),
        'min_delta': min(deltas_s),
        'max_delta': max(deltas_s),
        'slices': slices,
    }


def _updated_description(desc: str, finterval_s: float) -> str:
    line = f'finterval={finterval_s:.6g}'
    if re.search(r'(?m)^finterval=', desc):
        desc = re.sub(r'(?m)^finterval=.*$', line, desc)
    else:
        if desc and not desc.endswith('\n'):
            desc += '\n'
        desc += line + '\n'
    return desc


def _find_image_description_entry(fh) -> tuple[str, int]:
    """
    Return (endianness, entry_offset) for tag 270 in the first classic TIFF IFD.

    ImageJ stores the hyperstack description in the first IFD. Updating only
    this entry keeps the original TIFF pages, byte order, IJMetadata tags, and
    Fiji-readable layout intact.
    """
    fh.seek(0)
    header = fh.read(8)
    if len(header) != 8:
        raise ValueError('not a TIFF file')
    if header[:2] == b'II':
        endian = '<'
    elif header[:2] == b'MM':
        endian = '>'
    else:
        raise ValueError('not a TIFF file')
    if struct.unpack(endian + 'H', header[2:4])[0] != 42:
        raise ValueError('BigTIFF is not supported by the in-place tag updater')

    ifd_offset = struct.unpack(endian + 'I', header[4:8])[0]
    fh.seek(ifd_offset)
    n_entries_raw = fh.read(2)
    if len(n_entries_raw) != 2:
        raise ValueError('could not read first TIFF IFD')
    n_entries = struct.unpack(endian + 'H', n_entries_raw)[0]

    for i in range(n_entries):
        entry_offset = ifd_offset + 2 + i * 12
        fh.seek(entry_offset)
        entry = fh.read(12)
        if len(entry) != 12:
            raise ValueError('could not read TIFF IFD entry')
        tag = struct.unpack(endian + 'H', entry[:2])[0]
        if tag == 270:
            return endian, entry_offset

    raise ValueError('ImageDescription tag 270 not found')


def _patch_image_description(tif_path: Path, description: str) -> None:
    desc_bytes = description.encode('utf-8') + b'\0'
    with tif_path.open('r+b') as fh:
        endian, entry_offset = _find_image_description_entry(fh)

        fh.seek(0, 2)
        desc_offset = fh.tell()
        fh.write(desc_bytes)

        fh.seek(entry_offset + 2)
        fh.write(struct.pack(endian + 'H', 2))  # ASCII
        fh.write(struct.pack(endian + 'I', len(desc_bytes)))
        fh.write(struct.pack(endian + 'I', desc_offset))


def embed_finterval(
    tif_path: Path,
    finterval_s: float,
    backup: bool,
    overwrite: bool = False,
) -> bool:
    old_desc = _read_description(tif_path)
    if not overwrite and re.search(r'(?m)^finterval=', old_desc):
        return False
    new_desc = _updated_description(old_desc, finterval_s)
    if new_desc == old_desc:
        return False

    if backup:
        backup_path = tif_path.with_name(tif_path.name + '.bak')
        if not backup_path.exists():
            shutil.copy2(tif_path, backup_path)

    _patch_image_description(tif_path, new_desc)
    return True


def process_pair(
    nd2_path: Path,
    tif_dir: Path,
    apply: bool,
    backup: bool,
    overwrite: bool,
) -> int:
    tifs = sorted(tif_dir.glob('*.tif')) + sorted(tif_dir.glob('*.tiff'))
    if not tifs:
        print(f'[SKIP] {nd2_path.name}: no direct TIFFs in {tif_dir}')
        return 0

    frames, slices = _read_imagej_shape(tifs[0])
    interval, details = infer_frame_interval_s(nd2_path, slices)
    print(
        f'{nd2_path.name}\n'
        f'  TIFF dir      : {tif_dir}\n'
        f'  TIFF shape    : frames={frames}, slices={details["slices"]}\n'
        f'  ND2 timestamps: {details["n_timestamps"]}; '
        f'deltas={details["n_deltas"]}/{details["n_raw_deltas"]}; '
        f'range={details["min_delta"]:.3f}-{details["max_delta"]:.3f} s; '
        f'median={details["median_delta"]:.3f} s\n'
        f'  finterval     : {interval:.6g} s (filtered mean)\n'
        f'  TIFFs         : {len(tifs)}'
    )

    if not apply:
        return len(tifs)

    changed = 0
    for tif in tifs:
        if embed_finterval(tif, interval, backup=backup, overwrite=overwrite):
            changed += 1
    print(f'  updated       : {changed}/{len(tifs)}')
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Embed ND2-derived finterval metadata into exported TIFFs.'
    )
    parser.add_argument(
        'root',
        type=Path,
        help='Directory containing top-level .nd2 files and matching TIFF folders.',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Actually rewrite TIFF files. Without this, only prints planned edits.',
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        help='Before rewriting, create <file>.bak next to each TIFF if absent.',
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Replace existing finterval lines. By default, TIFFs that already have finterval are left unchanged.',
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f'not a directory: {root}')

    nd2_paths = sorted(root.glob('*.nd2'))
    if not nd2_paths:
        parser.error(f'no top-level .nd2 files found in {root}')

    total = 0
    for nd2_path in nd2_paths:
        tif_dir = root / nd2_path.stem
        if not tif_dir.is_dir():
            print(f'[SKIP] {nd2_path.name}: missing TIFF folder {tif_dir.name}')
            continue
        try:
            total += process_pair(
                nd2_path, tif_dir, args.apply, args.backup, args.overwrite
            )
        except Exception as exc:
            print(f'[ERROR] {nd2_path.name}: {exc}', file=sys.stderr)

    mode = 'updated' if args.apply else 'would update'
    print(f'\nDone: {mode} {total} TIFF file(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
