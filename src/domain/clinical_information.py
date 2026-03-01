from __future__ import annotations

from pydantic import BaseModel, Field


class ClinicalInformation(BaseModel):
    """CLINICAL INFORMATION section — patient context and reason for exam."""

    primary_diagnosis: str = Field(description="Main pathology (e.g. 'Lung Neoplasia')")
    clinical_context: str = Field(
        description="Additional context (e.g. 'Included in Clinical Trial')"
    )
    patient_sex: str | None = Field(default=None)
    patient_age: str | None = Field(default=None, description="e.g. '054Y'")
