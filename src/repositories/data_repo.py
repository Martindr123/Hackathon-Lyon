from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field

import pydicom

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass
class SeriesInfo:
    name: str
    path: Path
    dicom_files: list[Path] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.dicom_files)

    @property
    def is_segmentation(self) -> bool:
        return self.name.startswith("SEG ")

    @property
    def is_structured_report(self) -> bool:
        return self.name.startswith("SR ")

    @property
    def is_ct(self) -> bool:
        return self.name.startswith("CT ")


@dataclass
class StudyInfo:
    accession_number: int
    description: str
    path: Path
    series: list[SeriesInfo] = field(default_factory=list)

    @property
    def ct_series(self) -> list[SeriesInfo]:
        return [s for s in self.series if s.is_ct]

    @property
    def segmentation(self) -> SeriesInfo | None:
        segs = [s for s in self.series if s.is_segmentation]
        return segs[0] if segs else None

    @property
    def structured_report(self) -> SeriesInfo | None:
        srs = [s for s in self.series if s.is_structured_report]
        return srs[0] if srs else None


def _parse_study_folder_name(name: str) -> tuple[int, str]:
    """Extract accession number and description from folder name like '11092835 TC TRAX TC ABDOMEN'."""
    parts = name.split(" ", 1)
    accession = int(parts[0])
    description = parts[1] if len(parts) > 1 else ""
    return accession, description


class DataRepo:
    """Navigates the data/ folder tree to locate DICOM files.

    Structure:
        data/
        ├── {PatientID} {PatientID}/
        │   ├── {AccessionNumber} {StudyDescription}/
        │   │   ├── CT CEV torax/          (CT DICOM slices)
        │   │   ├── CT lung/
        │   │   ├── SEG .../               (segmentation mask, 1 file)
        │   │   └── SR .../                (structured report, 1 file)
    """

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or DATA_DIR

    # ── Patient level ────────────────────────────────────────

    def _find_patient_dir(self, patient_id: str) -> Path | None:
        """Patient folders are named '{PatientID} {PatientID}'."""
        for d in self._data_dir.iterdir():
            if d.is_dir() and d.name.startswith(patient_id):
                return d
        return None

    def get_patient_ids(self) -> list[str]:
        return [
            d.name.split(" ")[0]
            for d in sorted(self._data_dir.iterdir())
            if d.is_dir()
        ]

    # ── Study level ──────────────────────────────────────────

    def _build_series(self, series_dir: Path) -> SeriesInfo:
        dicom_files = sorted(
            f for f in series_dir.iterdir() if f.is_file() and f.suffix == ".dcm"
        )
        return SeriesInfo(name=series_dir.name, path=series_dir, dicom_files=dicom_files)

    def _build_study(self, study_dir: Path) -> StudyInfo:
        accession, description = _parse_study_folder_name(study_dir.name)
        series = [
            self._build_series(d)
            for d in sorted(study_dir.iterdir())
            if d.is_dir()
        ]
        return StudyInfo(
            accession_number=accession,
            description=description,
            path=study_dir,
            series=series,
        )

    def get_studies(self, patient_id: str) -> list[StudyInfo]:
        patient_dir = self._find_patient_dir(patient_id)
        if patient_dir is None:
            return []
        return [
            self._build_study(d)
            for d in sorted(patient_dir.iterdir())
            if d.is_dir()
        ]

    def get_study(self, patient_id: str, accession_number: int) -> StudyInfo | None:
        for study in self.get_studies(patient_id):
            if study.accession_number == accession_number:
                return study
        return None

    # ── Image retrieval ──────────────────────────────────────

    def get_ct_dicom_files(self, patient_id: str, accession_number: int) -> list[Path]:
        """All CT DICOM files for a given study, across all CT series."""
        study = self.get_study(patient_id, accession_number)
        if study is None:
            return []
        files: list[Path] = []
        for series in study.ct_series:
            files.extend(series.dicom_files)
        return files

    def get_all_ct_files_for_patient(self, patient_id: str) -> dict[int, list[Path]]:
        """All CT files for a patient, keyed by accession number."""
        return {
            study.accession_number: [
                f for series in study.ct_series for f in series.dicom_files
            ]
            for study in self.get_studies(patient_id)
        }

    def get_segmentation_file(self, patient_id: str, accession_number: int) -> Path | None:
        study = self.get_study(patient_id, accession_number)
        if study is None:
            return None
        seg = study.segmentation
        return seg.dicom_files[0] if seg and seg.dicom_files else None

    def get_study_date(self, patient_id: str, accession_number: int) -> str | None:
        """Read the DICOM StudyDate (YYYYMMDD → YYYY-MM-DD) for a study."""
        study = self.get_study(patient_id, accession_number)
        if study is None:
            return None
        for series in study.ct_series:
            if not series.dicom_files:
                continue
            ds = pydicom.dcmread(str(series.dicom_files[0]), stop_before_pixels=True)
            raw = getattr(ds, "StudyDate", None)
            if raw:
                raw = str(raw)
                return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else raw
        return None

    def get_series_by_name(
        self, patient_id: str, accession_number: int, series_name: str
    ) -> SeriesInfo | None:
        """Find a series by partial name match (case-insensitive)."""
        study = self.get_study(patient_id, accession_number)
        if study is None:
            return None
        lower = series_name.lower()
        for series in study.series:
            if lower in series.name.lower():
                return series
        return None
