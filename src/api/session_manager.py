"""In-memory store for interactive report generation sessions."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.domain.clinical_information import ClinicalInformation
from src.domain.study_technique import StudyTechnique
from src.domain.report_determinist import ReportDeterminist
from src.domain.conclusions import Conclusions
from src.domain.lesion_agent import LesionAgent
from src.domain.infiltration_assessment import InfiltrationAssessment
from src.domain.organ_assessment import OrganAssessment
from src.domain.incidental_finding import IncidentalFinding
from src.agents.common import ExamContext


STEP_NAMES = [
    "lesions",
    "infiltration",
    "negative_findings",
    "organ_assessments",
    "incidental_findings",
    "conclusions",
]
TOTAL_STEPS = len(STEP_NAMES)


@dataclass
class ReportSession:
    session_id: str
    patient_id: str
    accession_number: int
    status: str  # "running_agent" | "awaiting_validation" | "complete"
    current_step: int
    exam_context: ExamContext

    clinical_info: ClinicalInformation | None = None
    study_technique: StudyTechnique | None = None
    report_det: ReportDeterminist | None = None
    conclusions_det: Conclusions | None = None

    lesions: list[LesionAgent] | None = None
    infiltration: InfiltrationAssessment | None = None
    neg_findings: list[str] | None = None
    neg_findings_confidence: float = 0.5
    organ_assessments: list[OrganAssessment] | None = None
    incidental_findings: list[IncidentalFinding] | None = None
    conclusions_final: Conclusions | None = None

    current_proposal: Any = None
    evidence_images: list[dict] = field(default_factory=list)

    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _pending_event: dict | None = field(default=None, repr=False)

    def push_event(self, event: dict) -> None:
        self._pending_event = event
        self._event.set()

    async def wait_event(self) -> dict:
        await self._event.wait()
        self._event.clear()
        ev = self._pending_event
        self._pending_event = None
        return ev

    @property
    def step_name(self) -> str:
        if self.current_step < TOTAL_STEPS:
            return STEP_NAMES[self.current_step]
        return "complete"


_sessions: dict[str, ReportSession] = {}


def create_session(
    patient_id: str,
    accession_number: int,
    ctx: ExamContext,
) -> ReportSession:
    sid = uuid.uuid4().hex[:12]
    session = ReportSession(
        session_id=sid,
        patient_id=patient_id,
        accession_number=accession_number,
        status="running_agent",
        current_step=0,
        exam_context=ctx,
    )
    _sessions[sid] = session
    return session


def get_session(session_id: str) -> ReportSession | None:
    return _sessions.get(session_id)


def remove_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
