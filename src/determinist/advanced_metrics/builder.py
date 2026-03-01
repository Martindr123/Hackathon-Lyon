"""Build advanced oncological metrics from DICOM SEG + CT data.

Computed metrics:
- Total tumor burden (sum of volumes) and its evolution
- Volumetric RECIST (vRECIST) based on total volume change
- Per-lesion Tumor Doubling Time (TDT) and Tumor Growth Rate (TGR)
- Per-lesion Hounsfield-Unit heterogeneity
- Multi-exam trend analysis (nadir, rebound, trajectory)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

from src.domain.advanced_metrics import (
    AdvancedMetrics,
    LesionAdvancedMetrics,
    TrendPoint,
)
from src.repositories.liste_examen_repo import ListeExamenRepo, Examen
from src.repositories.data_repo import DataRepo
from src.determinist.report_determinist.seg_analyzer import analyze_seg, SegmentInfo
from src.determinist.advanced_metrics.heterogeneity import compute_heterogeneity
from src.determinist.report_determinist.recist import compute_change_percent

logger = logging.getLogger(__name__)

VRECIST_PR_THRESHOLD = -65.0
VRECIST_PD_THRESHOLD = 73.0


def _days_between(date_a: str, date_b: str) -> int | None:
    """Calendar days between two YYYY-MM-DD date strings."""
    try:
        da = datetime.strptime(date_a, "%Y-%m-%d")
        db = datetime.strptime(date_b, "%Y-%m-%d")
        return abs((db - da).days)
    except (ValueError, TypeError):
        return None


def _doubling_time(v_current: float, v_previous: float, days: int) -> float | None:
    """Tumor volume doubling time in days: TDT = Δt × ln(2) / ln(V2/V1)."""
    if v_previous <= 0 or v_current <= 0 or days <= 0:
        return None
    ratio = v_current / v_previous
    if ratio <= 0:
        return None
    ln_ratio = math.log(ratio)
    if abs(ln_ratio) < 1e-9:
        return None
    tdt = days * math.log(2) / ln_ratio
    return round(tdt, 1)


def _growth_rate(v_current: float, v_previous: float, days: int) -> float | None:
    """Tumor Growth Rate as %/month: TGR = (ln(V2/V1) / Δt) × 30 × 100."""
    if v_previous <= 0 or v_current <= 0 or days <= 0:
        return None
    ratio = v_current / v_previous
    if ratio <= 0:
        return None
    tgr = (math.log(ratio) / days) * 30 * 100
    return round(tgr, 2)


def _compute_v_recist(
    current_total_ml: float, previous_total_ml: float | None
) -> tuple[str | None, str | None]:
    """Volumetric RECIST classification based on total volume change."""
    if previous_total_ml is None or previous_total_ml <= 0:
        return None, None

    if current_total_ml <= 0:
        return "CR", "Complete disappearance of all measurable tumor volume."

    pct = compute_change_percent(current_total_ml, previous_total_ml)
    if pct is None:
        return None, None

    if pct <= VRECIST_PR_THRESHOLD:
        conclusion = "PR"
        justification = (
            f"Total tumor volume decreased by {pct:.1f}% "
            f"({previous_total_ml:.1f} → {current_total_ml:.1f} mL), "
            f"exceeding the 65% decrease threshold for volumetric Partial Response."
        )
    elif pct >= VRECIST_PD_THRESHOLD:
        conclusion = "PD"
        justification = (
            f"Total tumor volume increased by {pct:.1f}% "
            f"({previous_total_ml:.1f} → {current_total_ml:.1f} mL), "
            f"exceeding the 73% increase threshold for volumetric Progressive Disease."
        )
    else:
        conclusion = "SD"
        justification = (
            f"Total tumor volume changed by {pct:.1f}% "
            f"({previous_total_ml:.1f} → {current_total_ml:.1f} mL), "
            f"within Stable Disease range (−65% to +73%)."
        )

    return conclusion, justification


def _classify_trend(trend: list[TrendPoint]) -> str | None:
    """Classify the overall trajectory from ≥ 3 data points."""
    sums = [t.sum_of_diameters_mm for t in trend if t.sum_of_diameters_mm is not None]
    if len(sums) < 3:
        return None

    deltas = [sums[i] - sums[i - 1] for i in range(1, len(sums))]
    recent_deltas = deltas[-min(3, len(deltas)) :]

    all_neg = all(d < -0.5 for d in recent_deltas)
    all_pos = all(d > 0.5 for d in recent_deltas)
    all_flat = all(abs(d) <= 0.5 for d in recent_deltas)

    if all_neg:
        return "improving"
    if all_flat:
        return "stable"
    if all_pos:
        if len(recent_deltas) >= 2 and recent_deltas[-1] > recent_deltas[-2] * 1.3:
            return "accelerating"
        return "worsening"
    return "mixed"


def _count_consecutive_sd(trend: list[TrendPoint]) -> int:
    """Count consecutive Stable Disease exams from the most recent backwards."""
    sums = [t.sum_of_diameters_mm for t in trend if t.sum_of_diameters_mm is not None]
    if len(sums) < 2:
        return 0

    count = 0
    for i in range(len(sums) - 1, 0, -1):
        prev_sum = sums[i - 1]
        if prev_sum <= 0:
            break
        pct = (sums[i] - prev_sum) / prev_sum * 100
        if -30 <= pct <= 20:
            count += 1
        else:
            break
    return count


def _find_previous_exam(
    examen_repo: ListeExamenRepo,
    patient_id: str,
    accession_number: int,
    data_repo: DataRepo | None = None,
) -> Examen | None:
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


def _build_trend(
    patient_id: str,
    examen_repo: ListeExamenRepo,
    data_repo: DataRepo,
) -> list[TrendPoint]:
    """Build the full historical trend for a patient."""
    history = examen_repo.get_patient_history(patient_id, data_repo)
    points: list[TrendPoint] = []

    for exam in history:
        if not exam.study_date:
            continue

        seg_info = _get_seg_info(data_repo, patient_id, exam.accession_number)
        if seg_info:
            diameters = [s.longest_diameter_mm for s in seg_info]
            volumes_ml = [s.volume_ml for s in seg_info]
            points.append(
                TrendPoint(
                    study_date=exam.study_date,
                    accession_number=exam.accession_number,
                    sum_of_diameters_mm=sum(diameters) if diameters else None,
                    total_volume_ml=sum(volumes_ml) if volumes_ml else None,
                    lesion_count=len(seg_info),
                )
            )
        elif exam.lesion_sizes_mm:
            points.append(
                TrendPoint(
                    study_date=exam.study_date,
                    accession_number=exam.accession_number,
                    sum_of_diameters_mm=sum(exam.lesion_sizes_mm),
                    total_volume_ml=None,
                    lesion_count=len(exam.lesion_sizes_mm),
                )
            )

    return points


def build_advanced_metrics(
    patient_id: str,
    accession_number: int,
    examen_repo: ListeExamenRepo | None = None,
    data_repo: DataRepo | None = None,
) -> AdvancedMetrics:
    """Build all advanced metrics for one exam."""
    examen_repo = examen_repo or ListeExamenRepo()
    data_repo = data_repo or DataRepo()

    current_exam = examen_repo.get_by_accession_number(accession_number)
    if current_exam is None:
        logger.warning("No exam found for accession %s", accession_number)
        return AdvancedMetrics()

    previous_exam = _find_previous_exam(
        examen_repo, patient_id, accession_number, data_repo
    )

    current_seg = _get_seg_info(data_repo, patient_id, accession_number)
    previous_seg = (
        _get_seg_info(data_repo, patient_id, previous_exam.accession_number)
        if previous_exam
        else []
    )

    # ── Days between exams ────────────────────────────────────
    days: int | None = None
    if previous_exam and current_exam.study_date and previous_exam.study_date:
        days = _days_between(previous_exam.study_date, current_exam.study_date)

    # ── Total tumor burden ────────────────────────────────────
    current_burden = (
        sum(s.volume_ml for s in current_seg) if current_seg else None
    )
    previous_burden = (
        sum(s.volume_ml for s in previous_seg) if previous_seg else None
    )
    burden_change = (
        compute_change_percent(current_burden, previous_burden)
        if current_burden is not None and previous_burden is not None
        else None
    )

    # ── Volumetric RECIST ─────────────────────────────────────
    v_recist, v_recist_just = _compute_v_recist(
        current_burden or 0.0, previous_burden
    )

    # ── Per-lesion: TDT, TGR ──────────────────────────────────
    lesion_metrics: list[LesionAdvancedMetrics] = []
    for i, seg in enumerate(current_seg):
        prev_seg = previous_seg[i] if i < len(previous_seg) else None

        tdt: float | None = None
        tgr: float | None = None
        if prev_seg and days and days > 0:
            tdt = _doubling_time(seg.volume_mm3, prev_seg.volume_mm3, days)
            tgr = _growth_rate(seg.volume_mm3, prev_seg.volume_mm3, days)

        lesion_metrics.append(
            LesionAdvancedMetrics(
                segment_number=seg.segment_number,
                doubling_time_days=tdt,
                growth_rate_percent_per_month=tgr,
            )
        )

    # ── Heterogeneity (HU) ───────────────────────────────────
    seg_path = data_repo.get_segmentation_file(patient_id, accession_number)
    ct_files = data_repo.get_ct_dicom_files(patient_id, accession_number)
    if seg_path and ct_files:
        try:
            hu_stats = compute_heterogeneity(seg_path, ct_files)
            hu_by_seg = {h.segment_number: h for h in hu_stats}
            for lm in lesion_metrics:
                hu = hu_by_seg.get(lm.segment_number)
                if hu:
                    lm.hu_mean = hu.mean
                    lm.hu_std = hu.std
                    lm.hu_heterogeneity_index = hu.heterogeneity_index
        except Exception:
            logger.warning("Heterogeneity computation failed", exc_info=True)

    # ── Trend analysis ────────────────────────────────────────
    trend = _build_trend(patient_id, examen_repo, data_repo)

    nadir_sum: float | None = None
    change_from_nadir: float | None = None
    sums = [t.sum_of_diameters_mm for t in trend if t.sum_of_diameters_mm is not None]
    if sums:
        nadir_sum = min(sums)
        current_sum = sums[-1]
        if nadir_sum > 0 and current_sum is not None:
            change_from_nadir = round(
                (current_sum - nadir_sum) / nadir_sum * 100, 1
            )

    consecutive_sd = _count_consecutive_sd(trend)
    trend_dir = _classify_trend(trend)

    return AdvancedMetrics(
        total_tumor_burden_ml=round(current_burden, 2) if current_burden else None,
        previous_total_tumor_burden_ml=(
            round(previous_burden, 2) if previous_burden else None
        ),
        tumor_burden_change_percent=(
            round(burden_change, 1) if burden_change is not None else None
        ),
        v_recist_conclusion=v_recist,
        v_recist_justification=v_recist_just,
        lesion_metrics=lesion_metrics,
        trend=trend,
        nadir_sum_of_diameters_mm=round(nadir_sum, 1) if nadir_sum else None,
        change_from_nadir_percent=change_from_nadir,
        consecutive_stable_exams=consecutive_sd,
        trend_direction=trend_dir,
        days_since_previous_exam=days,
    )
