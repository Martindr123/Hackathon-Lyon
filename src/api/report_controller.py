from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.domain.clinical_report import ClinicalReport
from src.repositories.liste_examen_repo import ListeExamenRepo
from src.repositories.data_repo import DataRepo
from src.uses_cases.create_last_report import create_last_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])

_examen_repo = ListeExamenRepo()
_data_repo = DataRepo()


class ReportRequest(BaseModel):
    patient_id: str
    accession_number: int | None = None
    max_slices: int = 8


class PatientExam(BaseModel):
    patient_id: str
    accession_number: int
    serie: str
    lesion_count: int
    study_date: str | None = None


@router.get("/patients", response_model=list[str])
def list_patients():
    """List all available patient IDs."""
    return _examen_repo.get_patient_ids()


@router.get("/patients/{patient_id}/exams", response_model=list[PatientExam])
def list_exams(patient_id: str):
    """List all exams for a given patient, sorted chronologically."""
    exams = _examen_repo.get_patient_history(patient_id, _data_repo)
    if not exams:
        raise HTTPException(status_code=404, detail=f"No exams found for patient {patient_id}")
    return [
        PatientExam(
            patient_id=e.patient_id,
            accession_number=e.accession_number,
            serie=e.serie,
            lesion_count=len(e.lesion_sizes_mm),
            study_date=e.study_date,
        )
        for e in exams
    ]


@router.post("/generate", response_model=ClinicalReport)
def generate_report(request: ReportRequest):
    """Generate a full clinical report for a patient exam.

    If accession_number is omitted, the latest exam is used.
    """
    patient_id = request.patient_id
    accession = request.accession_number

    if accession is None:
        history = _examen_repo.get_patient_history(patient_id, _data_repo)
        if not history:
            raise HTTPException(status_code=404, detail=f"No exams found for patient {patient_id}")
        accession = history[-1].accession_number

    exam = _examen_repo.get_by_accession_number(accession)
    if exam is None:
        raise HTTPException(status_code=404, detail=f"Accession {accession} not found")

    try:
        report = create_last_report(patient_id, accession, max_slices=request.max_slices)
        return report
    except Exception as exc:
        logger.exception("Failed to generate report for %s / %s", patient_id, accession)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/generate/text")
def generate_report_text(request: ReportRequest) -> dict[str, str]:
    """Generate a clinical report and return it as human-readable text."""
    report = generate_report(request)
    return {"patient_id": report.patient_id, "accession_number": str(report.accession_number), "text": report.to_text()}
