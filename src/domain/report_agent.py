from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.lesion_agent import LesionAgent
from src.domain.infiltration_assessment import InfiltrationAssessment
from src.domain.organ_assessment import OrganAssessment
from src.domain.incidental_finding import IncidentalFinding


class ReportAgent(BaseModel):
    """Agent/LLM-generated part of the REPORT section — requires image interpretation."""

    lesions: list[LesionAgent] = Field(default_factory=list)
    infiltration: InfiltrationAssessment = Field(default_factory=InfiltrationAssessment)
    negative_findings: list[str] = Field(default_factory=list)
    negative_findings_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    organ_assessments: list[OrganAssessment] = Field(default_factory=list)
    incidental_findings: list[IncidentalFinding] = Field(default_factory=list)
