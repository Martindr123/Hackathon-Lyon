from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.lesion_determinist import LesionDeterminist
from src.domain.advanced_metrics import AdvancedMetrics


class ReportDeterminist(BaseModel):
    """Deterministic part of the REPORT section — computed from DICOM + Excel data."""

    lesions: list[LesionDeterminist] = Field(
        default_factory=list, description="Per-lesion deterministic measurements"
    )
    recist_conclusion: str | None = Field(
        default=None, description="RECIST 1.1 response category: SD, PD, PR, or CR"
    )
    advanced_metrics: AdvancedMetrics = Field(
        default_factory=AdvancedMetrics,
        description="Advanced oncological metrics (tumor burden, TGR, vRECIST, heterogeneity, trends)",
    )
