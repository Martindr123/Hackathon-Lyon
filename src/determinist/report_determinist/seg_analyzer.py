"""Analyse a DICOM SEG file to extract per-segment volume, diameters and best-slice info."""

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
    best_slice_index: int  # 1-based within segment's frames (for display)
    best_slice_global_index: int  # 0-based index in SEG/CT series for aggregation
    best_slice_z: float
    longest_diameter_mm: float
    short_axis_mm: float


def _diameters(
    mask_2d: np.ndarray, pixel_spacing: tuple[float, float]
) -> tuple[float, float]:
    """Compute longest diameter and perpendicular short axis (mm) of a 2D binary mask.

    The longest diameter is the maximum pairwise distance among convex-hull
    vertices.  The short axis is the width of the mask measured perpendicular
    to the longest-diameter direction, which matches the RECIST convention for
    lymph-node measurement.
    """
    ys, xs = np.where(mask_2d > 0)
    if len(ys) < 2:
        return 0.0, 0.0

    coords_mm = np.column_stack(
        [
            xs.astype(np.float64) * pixel_spacing[1],
            ys.astype(np.float64) * pixel_spacing[0],
        ]
    )

    try:
        from scipy.spatial import ConvexHull

        hull = ConvexHull(coords_mm)
        hull_pts = coords_mm[hull.vertices]
    except Exception:
        hull_pts = coords_mm

    if len(hull_pts) < 2:
        return 0.0, 0.0

    # --- longest diameter via rotating calipers on hull ---
    max_dist_sq = 0.0
    best_i, best_j = 0, 1
    for i in range(len(hull_pts)):
        diffs = hull_pts[i + 1 :] - hull_pts[i]
        dists_sq = np.sum(diffs**2, axis=1)
        if len(dists_sq) > 0:
            idx = int(np.argmax(dists_sq))
            if dists_sq[idx] > max_dist_sq:
                max_dist_sq = dists_sq[idx]
                best_i = i
                best_j = i + 1 + idx

    longest = float(np.sqrt(max_dist_sq))
    if longest < 1e-6:
        return 0.0, 0.0

    # --- short axis: project ALL foreground points onto the perpendicular ---
    direction = hull_pts[best_j] - hull_pts[best_i]
    perp = np.array([-direction[1], direction[0]])
    perp /= np.linalg.norm(perp)

    projections = coords_mm @ perp
    short_axis = float(projections.max() - projections.min())

    return round(longest, 1), round(short_axis, 1)


def analyze_seg(seg_path: Path) -> list[SegmentInfo]:
    """Parse a SEG DICOM and return per-segment metrics.

    Returns segments ordered by segment_number (1-based).
    best_slice_index is the 1-based frame position within the segment's
    frames where the lesion cross-section is largest.
    longest_diameter_mm and short_axis_mm are computed on that best slice.
    """
    ds = pydicom.dcmread(str(seg_path), stop_before_pixels=False)
    pixel_array = ds.pixel_array  # (num_frames, rows, cols)

    frame0 = ds.PerFrameFunctionalGroupsSequence[0]
    pm = frame0.PixelMeasuresSequence[0]
    pixel_spacing = (float(pm.PixelSpacing[0]), float(pm.PixelSpacing[1]))
    spacing_between = float(getattr(pm, "SpacingBetweenSlices", pm.SliceThickness))
    voxel_vol = pixel_spacing[0] * pixel_spacing[1] * spacing_between

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

        longest, short = _diameters(mask_frames[best_local], pixel_spacing)

        results.append(
            SegmentInfo(
                segment_number=seg_num,
                label=str(ds.SegmentSequence[seg_num - 1].SegmentLabel),
                volume_mm3=vol_mm3,
                volume_ml=vol_mm3 / 1000.0,
                best_slice_index=best_local + 1,
                best_slice_global_index=best_frame_idx,
                best_slice_z=z_pos,
                longest_diameter_mm=longest,
                short_axis_mm=short,
            )
        )

    return results
