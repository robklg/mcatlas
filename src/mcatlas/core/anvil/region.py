"""Region file header decoding.

A region file starts with two 4 KiB tables of 1024 big-endian entries, one per chunk slot
(index = local_x + 32 * local_z):

* locations: 3-byte sector offset + 1-byte sector count (0/0 = chunk absent)
* timestamps: 4-byte Unix seconds of the chunk's last save

The layout is the same for Anvil (.mca) and McRegion (.mcr).
"""

from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

HEADER_SIZE: Final = 8192
SECTOR: Final = 4096
CHUNKS_PER_REGION: Final = 1024


@dataclass(frozen=True, slots=True)
class RegionHeader:
    region_x: int
    region_z: int
    offsets: NDArray[np.int64]
    """Sector offset per slot (0 = absent)."""
    sectors: NDArray[np.int64]
    timestamps: NDArray[np.int64]
    """Unix seconds per slot (0 = never saved / absent)."""

    @property
    def present(self) -> NDArray[np.bool_]:
        return (self.offsets >= 2) & (self.sectors > 0)

    @property
    def chunk_count(self) -> int:
        return int(np.count_nonzero(self.present))

    def chunk_coords(self) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        """Absolute chunk (x, z) coordinates of the present chunks."""
        idx = np.flatnonzero(self.present).astype(np.int64)
        return self.region_x * 32 + idx % 32, self.region_z * 32 + idx // 32

    def present_timestamps(self) -> NDArray[np.int64]:
        """Save timestamps of present chunks that carry one."""
        ts = self.timestamps[self.present]
        return ts[ts > 0]


def parse_header(data: bytes, region_x: int, region_z: int) -> RegionHeader | None:
    """Decode the 8 KiB header; None if the file is too short to hold one (e.g. zero bytes)."""
    if len(data) < HEADER_SIZE:
        return None
    locations = np.frombuffer(data, dtype=">u4", count=CHUNKS_PER_REGION, offset=0)
    timestamps = np.frombuffer(data, dtype=">u4", count=CHUNKS_PER_REGION, offset=SECTOR)
    locations = locations.astype(np.int64)
    return RegionHeader(
        region_x=region_x,
        region_z=region_z,
        offsets=locations >> 8,
        sectors=locations & 0xFF,
        timestamps=timestamps.astype(np.int64),
    )
