from __future__ import annotations

from pydantic import BaseModel, Field


class OrganAssessment(BaseModel):
    """Assessment of a single organ or anatomical region."""

    organ: str = Field(description="Organ or region name (e.g. 'Liver', 'Spleen', 'Left adrenal')")
    finding: str = Field(description="Description of findings or 'No suspicious focal lesions'")
    is_normal: bool = Field(default=True)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Agent confidence in this assessment (0.0-1.0)")
