"""Analyse a DICOM SEG file to extract per-segment volume and best-slice info."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pydicom


@dataclass
class SegmentInfo:
    segment_number: int
    label: str
    volume_mm3: float
    volume_ml: float
    best_slice_index: int
    best_slice_z: float


def analyze_seg(seg_path: Path) -> list[SegmentInfo]:
    """Parse a SEG DICOM and return per-segment metrics.

    Returns segments ordered by segment_number (1-based).
    best_slice_index is the 1-based frame position within the segment's
    frames where the lesion cross-section is largest.
    """
    ds = pydicom.dcmread(str(seg_path), stop_before_pixels=False)
    pixel_array = ds.pixel_array  # (num_frames, rows, cols)

    frame0 = ds.PerFrameFunctionalGroupsSequence[0]
    pm = frame0.PixelMeasuresSequence[0]
    pixel_spacing = pm.PixelSpacing
    spacing_between = float(getattr(pm, "SpacingBetweenSlices", pm.SliceThickness))
    voxel_vol = float(pixel_spacing[0]) * float(pixel_spacing[1]) * spacing_between

    seg_frame_map: dict[int, list[int]] = {}
    for j, frame in enumerate(ds.PerFrameFunctionalGroupsSequence):
        seg_id = int(frame.SegmentIdentificationSequence[0].ReferencedSegmentNumber)
        seg_frame_map.setdefault(seg_id, []).append(j)

    results: list[SegmentInfo] = []
    for seg_num in sorted(seg_frame_map):
        frames = seg_frame_map[seg_num]
        mask_frames = pixel_array[frames]
        voxel_count = int(np.sum(mask_frames > 0))
        vol_mm3 = voxel_count * voxel_vol

        areas = [int(np.sum(mask_frames[i] > 0)) for i in range(len(frames))]
        best_local = int(np.argmax(areas))
        best_frame_idx = frames[best_local]

        best_frame = ds.PerFrameFunctionalGroupsSequence[best_frame_idx]
        z_pos = float(best_frame.PlanePositionSequence[0].ImagePositionPatient[2])

        results.append(
            SegmentInfo(
                segment_number=seg_num,
                label=str(ds.SegmentSequence[seg_num - 1].SegmentLabel),
                volume_mm3=vol_mm3,
                volume_ml=vol_mm3 / 1000.0,
                best_slice_index=best_local + 1,
                best_slice_z=z_pos,
            )
        )

    return results
