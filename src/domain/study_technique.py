from __future__ import annotations

from pydantic import BaseModel, Field


class StudyTechnique(BaseModel):
    """STUDY TECHNIQUE section — imaging protocol and comparison reference."""

    study_description: str = Field(
        description="Regions scanned (e.g. 'Thoracic, abdominal, and pelvic CT')"
    )
    contrast: str | None = Field(
        default=None, description="Contrast administration route (e.g. 'IV')"
    )
    contrast_agent: str | None = Field(
        default=None, description="Contrast product (e.g. 'Omnipaque 300')"
    )
    scanner_model: str | None = Field(default=None)
    tube_voltage_kvp: int | None = Field(default=None)
    slice_thickness_mm: float | None = Field(default=None)
    reconstruction_kernel: str | None = Field(default=None)
    scan_mode: str | None = Field(default=None, description="e.g. 'HELICAL MODE'")
    comparison_study_date: str | None = Field(
        default=None, description="Date of the previous exam used for comparison"
    )
    comparison_accession_number: int | None = Field(default=None)
