from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.lesion_measurement import LesionMeasurement
from src.domain.lesion_comparison import LesionComparison
from src.domain.organ_assessment import OrganAssessment
from src.domain.incidental_finding import IncidentalFinding


class ReportFindings(BaseModel):
    """REPORT section — detailed radiological findings."""

    lesion_measurements: list[LesionMeasurement] = Field(default_factory=list, description="All lesions identified on the current exam")
    lesion_comparisons: list[LesionComparison] = Field(default_factory=list, description="Size evolution vs previous exam(s)")
    organ_assessments: list[OrganAssessment] = Field(default_factory=list, description="Systematic review of visible organs")
    incidental_findings: list[IncidentalFinding] = Field(default_factory=list, description="Findings unrelated to the primary pathology")
    negative_findings: list[str] = Field(default_factory=list, description="Confirmed absences (e.g. 'No pleural effusion')")
    free_text: str | None = Field(default=None, description="Additional narrative from the LLM not captured above")
