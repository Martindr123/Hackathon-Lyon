"""Extract Hounsfield-Unit statistics from CT slices under a DICOM SEG mask.

For each segment the function returns (mean_HU, std_HU, heterogeneity_index).
The heterogeneity index is the coefficient of variation: std / |mean|.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pydicom

logger = logging.getLogger(__name__)


@dataclass
class HUStats:
    segment_number: int
    mean: float
    std: float
    heterogeneity_index: float


def _build_ct_z_map(
    ct_files: list[Path],
) -> dict[float, np.ndarray]:
    """Read CT slices and index them by rounded z-position.

    Returns {z_position: pixel_array} where pixel_array stores raw stored
    values (RescaleSlope/Intercept are applied when sampling).
    """
    z_map: dict[float, tuple[np.ndarray, float, float]] = {}
    for f in ct_files:
        ds = pydicom.dcmread(str(f), stop_before_pixels=False)
        z = round(float(ds.ImagePositionPatient[2]), 2)
        slope = float(getattr(ds, "RescaleSlope", 1))
        intercept = float(getattr(ds, "RescaleIntercept", 0))
        z_map[z] = (ds.pixel_array, slope, intercept)
    return z_map


def compute_heterogeneity(
    seg_path: Path,
    ct_files: list[Path],
) -> list[HUStats]:
    """Compute per-segment HU statistics by overlaying SEG masks on CT slices.

    Segments whose mask does not overlap any CT slice are silently skipped.
    """
    if not ct_files:
        return []

    seg_ds = pydicom.dcmread(str(seg_path), stop_before_pixels=False)
    seg_array = seg_ds.pixel_array

    ct_z_map = _build_ct_z_map(ct_files)

    seg_frame_map: dict[int, list[int]] = {}
    for j, frame in enumerate(seg_ds.PerFrameFunctionalGroupsSequence):
        seg_id = int(frame.SegmentIdentificationSequence[0].ReferencedSegmentNumber)
        seg_frame_map.setdefault(seg_id, []).append(j)

    results: list[HUStats] = []
    for seg_num in sorted(seg_frame_map):
        hu_values: list[float] = []
        for frame_idx in seg_frame_map[seg_num]:
            mask_2d = seg_array[frame_idx]
            frame_meta = seg_ds.PerFrameFunctionalGroupsSequence[frame_idx]
            z = round(float(frame_meta.PlanePositionSequence[0].ImagePositionPatient[2]), 2)

            ct_entry = ct_z_map.get(z)
            if ct_entry is None:
                nearest_z = min(ct_z_map.keys(), key=lambda k: abs(k - z), default=None)
                if nearest_z is not None and abs(nearest_z - z) < 1.5:
                    ct_entry = ct_z_map[nearest_z]

            if ct_entry is None:
                continue

            ct_pixels, slope, intercept = ct_entry
            foreground = mask_2d > 0
            if not np.any(foreground):
                continue

            raw = ct_pixels[foreground].astype(np.float64)
            hu = raw * slope + intercept
            hu_values.extend(hu.tolist())

        if len(hu_values) < 2:
            continue

        arr = np.array(hu_values)
        mean_hu = float(np.mean(arr))
        std_hu = float(np.std(arr, ddof=1))
        het_idx = std_hu / abs(mean_hu) if abs(mean_hu) > 1e-6 else 0.0

        results.append(
            HUStats(
                segment_number=seg_num,
                mean=round(mean_hu, 1),
                std=round(std_hu, 1),
                heterogeneity_index=round(het_idx, 3),
            )
        )

    return results
