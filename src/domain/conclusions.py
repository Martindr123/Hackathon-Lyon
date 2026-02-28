from __future__ import annotations

from pydantic import BaseModel, Field


class Conclusions(BaseModel):
    """CONCLUSIONS section — summary and RECIST evaluation."""

    recist_response: str | None = Field(default=None, description="RECIST 1.1 classification: CR, PR, SD, or PD")
    recist_justification: str | None = Field(default=None, description="Rationale for the RECIST classification")
    sum_of_diameters_mm: float | None = Field(default=None, description="Sum of longest diameters of target lesions (current exam)")
    previous_sum_of_diameters_mm: float | None = Field(default=None, description="Sum of longest diameters of target lesions (previous exam)")
    key_findings: list[str] = Field(default_factory=list, description="Bullet-point summary of the most important findings")
    recommendation: str | None = Field(default=None, description="Follow-up recommendation if any")
