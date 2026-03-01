from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.lesion_determinist import LesionDeterminist


class ReportDeterminist(BaseModel):
    """Deterministic part of the REPORT section — computed from DICOM + Excel data."""

    lesions: list[LesionDeterminist] = Field(
        default_factory=list, description="Per-lesion deterministic measurements"
    )
    recist_conclusion: str | None = Field(
        default=None, description="RECIST 1.1 response category: SD, PD, PR, or CR"
    )
