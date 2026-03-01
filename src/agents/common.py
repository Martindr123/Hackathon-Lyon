"""Shared utilities for all report agents.

Provides image preparation and previous-report context extraction
so that each agent can focus on its specific LLM task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import SimpleITK as sitk

from src.repositories.data_repo import DataRepo, SeriesInfo, StudyInfo
from src.repositories.liste_examen_repo import ListeExamenRepo
from src.services.llm_prompt_service import PromptMessage, LLMPrompt
from src.determinist.report_determinist.seg_analyzer import analyze_seg


@dataclass
class SegMeasurement:
    """Per-segment measurements from the SEG DICOM."""

    segment_number: int
    longest_diameter_mm: float
    short_axis_mm: float
    volume_ml: float
    best_slice_index: int  # 1-based for display
    best_slice_global_index: int = 0  # 0-based in series for aggregation


@dataclass
class ExamContext:
    """Everything an agent needs to build its prompt for one exam."""

    patient_id: str
    accession_number: int
    image_paths: list[Path] = field(default_factory=list)
    seg_path: Path | None = None
    series_files: list[Path] = field(default_factory=list)
    previous_report_text: str | None = None
    n_lesions: int = 0
    seg_measurements: list[SegMeasurement] = field(default_factory=list)
    radiologist_remark: str | None = None


def _match_series(study: StudyInfo, serie_label: str) -> SeriesInfo | None:
    keywords = serie_label.lower().split()[1:]
    for series in study.ct_series:
        name_lower = series.name.lower()
        if all(kw in name_lower for kw in keywords):
            return series
    if keywords:
        for series in study.ct_series:
            if keywords[0] in series.name.lower():
                return series
    return None


def _subsample(
    files: list[Path],
    max_count: int,
    seg_path: Path | None = None,
) -> list[Path]:
    n = len(files)
    if n <= max_count:
        return files

    seg_indices: set[int] = set()
    if seg_path:
        try:
            seg_img = sitk.ReadImage(str(seg_path))
            seg_arr = sitk.GetArrayFromImage(seg_img)
            seg_indices = {
                i for i in range(min(seg_arr.shape[0], n)) if seg_arr[i].any()
            }
        except Exception:
            pass

    seg_indices = {i for i in seg_indices if i < n}

    if len(seg_indices) >= max_count:
        seg_list = sorted(seg_indices)
        step = len(seg_list) / max_count
        chosen = sorted({seg_list[int(i * step)] for i in range(max_count)})
        return [files[i] for i in chosen]

    remaining_budget = max_count - len(seg_indices)
    other_indices = [i for i in range(n) if i not in seg_indices]
    if not other_indices:
        return [files[i] for i in sorted(seg_indices)]
    step = len(other_indices) / remaining_budget if remaining_budget > 0 else 1
    sampled_others = {other_indices[int(i * step)] for i in range(remaining_budget)}

    return [files[i] for i in sorted(seg_indices | sampled_others)]


_REPORT_SECTION_RE = re.compile(
    r"REPORT\.\s*(.+?)(?:\s*CONCLUSIONS\.|$)",
    re.DOTALL | re.IGNORECASE,
)


def _extract_report_section(raw_report: str) -> str | None:
    """Extract the REPORT section from a raw clinical report."""
    match = _REPORT_SECTION_RE.search(raw_report)
    return match.group(1).strip() if match else None


def build_exam_context(
    patient_id: str,
    accession_number: int,
    max_slices: int = 8,
    examen_repo: ListeExamenRepo | None = None,
    data_repo: DataRepo | None = None,
) -> ExamContext:
    """Prepare images and previous-report context for the agents."""
    examen_repo = examen_repo or ListeExamenRepo()
    data_repo = data_repo or DataRepo()

    current_exam = examen_repo.get_by_accession_number(accession_number)
    if current_exam is None:
        return ExamContext(patient_id=patient_id, accession_number=accession_number)

    study = data_repo.get_study(patient_id, accession_number)

    ct_series = _match_series(study, current_exam.serie) if study else None
    all_series_files = ct_series.dicom_files if ct_series else []

    seg_path: Path | None = None
    if study and study.segmentation and study.segmentation.dicom_files:
        seg_path = study.segmentation.dicom_files[0]

    sampled = _subsample(all_series_files, max_slices, seg_path)

    # --- Previous report context (date-sorted) ---
    previous_report: str | None = None
    history = examen_repo.get_patient_history(patient_id, data_repo)
    current_date = next(
        (e.study_date for e in history if e.accession_number == accession_number),
        None,
    )
    for past in reversed(history):
        if past.accession_number == accession_number:
            continue
        if current_date and past.study_date and past.study_date >= current_date:
            continue
        if (
            past.clinical_info
            and "no reporting data" not in past.clinical_info.lower()
            and not past.clinical_info.startswith("NO rep")
        ):
            section = _extract_report_section(past.clinical_info)
            previous_report = section or past.clinical_info.strip()
            break

    # Measurements from SEG masks (not from the report we are generating)
    seg_measurements: list[SegMeasurement] = []
    if seg_path:
        try:
            for si in analyze_seg(seg_path):
                seg_measurements.append(
                    SegMeasurement(
                        segment_number=si.segment_number,
                        longest_diameter_mm=si.longest_diameter_mm,
                        short_axis_mm=si.short_axis_mm,
                        volume_ml=si.volume_ml,
                        best_slice_index=si.best_slice_index,
                        best_slice_global_index=si.best_slice_global_index,
                    )
                )
        except Exception:
            pass

    return ExamContext(
        patient_id=patient_id,
        accession_number=accession_number,
        image_paths=sampled,
        seg_path=seg_path,
        series_files=all_series_files,
        previous_report_text=previous_report,
        n_lesions=len(seg_measurements),
        seg_measurements=seg_measurements,
    )


def context_with_images(base: ExamContext, image_paths: list[Path]) -> ExamContext:
    """Return a new ExamContext with the same meta but different image_paths (for multi-agent)."""
    return ExamContext(
        patient_id=base.patient_id,
        accession_number=base.accession_number,
        image_paths=image_paths,
        seg_path=base.seg_path,
        series_files=base.series_files,
        previous_report_text=base.previous_report_text,
        n_lesions=base.n_lesions,
        seg_measurements=base.seg_measurements,
        radiologist_remark=base.radiologist_remark,
    )


def context_with_remark(base: ExamContext, remark: str | None) -> ExamContext:
    """Return a new ExamContext with the same data but radiologist_remark set (for refine)."""
    if not remark and base.radiologist_remark is None:
        return base
    return ExamContext(
        patient_id=base.patient_id,
        accession_number=base.accession_number,
        image_paths=base.image_paths,
        seg_path=base.seg_path,
        series_files=base.series_files,
        previous_report_text=base.previous_report_text,
        n_lesions=base.n_lesions,
        seg_measurements=base.seg_measurements,
        radiologist_remark=remark.strip() if remark else None,
    )


def make_prompt(system_text: str, user_text: str, ctx: ExamContext) -> LLMPrompt:
    """Build a 2-message LLMPrompt (system + user with images)."""
    text = user_text
    if ctx.radiologist_remark:
        text = text.rstrip() + "\n\nRemarque du radiologue à prendre en compte : " + ctx.radiologist_remark
    prompt = LLMPrompt()
    prompt.messages.append(PromptMessage(role="system", text=system_text))
    prompt.messages.append(
        PromptMessage(
            role="user",
            text=text,
            image_paths=ctx.image_paths,
            seg_path=ctx.seg_path,
            series_files=ctx.series_files,
        )
    )
    return prompt
