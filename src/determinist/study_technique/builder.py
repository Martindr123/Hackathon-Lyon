from __future__ import annotations

import pydicom

from src.domain.study_technique import StudyTechnique
from src.repositories.liste_examen_repo import ListeExamenRepo
from src.repositories.data_repo import DataRepo


def _read_dicom_technique(
    data_repo: DataRepo, patient_id: str, accession_number: int
) -> dict:
    """Extract imaging technique metadata from the first CT DICOM file."""
    study = data_repo.get_study(patient_id, accession_number)
    if study is None:
        return {}

    for series in study.ct_series:
        if not series.dicom_files:
            continue

        ds = pydicom.dcmread(str(series.dicom_files[0]), stop_before_pixels=True)

        meta: dict = {}

        if hasattr(ds, "StudyDescription") and ds.StudyDescription:
            meta["study_description"] = str(ds.StudyDescription)

        if hasattr(ds, "ContrastBolusRoute") and ds.ContrastBolusRoute:
            meta["contrast"] = str(ds.ContrastBolusRoute)

        if hasattr(ds, "ContrastBolusAgent") and ds.ContrastBolusAgent:
            meta["contrast_agent"] = str(ds.ContrastBolusAgent)

        model_parts = []
        if hasattr(ds, "Manufacturer") and ds.Manufacturer:
            model_parts.append(str(ds.Manufacturer))
        if hasattr(ds, "ManufacturerModelName") and ds.ManufacturerModelName:
            model_parts.append(str(ds.ManufacturerModelName))
        if model_parts:
            meta["scanner_model"] = " ".join(model_parts)

        if hasattr(ds, "KVP") and ds.KVP:
            meta["tube_voltage_kvp"] = int(ds.KVP)

        if hasattr(ds, "SliceThickness") and ds.SliceThickness:
            meta["slice_thickness_mm"] = float(ds.SliceThickness)

        if hasattr(ds, "ConvolutionKernel") and ds.ConvolutionKernel:
            meta["reconstruction_kernel"] = str(ds.ConvolutionKernel)

        if hasattr(ds, "ScanOptions") and ds.ScanOptions:
            meta["scan_mode"] = str(ds.ScanOptions)

        return meta

    return {}


def _find_previous_exam(
    examen_repo: ListeExamenRepo,
    patient_id: str,
    accession_number: int,
    data_repo: DataRepo | None = None,
) -> int | None:
    """Find the accession number of the chronologically preceding exam."""
    history = examen_repo.get_patient_history(patient_id, data_repo)
    current_date = next(
        (e.study_date for e in history if e.accession_number == accession_number),
        None,
    )
    previous_accession: int | None = None
    for exam in history:
        if exam.accession_number == accession_number:
            break
        if current_date and exam.study_date and exam.study_date >= current_date:
            continue
        previous_accession = exam.accession_number

    return previous_accession


def _read_study_date(
    data_repo: DataRepo, patient_id: str, accession_number: int
) -> str | None:
    """Read the StudyDate from the DICOM metadata of a study."""
    return data_repo.get_study_date(patient_id, accession_number)


def build_study_technique(
    patient_id: str,
    accession_number: int,
    examen_repo: ListeExamenRepo | None = None,
    data_repo: DataRepo | None = None,
) -> StudyTechnique:
    """Build a StudyTechnique deterministically from DICOM metadata.

    Sources:
    - study_description, contrast, scanner_model, kvp, slice_thickness,
      kernel, scan_mode: from DICOM tags of the current exam.
    - comparison_study_date, comparison_accession_number: from the
      previous exam in the patient's history.
    """
    examen_repo = examen_repo or ListeExamenRepo()
    data_repo = data_repo or DataRepo()

    meta = _read_dicom_technique(data_repo, patient_id, accession_number)

    prev_accession = _find_previous_exam(
        examen_repo, patient_id, accession_number, data_repo
    )

    prev_date: str | None = None
    if prev_accession is not None:
        prev_date = _read_study_date(data_repo, patient_id, prev_accession)

    return StudyTechnique(
        study_description=meta.get("study_description", "N/A"),
        contrast=meta.get("contrast"),
        contrast_agent=meta.get("contrast_agent"),
        scanner_model=meta.get("scanner_model"),
        tube_voltage_kvp=meta.get("tube_voltage_kvp"),
        slice_thickness_mm=meta.get("slice_thickness_mm"),
        reconstruction_kernel=meta.get("reconstruction_kernel"),
        scan_mode=meta.get("scan_mode"),
        comparison_study_date=prev_date,
        comparison_accession_number=prev_accession,
    )
