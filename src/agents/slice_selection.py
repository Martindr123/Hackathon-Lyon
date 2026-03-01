"""Per-task slice selection strategies for multi-agent coverage.

Each task gets a list of image groups (each group = list of Path, max 8).
When there are more relevant slices than 8, we partition into multiple groups
so that every sub-agent sees a different set of images; results are then
aggregated.
"""

from __future__ import annotations

from pathlib import Path

import SimpleITK as sitk

from src.agents.common import SegMeasurement

TASK_LESIONS = "lesions"
TASK_INFILTRATION = "infiltration"
TASK_NEGATIVE_FINDINGS = "negative_findings"
TASK_ORGAN_ASSESSMENTS = "organ_assessments"
TASK_INCIDENTAL_FINDINGS = "incidental_findings"

MAX_SLICES_PER_GROUP = 8

# Anatomic zones: number of regions to cover (thorax high/low, abdomen, pelvis, etc.)
NUM_ANATOMIC_ZONES = 6
SLICES_PER_ZONE = 2

# Incidental: max total slices to sweep (then partition into groups of 8)
MAX_INCIDENTAL_SLICES = 24


def _seg_positive_indices(seg_path: Path, series_len: int) -> list[int]:
    """Return 0-based slice indices where the SEG has any non-zero pixel."""
    try:
        seg_img = sitk.ReadImage(str(seg_path))
        arr = sitk.GetArrayFromImage(seg_img)
        n = min(arr.shape[0], series_len)
        return [i for i in range(n) if arr[i].any()]
    except Exception:
        return []


def _partition_indices(indices: list[int], max_per: int) -> list[list[int]]:
    """Split a list of indices into chunks of at most max_per."""
    if not indices:
        return []
    out: list[list[int]] = []
    for i in range(0, len(indices), max_per):
        out.append(indices[i : i + max_per])
    return out


def _anatomic_zone_indices(series_len: int) -> list[int]:
    """Return slice indices that cover anatomic zones (thorax, abdomen, pelvis, etc.)."""
    if series_len == 0:
        return []
    zone_size = max(1, series_len // NUM_ANATOMIC_ZONES)
    indices: list[int] = []
    for z in range(NUM_ANATOMIC_ZONES):
        start = z * zone_size
        end = min((z + 1) * zone_size, series_len)
        if start >= end:
            continue
        # Evenly spaced samples within this zone
        step = max(1, (end - start) // SLICES_PER_ZONE)
        for k in range(SLICES_PER_ZONE):
            idx = start + k * step
            if idx < end:
                indices.append(idx)
    return sorted(set(indices))


def _uniform_spread_indices(series_len: int, max_total: int) -> list[int]:
    """Return evenly spaced indices across the full series (for incidental sweep)."""
    if series_len == 0:
        return []
    n = min(max_total, series_len)
    if n >= series_len:
        return list(range(series_len))
    step = (series_len - 1) / (n - 1) if n > 1 else 0
    return [int(round(i * step)) for i in range(n)]


def get_image_groups_for_task(
    task_name: str,
    series_files: list[Path],
    seg_path: Path | None,
    seg_measurements: list[SegMeasurement],
    max_per_group: int = MAX_SLICES_PER_GROUP,
) -> tuple[list[list[Path]], list[list[int]]]:
    """Return image groups and their slice indices for the given task.

    Returns (groups_paths, groups_indices). Each group has length <= max_per_group.
    groups_indices[k] are the 0-based series indices for group k (for aggregation).

    - lesions / infiltration: all SEG-positive slices, partitioned into
      groups of 8 so no lesion slice is dropped. If no SEG, falls back
      to one group of 8 uniformly sampled.
    - negative_findings / organ_assessments: anatomic zone coverage
      (6 zones × 2 slices = up to 12), then partitioned into groups of 8.
    - incidental_findings: uniform spread (up to 24 slices), partitioned.
    """
    n_series = len(series_files)
    if n_series == 0:
        return [], []

    def to_groups(groups_indices: list[list[int]]):
        paths = [
            [series_files[i] for i in idx_list if i < n_series]
            for idx_list in groups_indices
        ]
        return paths, groups_indices

    if task_name in (TASK_LESIONS, TASK_INFILTRATION):
        if seg_path:
            seg_indices = _seg_positive_indices(seg_path, n_series)
        else:
            seg_indices = []
        if seg_indices:
            groups_indices = _partition_indices(seg_indices, max_per_group)
        else:
            step = (
                max(1, (n_series - 1) / max_per_group)
                if n_series > max_per_group
                else 1
            )
            chosen = [
                int(min(i * step, n_series - 1))
                for i in range(min(max_per_group, n_series))
            ]
            groups_indices = [chosen]
        return to_groups(groups_indices)

    if task_name in (TASK_NEGATIVE_FINDINGS, TASK_ORGAN_ASSESSMENTS):
        zone_indices = _anatomic_zone_indices(n_series)
        if not zone_indices:
            zone_indices = (
                [
                    int(i * (n_series - 1) / (max_per_group - 1))
                    for i in range(max_per_group)
                ]
                if n_series >= max_per_group
                else list(range(n_series))
            )
        groups_indices = _partition_indices(zone_indices, max_per_group)
        return to_groups(groups_indices)

    if task_name == TASK_INCIDENTAL_FINDINGS:
        sweep_indices = _uniform_spread_indices(n_series, MAX_INCIDENTAL_SLICES)
        if not sweep_indices:
            sweep_indices = list(range(min(n_series, max_per_group)))
        groups_indices = _partition_indices(sweep_indices, max_per_group)
        return to_groups(groups_indices)

    # Unknown task: single group of 8
    step = max(1, (n_series - 1) / max_per_group) if n_series > max_per_group else 1
    chosen = [
        int(min(i * step, n_series - 1)) for i in range(min(max_per_group, n_series))
    ]
    return to_groups([chosen])
