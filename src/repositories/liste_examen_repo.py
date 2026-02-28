from pathlib import Path
from dataclasses import dataclass, field

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
EXCEL_FILENAME = "Liste examen UNBOXED finaliseģe v2 (avec mesures).xlsx"

COL_SERIE = "Série avec les masques de DICOM SEG"
COL_LESION_SIZE = "lesion size in mm"
COL_PATIENT_ID = "PatientID"
COL_ACCESSION = "AccessionNumber"
COL_CLINICAL = "Clinical information data (Pseudo reports)"


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
    def patient_data_dir(self) -> Path:
        return DATA_DIR / self.patient_id


def _parse_lesion_sizes(raw: str) -> list[float]:
    """Parse the lesion size field which can contain multiple values separated by newlines."""
    sizes: list[float] = []
    for part in raw.strip().split("\n"):
        part = part.strip()
        if part:
            try:
                sizes.append(float(part))
            except ValueError:
                continue
    return sizes


class ListeExamenRepo:
    def __init__(self, filepath: Path | None = None):
        self._filepath = filepath or (DATA_DIR / EXCEL_FILENAME)
        self._df: pd.DataFrame | None = None

    def _load(self) -> pd.DataFrame:
        if self._df is None:
            self._df = pd.read_excel(self._filepath)
        return self._df

    def _row_to_examen(self, row: pd.Series) -> Examen:
        return Examen(
            serie=str(row[COL_SERIE]),
            lesion_sizes_mm=_parse_lesion_sizes(str(row[COL_LESION_SIZE])),
            patient_id=str(row[COL_PATIENT_ID]),
            accession_number=int(row[COL_ACCESSION]),
            clinical_info=str(row[COL_CLINICAL]),
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
        from src.repositories.data_repo import DataRepo  # noqa: F811 – lazy to avoid circular

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
