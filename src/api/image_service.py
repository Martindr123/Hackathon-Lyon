"""Generate evidence images (CT overlays) for the review UI.

Extracts and reuses the overlay logic from llm_service.py so that
the frontend can display the same images the LLM agents see.
"""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import cv2

CT_WINDOW_CENTER = -600
CT_WINDOW_WIDTH = 1500
OVERLAY_COLOR = (0, 0, 255)  # red in BGR
OVERLAY_ALPHA = 0.35


def _apply_ct_window(arr: np.ndarray) -> np.ndarray:
    lower = CT_WINDOW_CENTER - CT_WINDOW_WIDTH / 2
    upper = CT_WINDOW_CENTER + CT_WINDOW_WIDTH / 2
    arr = np.clip(arr, lower, upper)
    return ((arr - lower) / (upper - lower) * 255).astype(np.uint8)


def _read_ct_slice(path: Path) -> np.ndarray:
    image = sitk.ReadImage(str(path))
    arr = sitk.GetArrayFromImage(image).astype(np.float32)
    if arr.ndim == 3:
        arr = arr[0]
    return _apply_ct_window(arr)


def _load_seg_volume(seg_path: Path) -> np.ndarray:
    image = sitk.ReadImage(str(seg_path))
    return sitk.GetArrayFromImage(image) > 0


def _create_overlay(ct_uint8: np.ndarray, mask: np.ndarray) -> np.ndarray:
    rgb = cv2.cvtColor(ct_uint8, cv2.COLOR_GRAY2BGR)
    if not mask.any():
        return rgb
    colored = rgb.copy()
    colored[mask] = OVERLAY_COLOR
    return cv2.addWeighted(rgb, 1 - OVERLAY_ALPHA, colored, OVERLAY_ALPHA, 0)


def _to_base64_png(img: np.ndarray) -> str:
    _, png_bytes = cv2.imencode(".png", img)
    return base64.b64encode(png_bytes.tobytes()).decode("utf-8")


def generate_slice_b64(
    ct_path: Path,
    seg_arr: np.ndarray | None,
    series_files: list[Path],
) -> str:
    """Render a single CT slice as a base64 PNG, with optional SEG overlay."""
    ct_slice = _read_ct_slice(ct_path)
    if seg_arr is not None:
        try:
            slice_idx = series_files.index(ct_path)
        except ValueError:
            slice_idx = -1
        if 0 <= slice_idx < seg_arr.shape[0]:
            img = _create_overlay(ct_slice, seg_arr[slice_idx])
        else:
            img = cv2.cvtColor(ct_slice, cv2.COLOR_GRAY2BGR)
    else:
        img = cv2.cvtColor(ct_slice, cv2.COLOR_GRAY2BGR)
    return _to_base64_png(img)


def generate_evidence_images(
    image_paths: list[Path],
    seg_path: Path | None,
    series_files: list[Path],
    best_slice_indices: list[int] | None = None,
) -> list[dict]:
    """Generate base64 evidence images for the review UI.

    Returns a list of dicts:
        {"base64": str, "label": str, "is_best_slice": bool, "segment": int|None,
         "reason": str, "global_index": int}
    """
    seg_arr = None
    if seg_path:
        try:
            seg_arr = _load_seg_volume(seg_path)
        except Exception:
            pass

    best_set: dict[int, int] = {}
    if best_slice_indices and series_files:
        for seg_num, bsi in enumerate(best_slice_indices, start=1):
            for file_idx, fp in enumerate(series_files):
                if file_idx == bsi - 1:
                    best_set[file_idx] = seg_num
                    break

    sampled_global_indices: dict[int, Path] = {}
    for p in image_paths:
        try:
            idx = series_files.index(p)
        except ValueError:
            idx = -1
        sampled_global_indices[idx] = p

    all_indices = set(sampled_global_indices.keys())
    for file_idx in best_set:
        if file_idx not in all_indices and file_idx < len(series_files):
            all_indices.add(file_idx)

    results: list[dict] = []
    for idx in sorted(all_indices):
        path = sampled_global_indices.get(idx) or series_files[idx]
        is_best = idx in best_set
        seg_num = best_set.get(idx)
        label = f"Slice {idx + 1}"
        if is_best and seg_num:
            label += f" (best for segment {seg_num})"
            reason = f"Meilleure slice pour le segment {seg_num} (plus grande section)."
        else:
            reason = f"Slice {idx + 1} du volume."

        b64 = generate_slice_b64(path, seg_arr, series_files)
        results.append(
            {
                "base64": b64,
                "label": label,
                "is_best_slice": is_best,
                "segment": seg_num,
                "reason": reason,
                "global_index": idx,
            }
        )

    return results
