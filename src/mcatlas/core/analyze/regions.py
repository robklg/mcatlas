"""Region-header facts: chunk counts, extent, save times and a history signature.

Only the 8 KiB header of each region file is read, in one batch per dimension so the source
adapter can fetch them concurrently (latency, not bandwidth, dominates over SMB).
"""

import base64
from collections import Counter

import numpy as np
from numpy.typing import NDArray

from mcatlas.core.anvil.region import HEADER_SIZE, parse_header
from mcatlas.core.dedupe import chunk_keys, dimension_code, minhash
from mcatlas.core.discovery import parse_region_name
from mcatlas.core.facts import DimensionFacts, RegionFacts
from mcatlas.core.model import DimensionLayout, WorldFiles, WorldLayout
from mcatlas.core.npx import value_counts


def _dimension(
    files: WorldFiles, dim: DimensionLayout, keys: list[NDArray[np.uint64]], errors: list[str]
) -> DimensionFacts:
    code = dimension_code(dim.key)
    hours: Counter[int] = Counter()
    footprint: dict[str, str] = {}
    chunks = empty = 0
    min_x = min_z = max_x = max_z = 0
    have_bbox = False

    readable: list[tuple[str, int, int]] = []
    for f in dim.region_files:
        parsed = parse_region_name(f.relpath.rsplit("/", 1)[-1])
        if parsed is None:
            continue
        if f.size < HEADER_SIZE:
            empty += 1
        else:
            readable.append((f.relpath, parsed[0], parsed[1]))

    blobs = files.read_ranges([(rel, 0, HEADER_SIZE) for rel, _, _ in readable])
    for (rel, region_x, region_z), blob in zip(readable, blobs, strict=True):
        if isinstance(blob, OSError):
            errors.append(f"{rel}: {blob}")
            continue
        header = parse_header(blob, region_x, region_z)
        if header is None or header.chunk_count == 0:
            empty += 1
            continue
        xs, zs = header.chunk_coords()
        bits = np.packbits(header.present).tobytes()
        footprint[f"{region_x},{region_z}"] = base64.b64encode(bits).decode("ascii")
        ts = header.timestamps[header.present]
        chunks += int(xs.size)
        lo_x, lo_z, hi_x, hi_z = int(xs.min()), int(zs.min()), int(xs.max()), int(zs.max())
        if have_bbox:
            min_x, min_z = min(min_x, lo_x), min(min_z, lo_z)
            max_x, max_z = max(max_x, hi_x), max(max_z, hi_z)
        else:
            min_x, min_z, max_x, max_z, have_bbox = lo_x, lo_z, hi_x, hi_z, True
        saved = ts[ts > 0]
        hours.update(value_counts(saved // 3600))
        keys.append(chunk_keys(code, xs, zs, ts))

    return DimensionFacts(
        key=dim.key,
        region_files=len(dim.region_files),
        empty_region_files=empty,
        chunks=chunks,
        bbox_chunks=(min_x, min_z, max_x, max_z) if have_bbox else None,
        chunk_saves_by_hour=dict(sorted(hours.items())),
        footprint=dict(sorted(footprint.items())),
    )


def analyze_regions(files: WorldFiles, layout: WorldLayout) -> RegionFacts:
    keys: list[NDArray[np.uint64]] = []
    errors: list[str] = []
    dims = [_dimension(files, d, keys, errors) for d in layout.dimensions]
    signature = minhash(np.concatenate(keys)) if keys else []
    return RegionFacts(dimensions=dims, minhash=signature, errors=errors)
