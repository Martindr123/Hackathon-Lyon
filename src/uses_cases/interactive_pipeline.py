"""Step-by-step interactive pipeline for human-in-the-loop report generation.

Each step runs one LLM agent, returns a proposal, and waits for the
radiologist to validate/edit before moving to the next step.
"""

from __future__ import annotations

import logging
from itertools import chain

from src.domain.clinical_report import ClinicalReport
from src.domain.report_findings import ReportFindings
from src.domain.report_agent import ReportAgent
from src.domain.lesion_agent import LesionAgent
from src.domain.infiltration_assessment import InfiltrationAssessment
from src.domain.organ_assessment import OrganAssessment
from src.domain.incidental_finding import IncidentalFinding
from src.domain.conclusions import Conclusions

from src.repositories.liste_examen_repo import ListeExamenRepo
from src.repositories.data_repo import DataRepo
from src.services.llm_service import LLMService

from src.determinist.clinical_information.builder import build_clinical_information
from src.determinist.study_technique.builder import build_study_technique
from src.determinist.report_determinist.builder import build_report_determinist
from src.determinist.conclusions.builder import build_conclusions_determinist

from src.agents.common import context_with_images, context_with_remark
from src.agents.slice_selection import (
    get_image_groups_for_task,
    TASK_LESIONS,
    TASK_INFILTRATION,
    TASK_NEGATIVE_FINDINGS,
    TASK_ORGAN_ASSESSMENTS,
    TASK_INCIDENTAL_FINDINGS,
)
from src.agents.aggregation import (
    aggregate_lesions,
    aggregate_infiltration,
    aggregate_negative_findings,
    aggregate_organ_assessments,
    aggregate_incidental_findings,
)
from src.agents.lesions_agent import run_lesions_agent
from src.agents.infiltration_agent import run_infiltration_agent
from src.agents.negative_findings_agent import (
    run_negative_findings_agent,
    NegativeFindingsResult,
)
from src.agents.organ_assessments_agent import run_organ_assessments_agent
from src.agents.incidental_findings_agent import run_incidental_findings_agent
from src.agents.conclusions_agent import run_conclusions_agent
from src.agents.agent_info import get_agent_info, get_image_legend

from src.api.session_manager import ReportSession, STEP_NAMES, TOTAL_STEPS
from src.api.image_service import generate_evidence_images

logger = logging.getLogger(__name__)


def init_session(session: ReportSession, examen_repo=None, data_repo=None):
    """Run all deterministic builders and populate the session."""
    examen_repo = examen_repo or ListeExamenRepo()
    data_repo = data_repo or DataRepo()

    pid = session.patient_id
    acc = session.accession_number

    logger.info("[interactive] Deterministic builders for %s/%s …", pid, acc)
    session.clinical_info = build_clinical_information(pid, acc, examen_repo, data_repo)
    session.study_technique = build_study_technique(pid, acc, examen_repo, data_repo)
    session.report_det = build_report_determinist(pid, acc, examen_repo, data_repo)
    session.conclusions_det = build_conclusions_determinist(
        pid, acc, examen_repo, data_repo
    )

    best_indices = [m.best_slice_index for m in session.exam_context.seg_measurements]
    session.evidence_images = generate_evidence_images(
        session.exam_context.image_paths,
        session.exam_context.seg_path,
        session.exam_context.series_files,
        best_indices,
    )

    logger.info(
        "[interactive] Session initialized: %d evidence images",
        len(session.evidence_images),
    )


def _task_name_to_slice_task(step_name: str) -> str:
    """Map pipeline step name to slice_selection task name."""
    return {
        "lesions": TASK_LESIONS,
        "infiltration": TASK_INFILTRATION,
        "negative_findings": TASK_NEGATIVE_FINDINGS,
        "organ_assessments": TASK_ORGAN_ASSESSMENTS,
        "incidental_findings": TASK_INCIDENTAL_FINDINGS,
    }.get(step_name, TASK_LESIONS)


def run_pipeline_step(
    session: ReportSession,
    llm: LLMService | None = None,
    radiologist_remark: str | None = None,
) -> dict:
    """Run the agent for the current step and return a proposal dict.

    Uses per-task slice selection; may run multiple sub-agents and aggregate.
    The proposal is JSON-serializable and may include num_sub_agents.
    When radiologist_remark is provided (and non-empty), it is appended to the
    prompt for the current step's agent(s).
    """
    llm = llm or LLMService()
    base_ctx = session.exam_context
    if radiologist_remark:
        base_ctx = context_with_remark(base_ctx, radiologist_remark)
    step = session.current_step
    step_name = STEP_NAMES[step]

    logger.info(
        "[interactive] Running agent step %d/%d: %s", step + 1, TOTAL_STEPS, step_name
    )
    session.status = "running_agent"

    # Conclusions: single run, no image groups
    if step_name == "conclusions":
        report_agt = ReportAgent(
            lesions=session.lesions or [],
            infiltration=session.infiltration or InfiltrationAssessment(),
            negative_findings=session.neg_findings or [],
            negative_findings_confidence=session.neg_findings_confidence,
            organ_assessments=session.organ_assessments or [],
            incidental_findings=session.incidental_findings or [],
        )
        result = run_conclusions_agent(
            session.report_det,
            report_agt,
            session.conclusions_det,
            session.exam_context.previous_report_text,
            llm=llm,
            radiologist_remark=base_ctx.radiologist_remark,
        )
        session.current_proposal = result
        return {
            "step": step_name,
            "step_index": step,
            "total_steps": TOTAL_STEPS,
            "proposal": {
                "key_findings": result.key_findings,
                "recommendation": result.recommendation,
                "conclusions_confidence": result.conclusions_confidence,
                "recist_response": result.recist_response,
                "recist_justification": result.recist_justification,
                "sum_of_diameters_mm": result.sum_of_diameters_mm,
                "previous_sum_of_diameters_mm": result.previous_sum_of_diameters_mm,
            },
            "num_sub_agents": 1,
            "agent_info": get_agent_info(step_name),
            "image_legend": get_image_legend(step_name),
        }

    # Image-based steps: get per-task slice groups, run 1 or n agents, optionally aggregate
    slice_task = _task_name_to_slice_task(step_name)
    image_groups, group_indices = get_image_groups_for_task(
        slice_task,
        base_ctx.series_files,
        base_ctx.seg_path,
        base_ctx.seg_measurements,
    )
    num_groups = len(image_groups)

    # Set session evidence images to exactly the images used by (sub-)agents for this step
    all_paths = list(dict.fromkeys(chain.from_iterable(image_groups)))
    best_indices = None
    if base_ctx.seg_measurements:
        best_indices = [
            m.best_slice_global_index + 1 for m in base_ctx.seg_measurements
        ]
    session.evidence_images = generate_evidence_images(
        all_paths,
        base_ctx.seg_path,
        base_ctx.series_files,
        best_indices,
    )

    def _run_and_aggregate_lesions():
        sub_results = []
        for group in image_groups:
            ctx = context_with_images(base_ctx, group)
            sub_results.append(
                run_lesions_agent(
                    session.patient_id,
                    session.accession_number,
                    llm=llm,
                    ctx=ctx,
                )
            )
        if num_groups == 1:
            return sub_results[0], 1
        return (
            aggregate_lesions(sub_results, base_ctx.seg_measurements, group_indices),
            num_groups,
        )

    def _run_and_aggregate_infiltration():
        sub_results = []
        for group in image_groups:
            ctx = context_with_images(base_ctx, group)
            sub_results.append(
                run_infiltration_agent(
                    session.patient_id,
                    session.accession_number,
                    llm=llm,
                    ctx=ctx,
                )
            )
        if num_groups == 1:
            return sub_results[0], 1
        return aggregate_infiltration(sub_results), num_groups

    def _run_and_aggregate_negative():
        sub_results = []
        for group in image_groups:
            ctx = context_with_images(base_ctx, group)
            r = run_negative_findings_agent(
                session.patient_id,
                session.accession_number,
                llm=llm,
                ctx=ctx,
            )
            sub_results.append((r.findings, r.confidence))
        if num_groups == 1:
            return sub_results[0][0], sub_results[0][1], 1
        findings, conf = aggregate_negative_findings(sub_results)
        return findings, conf, num_groups

    def _run_and_aggregate_organs():
        sub_results = []
        for group in image_groups:
            ctx = context_with_images(base_ctx, group)
            sub_results.append(
                run_organ_assessments_agent(
                    session.patient_id,
                    session.accession_number,
                    llm=llm,
                    ctx=ctx,
                )
            )
        if num_groups == 1:
            return sub_results[0], 1
        return aggregate_organ_assessments(sub_results), num_groups

    def _run_and_aggregate_incidentals():
        sub_results = []
        for group in image_groups:
            ctx = context_with_images(base_ctx, group)
            sub_results.append(
                run_incidental_findings_agent(
                    session.patient_id,
                    session.accession_number,
                    llm=llm,
                    ctx=ctx,
                )
            )
        if num_groups == 1:
            return sub_results[0], 1
        return aggregate_incidental_findings(sub_results), num_groups

    image_legend_step = get_image_legend(slice_task)
    agent_info_step = get_agent_info(step_name)

    if step_name == "lesions":
        result, num_sub = _run_and_aggregate_lesions()
        session.current_proposal = result
        return {
            "step": step_name,
            "step_index": step,
            "total_steps": TOTAL_STEPS,
            "proposal": [le.model_dump() for le in result],
            "num_sub_agents": num_sub,
            "agent_info": agent_info_step,
            "image_legend": image_legend_step,
        }
    if step_name == "infiltration":
        result, num_sub = _run_and_aggregate_infiltration()
        session.current_proposal = result
        return {
            "step": step_name,
            "step_index": step,
            "total_steps": TOTAL_STEPS,
            "proposal": result.model_dump(),
            "num_sub_agents": num_sub,
            "agent_info": agent_info_step,
            "image_legend": image_legend_step,
        }
    if step_name == "negative_findings":
        findings, conf, num_sub = _run_and_aggregate_negative()
        session.current_proposal = NegativeFindingsResult(
            findings=findings, confidence=conf
        )
        return {
            "step": step_name,
            "step_index": step,
            "total_steps": TOTAL_STEPS,
            "proposal": {"findings": findings, "confidence": conf},
            "num_sub_agents": num_sub,
            "agent_info": agent_info_step,
            "image_legend": image_legend_step,
        }
    if step_name == "organ_assessments":
        result, num_sub = _run_and_aggregate_organs()
        session.current_proposal = result
        return {
            "step": step_name,
            "step_index": step,
            "total_steps": TOTAL_STEPS,
            "proposal": [oa.model_dump() for oa in result],
            "num_sub_agents": num_sub,
            "agent_info": agent_info_step,
            "image_legend": image_legend_step,
        }
    if step_name == "incidental_findings":
        result, num_sub = _run_and_aggregate_incidentals()
        session.current_proposal = result
        return {
            "step": step_name,
            "step_index": step,
            "total_steps": TOTAL_STEPS,
            "proposal": [inc.model_dump() for inc in result],
            "num_sub_agents": num_sub,
            "agent_info": agent_info_step,
            "image_legend": image_legend_step,
        }

    raise ValueError(f"Unknown step: {step}")


def apply_validation(session: ReportSession, validated_data: dict) -> None:
    """Store the validated (possibly edited) data and advance to the next step."""
    step_name = STEP_NAMES[session.current_step]

    if step_name == "lesions":
        session.lesions = [
            LesionAgent(**item) for item in validated_data.get("lesions", [])
        ]

    elif step_name == "infiltration":
        session.infiltration = InfiltrationAssessment(**validated_data)

    elif step_name == "negative_findings":
        session.neg_findings = validated_data.get("findings", [])
        session.neg_findings_confidence = validated_data.get("confidence", 0.5)

    elif step_name == "organ_assessments":
        session.organ_assessments = [
            OrganAssessment(**item) for item in validated_data.get("assessments", [])
        ]

    elif step_name == "incidental_findings":
        session.incidental_findings = [
            IncidentalFinding(**item) for item in validated_data.get("findings", [])
        ]

    elif step_name == "conclusions":
        session.conclusions_final = Conclusions(
            recist_response=session.conclusions_det.recist_response,
            recist_justification=session.conclusions_det.recist_justification,
            sum_of_diameters_mm=session.conclusions_det.sum_of_diameters_mm,
            previous_sum_of_diameters_mm=session.conclusions_det.previous_sum_of_diameters_mm,
            key_findings=validated_data.get("key_findings", []),
            recommendation=validated_data.get("recommendation"),
            conclusions_confidence=validated_data.get("conclusions_confidence", 0.5),
        )

    session.current_step += 1
    if session.current_step >= TOTAL_STEPS:
        session.status = "complete"
    else:
        session.status = "awaiting_validation"


def assemble_final_report(session: ReportSession) -> ClinicalReport:
    """Assemble the final ClinicalReport from all validated results."""
    report_agt = ReportAgent(
        lesions=session.lesions or [],
        infiltration=session.infiltration or InfiltrationAssessment(),
        negative_findings=session.neg_findings or [],
        negative_findings_confidence=session.neg_findings_confidence,
        organ_assessments=session.organ_assessments or [],
        incidental_findings=session.incidental_findings or [],
    )

    return ClinicalReport(
        patient_id=session.patient_id,
        accession_number=session.accession_number,
        clinical_information=session.clinical_info,
        study_technique=session.study_technique,
        report=ReportFindings(
            report_determinist=session.report_det,
            report_agent=report_agt,
        ),
        conclusions=session.conclusions_final or session.conclusions_det,
    )
