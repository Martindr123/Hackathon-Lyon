from __future__ import annotations

import re

import pydicom

from src.domain.clinical_information import ClinicalInformation
from src.repositories.liste_examen_repo import ListeExamenRepo
from src.repositories.data_repo import DataRepo


_CLINICAL_INFO_PATTERN = re.compile(
    r"CLINICAL INFORMATION\.\s*(.+?)(?:\s*(?:STUDY TECHNIQUE|REPORT|CONCLUSIONS)\.|$)",
    re.DOTALL | re.IGNORECASE,
)

_PROTOCOL_HINTS: dict[str, str] = {
    "PULMON": "Lung Neoplasia",
}


def _parse_clinical_info_text(raw_report: str) -> tuple[str, str]:
    """Extract primary_diagnosis and clinical_context from a previous report.

    Splits the 'CLINICAL INFORMATION.' section into:
    - primary_diagnosis: first sentence / main clause
    - clinical_context: remainder (trial info, etc.)
    """
    match = _CLINICAL_INFO_PATTERN.search(raw_report)
    if not match:
        return raw_report.strip(), ""

    text = match.group(1).strip().rstrip(".")
    parts = re.split(r"[.;]\s*", text, maxsplit=1)
    diagnosis = parts[0].strip()
    context = parts[1].strip() if len(parts) > 1 else ""
    return diagnosis, context


def _read_dicom_tags(data_repo: DataRepo, patient_id: str, accession_number: int) -> dict[str, str]:
    """Read demographic and clinical-context DICOM tags from the current exam."""
    study = data_repo.get_study(patient_id, accession_number)
    if study is None:
        return {}

    for series in study.ct_series:
        if not series.dicom_files:
            continue

        ds = pydicom.dcmread(str(series.dicom_files[0]), stop_before_pixels=True)
        info: dict[str, str] = {}

        for tag_name in ("PatientSex", "PatientAge", "BodyPartExamined",
                         "StudyDescription", "PatientComments"):
            if hasattr(ds, tag_name):
                val = getattr(ds, tag_name)
                if val:
                    info[tag_name] = str(val).strip()

        return info

    return {}


def _infer_diagnosis_from_dicom(tags: dict[str, str]) -> str:
    """Best-effort diagnosis from DICOM tags when no past report exists."""
    patient_comments = tags.get("PatientComments", "")
    for keyword, diagnosis in _PROTOCOL_HINTS.items():
        if keyword in patient_comments.upper():
            return diagnosis

    body_part = tags.get("BodyPartExamined", "")
    study_desc = tags.get("StudyDescription", "")
    if body_part or study_desc:
        return f"Follow-up imaging — {study_desc or body_part}"

    return "N/A"


def _infer_context_from_dicom(tags: dict[str, str]) -> str:
    """Best-effort clinical context from DICOM tags."""
    patient_comments = tags.get("PatientComments", "")
    if patient_comments:
        return f"Protocol: {patient_comments}"
    return ""


def build_clinical_information(
    patient_id: str,
    accession_number: int,
    examen_repo: ListeExamenRepo | None = None,
    data_repo: DataRepo | None = None,
) -> ClinicalInformation:
    """Build ClinicalInformation deterministically — without the current report.

    Strategy:
    1. Search past exams (strictly before current accession) for the most
       recent clinical report, and parse its CLINICAL INFORMATION section.
    2. If no past report is available, infer diagnosis/context from DICOM
       tags of the *current* exam (PatientComments, BodyPartExamined, etc.).
    3. patient_sex and patient_age always come from the current exam's DICOM.
    """
    examen_repo = examen_repo or ListeExamenRepo()
    data_repo = data_repo or DataRepo()

    dicom_tags = _read_dicom_tags(data_repo, patient_id, accession_number)

    # --- Try to extract diagnosis/context from the most recent PAST report ---
    diagnosis = ""
    context = ""

    history = examen_repo.get_patient_history(patient_id, data_repo)
    current_date = next(
        (e.study_date for e in history if e.accession_number == accession_number),
        None,
    )
    for past_exam in reversed(history):
        if past_exam.accession_number == accession_number:
            continue
        if current_date and past_exam.study_date and past_exam.study_date >= current_date:
            continue
        if past_exam.clinical_info and not past_exam.clinical_info.startswith("NO rep"):
            diagnosis, context = _parse_clinical_info_text(past_exam.clinical_info)
            break

    # --- Fallback: infer from DICOM tags of the current exam ---
    if not diagnosis:
        diagnosis = _infer_diagnosis_from_dicom(dicom_tags)
    if not context:
        context = _infer_context_from_dicom(dicom_tags)

    return ClinicalInformation(
        primary_diagnosis=diagnosis,
        clinical_context=context,
        patient_sex=dicom_tags.get("PatientSex"),
        patient_age=dicom_tags.get("PatientAge"),
    )
