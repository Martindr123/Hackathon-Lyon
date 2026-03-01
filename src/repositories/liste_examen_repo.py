import re
from pathlib import Path
from dataclasses import dataclass

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
EXCEL_FILENAME = "clinical data.xlsx"

COL_PATIENT_ID = "PatientID"
COL_ACCESSION = "AccessionNumber"
COL_CLINICAL = "Clinical information data (Pseudo reports)"

_FMARKER_RE = re.compile(
    r"[-–(]\s*(?:F|L)\s*(\d+)\s*[).]?"
    r"[^.]*?"
    r"(\d+(?:\.\d+)?)\s*(?:x\s*(\d+(?:\.\d+)?))?\s*mm",
    re.IGNORECASE,
)

_DIMENSION_RE = re.compile(
    r"(?:of|measuring|diameter)\s+"
    r"(\d+(?:\.\d+)?)\s*(?:x\s*(\d+(?:\.\d+)?))?\s*mm",
    re.IGNORECASE,
)


def _parse_lesion_sizes_from_report(report: str) -> list[float]:
    """Extract target-lesion longest diameters from the clinical report text.

    Looks for F-markers (F1, F2, …) and extracts the largest dimension
    mentioned near each marker.  Falls back to an empty list if no
    F-markers are found.
    """
    matches = _FMARKER_RE.findall(report)
    if not matches:
        return []

    by_index: dict[int, float] = {}
    for idx_str, dim1, dim2 in matches:
        idx = int(idx_str)
        d1 = float(dim1)
        d2 = float(dim2) if dim2 else 0.0
        longest = max(d1, d2)
        if idx not in by_index or longest > by_index[idx]:
            by_index[idx] = longest

    return [by_index[k] for k in sorted(by_index)]


def _find_serie_column(df: pd.DataFrame) -> str:
    """Find the Serie column, accounting for trailing whitespace."""
    for col in df.columns:
        if col.strip().startswith("Série avec les masques"):
            return col
    raise KeyError("Cannot find 'Série avec les masques de DICOM SEG' column")


@dataclass
class Examen:
    serie: str
    lesion_sizes_mm: list[float]
    patient_id: str
    accession_number: int
    clinical_info: str
    study_date: str | None = None

    @property
    def max_lesion_size(self) -> float | None:
        return max(self.lesion_sizes_mm) if self.lesion_sizes_mm else None

    @property
    def lesion_count(self) -> int:
        return len(self.lesion_sizes_mm)

    @property
    def patient_data_dir(self) -> Path:
        return DATA_DIR / self.patient_id


class ListeExamenRepo:
    def __init__(self, filepath: Path | None = None):
        self._filepath = filepath or (DATA_DIR / EXCEL_FILENAME)
        self._df: pd.DataFrame | None = None
        self._col_serie: str | None = None

    def _load(self) -> pd.DataFrame:
        if self._df is None:
            self._df = pd.read_excel(self._filepath)
            self._col_serie = _find_serie_column(self._df)
        return self._df

    def _row_to_examen(self, row: pd.Series) -> Examen:
        clinical = str(row[COL_CLINICAL])
        return Examen(
            serie=str(row[self._col_serie]),
            lesion_sizes_mm=_parse_lesion_sizes_from_report(clinical),
            patient_id=str(row[COL_PATIENT_ID]),
            accession_number=int(row[COL_ACCESSION]),
            clinical_info=clinical,
        )

    # ── Queries ──────────────────────────────────────────────

    def get_all(self) -> list[Examen]:
        df = self._load()
        return [self._row_to_examen(row) for _, row in df.iterrows()]

    def get_by_patient_id(self, patient_id: str) -> list[Examen]:
        df = self._load()
        mask = df[COL_PATIENT_ID] == patient_id
        return [self._row_to_examen(row) for _, row in df[mask].iterrows()]

    def get_by_accession_number(self, accession_number: int) -> Examen | None:
        df = self._load()
        mask = df[COL_ACCESSION] == accession_number
        subset = df[mask]
        if subset.empty:
            return None
        self._load()  # ensure _col_serie is set
        return self._row_to_examen(subset.iloc[0])

    def get_patient_ids(self) -> list[str]:
        df = self._load()
        return df[COL_PATIENT_ID].unique().tolist()

    def get_patient_history(
        self, patient_id: str, data_repo: "DataRepo | None" = None
    ) -> list[Examen]:
        """All exams for a patient, ordered chronologically.

        When *data_repo* is provided, each exam is enriched with its DICOM
        ``StudyDate`` and the list is sorted by that date.  Otherwise the
        fallback sort key is ``accession_number`` (not guaranteed to be
        chronological).
        """

        exams = self.get_by_patient_id(patient_id)

        if data_repo is not None:
            for exam in exams:
                if exam.study_date is None:
                    exam.study_date = data_repo.get_study_date(
                        patient_id, exam.accession_number
                    )

        def _sort_key(e: Examen) -> tuple[str, int]:
            return (e.study_date or "9999-99-99", e.accession_number)

        return sorted(exams, key=_sort_key)

    def get_clinical_report(self, accession_number: int) -> str | None:
        examen = self.get_by_accession_number(accession_number)
        return examen.clinical_info if examen else None

    def as_dataframe(self) -> pd.DataFrame:
        return self._load().copy()
