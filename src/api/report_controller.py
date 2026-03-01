from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.domain.clinical_report import ClinicalReport
from src.repositories.liste_examen_repo import ListeExamenRepo
from src.repositories.data_repo import DataRepo
from src.services.llm_service import LLMService
from src.uses_cases.create_last_report import create_last_report
from src.agents.common import build_exam_context

from src.api.session_manager import (
    create_session,
    get_session,
    TOTAL_STEPS,
    STEP_NAMES,
)
from src.agents.agent_info import list_agent_infos
from src.agents.remark_guard_agent import validate_remark
from src.uses_cases.interactive_pipeline import (
    init_session,
    run_pipeline_step,
    apply_validation,
    assemble_final_report,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])

_examen_repo = ListeExamenRepo()
_data_repo = DataRepo()


class ReportRequest(BaseModel):
    patient_id: str
    accession_number: int | None = None
    max_slices: int = 8


class PatientExam(BaseModel):
    patient_id: str
    accession_number: int
    serie: str
    lesion_count: int
    study_date: str | None = None


class StartRequest(BaseModel):
    patient_id: str
    accession_number: int | None = None
    max_slices: int = 8


class ValidateRequest(BaseModel):
    data: dict


class RefineRequest(BaseModel):
    remark: str = ""


# ── Existing endpoints (backward compatible) ──────────────────


@router.get("/patients", response_model=list[str])
def list_patients():
    return _examen_repo.get_patient_ids()


@router.get("/patients/{patient_id}/exams", response_model=list[PatientExam])
def list_exams(patient_id: str):
    exams = _examen_repo.get_patient_history(patient_id, _data_repo)
    if not exams:
        raise HTTPException(
            status_code=404, detail=f"No exams found for patient {patient_id}"
        )
    return [
        PatientExam(
            patient_id=e.patient_id,
            accession_number=e.accession_number,
            serie=e.serie,
            lesion_count=e.lesion_count,
            study_date=e.study_date,
        )
        for e in exams
    ]


@router.post("/generate", response_model=ClinicalReport)
def generate_report(request: ReportRequest):
    """One-shot report generation (backward compatible)."""
    patient_id = request.patient_id
    accession = request.accession_number

    if accession is None:
        history = _examen_repo.get_patient_history(patient_id, _data_repo)
        if not history:
            raise HTTPException(
                status_code=404, detail=f"No exams found for patient {patient_id}"
            )
        accession = history[-1].accession_number

    exam = _examen_repo.get_by_accession_number(accession)
    if exam is None:
        raise HTTPException(status_code=404, detail=f"Accession {accession} not found")

    try:
        report = create_last_report(
            patient_id, accession, max_slices=request.max_slices
        )
        return report
    except Exception as exc:
        logger.exception("Failed to generate report for %s / %s", patient_id, accession)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/generate/text")
def generate_report_text(request: ReportRequest) -> dict[str, str]:
    report = generate_report(request)
    return {
        "patient_id": report.patient_id,
        "accession_number": str(report.accession_number),
        "text": report.to_text(),
    }


# ── Interactive pipeline endpoints ────────────────────────────


def _sse_event(event_type: str, data: Any) -> str:
    payload = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/generate/start")
async def start_interactive(request: StartRequest):
    """Start an interactive pipeline session.

    Returns an SSE stream. The first event contains the session_id,
    deterministic results, and the first agent proposal.
    """
    patient_id = request.patient_id
    accession = request.accession_number

    if accession is None:
        history = _examen_repo.get_patient_history(patient_id, _data_repo)
        if not history:
            raise HTTPException(
                status_code=404, detail=f"No exams found for patient {patient_id}"
            )
        accession = history[-1].accession_number

    exam = _examen_repo.get_by_accession_number(accession)
    if exam is None:
        raise HTTPException(status_code=404, detail=f"Accession {accession} not found")

    ctx = build_exam_context(
        patient_id, accession, request.max_slices, _examen_repo, _data_repo
    )
    session = create_session(patient_id, accession, ctx)

    async def event_stream():
        try:
            loop = asyncio.get_event_loop()

            await loop.run_in_executor(
                None,
                init_session,
                session,
                _examen_repo,
                _data_repo,
            )

            yield _sse_event(
                "session_init",
                {
                    "session_id": session.session_id,
                    "patient_id": session.patient_id,
                    "accession_number": session.accession_number,
                    "clinical_info": session.clinical_info.model_dump()
                    if session.clinical_info
                    else None,
                    "study_technique": session.study_technique.model_dump()
                    if session.study_technique
                    else None,
                    "report_determinist": session.report_det.model_dump()
                    if session.report_det
                    else None,
                    "conclusions_det": session.conclusions_det.model_dump()
                    if session.conclusions_det
                    else None,
                },
            )

            llm = LLMService()
            proposal = await loop.run_in_executor(
                None,
                run_pipeline_step,
                session,
                llm,
            )
            session.status = "awaiting_validation"

            yield _sse_event(
                "step_result",
                {
                    "session_id": session.session_id,
                    **proposal,
                },
            )

            while session.current_step < TOTAL_STEPS:
                event_data = await session.wait_event()

                if event_data.get("type") == "validated":
                    apply_validation(session, event_data["data"])

                    if session.current_step >= TOTAL_STEPS:
                        report = assemble_final_report(session)
                        yield _sse_event(
                            "complete",
                            {
                                "session_id": session.session_id,
                                "report": report.model_dump(),
                            },
                        )
                        break

                    proposal = await loop.run_in_executor(
                        None,
                        run_pipeline_step,
                        session,
                        llm,
                    )
                    session.status = "awaiting_validation"

                    yield _sse_event(
                        "step_result",
                        {
                            "session_id": session.session_id,
                            **proposal,
                        },
                    )

        except Exception as exc:
            logger.exception(
                "Interactive pipeline error for session %s", session.session_id
            )
            yield _sse_event("error", {"message": str(exc)})
        finally:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/generate/{session_id}/validate")
async def validate_step(session_id: str, request: ValidateRequest):
    """Validate/edit the current agent proposal and advance the pipeline."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "awaiting_validation":
        raise HTTPException(
            status_code=409,
            detail=f"Session is not awaiting validation (status={session.status})",
        )

    session.push_event({"type": "validated", "data": request.data})
    return {"status": "ok", "step_advanced": session.step_name}


@router.post("/generate/{session_id}/refine")
async def refine_step(session_id: str, request: RefineRequest):
    """Re-run the current step's agent(s) with an optional radiologist remark.

    If the remark is non-empty, it is validated by a guard agent (rejects prompt
    injection / incoherent input). On rejection returns 400 with error message.
    On success returns the new proposal (same shape as step_result).
    """
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "awaiting_validation":
        raise HTTPException(
            status_code=409,
            detail=f"Session is not awaiting validation (status={session.status})",
        )

    remark = (request.remark or "").strip()
    sanitized_remark: str | None = None
    if remark:
        loop = asyncio.get_event_loop()
        accepted, sanitized, error_msg = await loop.run_in_executor(
            None,
            lambda: validate_remark(remark, LLMService()),
        )
        if not accepted:
            raise HTTPException(
                status_code=400,
                detail={"error": "refine_rejected", "message": error_msg or "Remarque non autorisée."},
            )
        sanitized_remark = sanitized

    loop = asyncio.get_event_loop()
    proposal = await loop.run_in_executor(
        None,
        lambda: run_pipeline_step(session, LLMService(), radiologist_remark=sanitized_remark),
    )
    session.status = "awaiting_validation"
    return proposal


@router.get("/agent-info")
def get_agent_info_list():
    """Return metadata for all pipeline agents (name, role, model_id)."""
    return {"agents": list_agent_infos(STEP_NAMES)}


@router.get("/generate/{session_id}/images")
def get_session_images(session_id: str):
    """Return the evidence images for this session (base64 PNGs, with reason per image)."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"images": session.evidence_images}
