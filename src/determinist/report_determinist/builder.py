from __future__ import annotations

import logging

from src.domain.lesion_determinist import LesionDeterminist
from src.domain.report_determinist import ReportDeterminist
from src.repositories.liste_examen_repo import ListeExamenRepo, Examen
from src.repositories.data_repo import DataRepo
from src.determinist.report_determinist.seg_analyzer import analyze_seg, SegmentInfo
from src.determinist.report_determinist.recist import (
    compute_evolution,
    compute_change_percent,
    compute_recist_conclusion,
)
from src.determinist.advanced_metrics.builder import build_advanced_metrics

logger = logging.getLogger(__name__)


def _find_previous_exam(
    examen_repo: ListeExamenRepo,
    patient_id: str,
    accession_number: int,
    data_repo: DataRepo | None = None,
) -> Examen | None:
    """Return the chronologically preceding exam, or None."""
    history = examen_repo.get_patient_history(patient_id, data_repo)
    current_date = next(
        (e.study_date for e in history if e.accession_number == accession_number),
        None,
    )
    previous: Examen | None = None
    for exam in history:
        if exam.accession_number == accession_number:
            break
        if current_date and exam.study_date and exam.study_date >= current_date:
            continue
        previous = exam
    return previous


def _get_seg_info(
    data_repo: DataRepo, patient_id: str, accession_number: int
) -> list[SegmentInfo]:
    """Load the SEG for this study and return per-segment info."""
    seg_path = data_repo.get_segmentation_file(patient_id, accession_number)
    if seg_path is None:
        return []
    try:
        return analyze_seg(seg_path)
    except Exception:
        logger.warning(
            "Failed to analyze SEG for %s / %s",
            patient_id,
            accession_number,
            exc_info=True,
        )
        return []


def build_report_determinist(
    patient_id: str,
    accession_number: int,
    examen_repo: ListeExamenRepo | None = None,
    data_repo: DataRepo | None = None,
) -> ReportDeterminist:
    """Build the deterministic part of a radiology report.

    Data sources:
    - Lesion dimensions: SEG DICOM (current), SEG or report text (previous)
    - Volume, best slice: SEG DICOM (current + previous exam)
    - Evolution, change_percent: computed from longest diameters
    - volume_change_percent: computed from volumes
    - RECIST conclusion: computed from sum of longest diameters
    """
    examen_repo = examen_repo or ListeExamenRepo()
    data_repo = data_repo or DataRepo()

    current_exam = examen_repo.get_by_accession_number(accession_number)
    if current_exam is None:
        logger.warning("No exam found for accession %s", accession_number)
        return ReportDeterminist()

    previous_exam = _find_previous_exam(
        examen_repo, patient_id, accession_number, data_repo
    )

    current_seg = _get_seg_info(data_repo, patient_id, accession_number)
    previous_seg = (
        _get_seg_info(data_repo, patient_id, previous_exam.accession_number)
        if previous_exam
        else []
    )

    # Current diameters from SEG masks (not from the report we are generating)
    current_sizes = [s.longest_diameter_mm for s in current_seg]
    # Previous diameters: prefer SEG if available, fall back to report text
    if previous_seg:
        previous_sizes = [s.longest_diameter_mm for s in previous_seg]
    else:
        previous_sizes = previous_exam.lesion_sizes_mm if previous_exam else None

    n_lesions = max(len(current_sizes), len(current_seg))
    lesions: list[LesionDeterminist] = []

    for i in range(n_lesions):
        seg: SegmentInfo | None = current_seg[i] if i < len(current_seg) else None
        prev_seg: SegmentInfo | None = (
            previous_seg[i] if i < len(previous_seg) else None
        )

        cur_diam = current_sizes[i] if i < len(current_sizes) else None
        prev_diam = (
            previous_sizes[i] if previous_sizes and i < len(previous_sizes) else None
        )

        cur_short = seg.short_axis_mm if seg else None
        prev_short = prev_seg.short_axis_mm if prev_seg else None

        evolution: str | None = None
        change_pct: float | None = None
        if cur_diam is not None and prev_diam is not None:
            evolution = compute_evolution(cur_diam, prev_diam)
            change_pct = compute_change_percent(cur_diam, prev_diam)

        vol_change_pct: float | None = None
        if seg and prev_seg and prev_seg.volume_mm3 > 0:
            vol_change_pct = compute_change_percent(seg.volume_mm3, prev_seg.volume_mm3)

        lesions.append(
            LesionDeterminist(
                dimensions_mm=[cur_diam] if cur_diam is not None else [],
                short_axis_mm=cur_short,
                previous_dimensions_mm=[prev_diam] if prev_diam is not None else None,
                previous_short_axis_mm=prev_short,
                evolution=evolution,
                slice_index=seg.best_slice_index if seg else None,
                volume_mm3=seg.volume_mm3 if seg else None,
                volume_ml=seg.volume_ml if seg else None,
                previous_volume_mm3=prev_seg.volume_mm3 if prev_seg else None,
                change_percent=change_pct,
                volume_change_percent=vol_change_pct,
            )
        )

    recist = compute_recist_conclusion(current_sizes, previous_sizes or [])

    logger.info("[advanced_metrics] Computing advanced oncological metrics …")
    advanced = build_advanced_metrics(
        patient_id, accession_number, examen_repo, data_repo
    )

    return ReportDeterminist(
        lesions=lesions,
        recist_conclusion=recist,
        advanced_metrics=advanced,
    )
