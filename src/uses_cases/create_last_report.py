"""Orchestrate the full generation of a ClinicalReport for one exam.

Pipeline:
1. Deterministic builders  (no LLM, fast)
   - ClinicalInformation
   - StudyTechnique
   - ReportDeterminist
   - Conclusions (partial: RECIST + sums)

2. LLM agents  (one call each, images sent via shared ExamContext)
   - LesionsAgent        → list[LesionAgent]     (with confidence)
   - InfiltrationAgent   → InfiltrationAssessment (structured + deterministic scoring)
   - NegativeFindingsAgent → (list[str], confidence)
   - OrganAssessmentsAgent → list[OrganAssessment] (with confidence)
   - IncidentalFindingsAgent → list[IncidentalFinding] (with confidence)
   - ConclusionsAgent    → key_findings + recommendation + confidence  (text-only)
"""

from __future__ import annotations

import logging

from src.domain.clinical_report import ClinicalReport
from src.domain.report_findings import ReportFindings
from src.domain.report_agent import ReportAgent

from src.repositories.liste_examen_repo import ListeExamenRepo
from src.repositories.data_repo import DataRepo
from src.services.llm_service import LLMService

from src.determinist.clinical_information.builder import build_clinical_information
from src.determinist.study_technique.builder import build_study_technique
from src.determinist.report_determinist.builder import build_report_determinist
from src.determinist.conclusions.builder import build_conclusions_determinist

from src.agents.common import build_exam_context
from src.agents.lesions_agent import run_lesions_agent
from src.agents.infiltration_agent import run_infiltration_agent
from src.agents.negative_findings_agent import run_negative_findings_agent
from src.agents.organ_assessments_agent import run_organ_assessments_agent
from src.agents.incidental_findings_agent import run_incidental_findings_agent
from src.agents.conclusions_agent import run_conclusions_agent

logger = logging.getLogger(__name__)


def create_last_report(
    patient_id: str,
    accession_number: int,
    max_slices: int = 8,
    examen_repo: ListeExamenRepo | None = None,
    data_repo: DataRepo | None = None,
    llm: LLMService | None = None,
) -> ClinicalReport:
    """Build a complete ClinicalReport for one patient exam.

    Returns a fully populated ClinicalReport Pydantic model.
    """
    examen_repo = examen_repo or ListeExamenRepo()
    data_repo = data_repo or DataRepo()
    llm = llm or LLMService()

    # ── 1. Deterministic ─────────────────────────────────────
    logger.info("[determinist] ClinicalInformation …")
    clinical_info = build_clinical_information(
        patient_id, accession_number, examen_repo, data_repo,
    )

    logger.info("[determinist] StudyTechnique …")
    study_technique = build_study_technique(
        patient_id, accession_number, examen_repo, data_repo,
    )

    logger.info("[determinist] ReportDeterminist …")
    report_det = build_report_determinist(
        patient_id, accession_number, examen_repo, data_repo,
    )

    logger.info("[determinist] Conclusions (RECIST + sums) …")
    conclusions_det = build_conclusions_determinist(
        patient_id, accession_number, examen_repo, data_repo,
    )

    # ── 2. Shared image context (prepared once, reused by all agents) ──
    logger.info("[agents] Preparing exam context (%d slices max) …", max_slices)
    ctx = build_exam_context(
        patient_id, accession_number, max_slices, examen_repo, data_repo,
    )

    # ── 3. LLM agents ────────────────────────────────────────
    logger.info("[agents] Lesions …")
    lesions = run_lesions_agent(patient_id, accession_number, llm=llm, ctx=ctx)

    logger.info("[agents] Infiltration …")
    infiltration = run_infiltration_agent(patient_id, accession_number, llm=llm, ctx=ctx)

    logger.info("[agents] Negative findings …")
    neg_result = run_negative_findings_agent(patient_id, accession_number, llm=llm, ctx=ctx)

    logger.info("[agents] Organ assessments …")
    organ_assessments = run_organ_assessments_agent(patient_id, accession_number, llm=llm, ctx=ctx)

    logger.info("[agents] Incidental findings …")
    incidental_findings = run_incidental_findings_agent(patient_id, accession_number, llm=llm, ctx=ctx)

    report_agt = ReportAgent(
        lesions=lesions,
        infiltration=infiltration,
        negative_findings=neg_result.findings,
        negative_findings_confidence=neg_result.confidence,
        organ_assessments=organ_assessments,
        incidental_findings=incidental_findings,
    )

    # ── 4. Conclusions agent (text-only, uses full report as context) ──
    logger.info("[agents] Conclusions (key findings + recommendation) …")
    conclusions = run_conclusions_agent(
        report_det, report_agt, conclusions_det, ctx.previous_report_text, llm=llm,
    )

    # ── 5. Assemble ──────────────────────────────────────────
    report = ClinicalReport(
        patient_id=patient_id,
        accession_number=accession_number,
        clinical_information=clinical_info,
        study_technique=study_technique,
        report=ReportFindings(
            report_determinist=report_det,
            report_agent=report_agt,
        ),
        conclusions=conclusions,
    )

    logger.info("Report complete for %s / %s", patient_id, accession_number)
    return report


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    patient_id = sys.argv[1] if len(sys.argv) > 1 else "0301B7D6"
    accession = int(sys.argv[2]) if len(sys.argv) > 2 else None
    max_slices = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    if accession is None:
        repo = ListeExamenRepo()
        history = repo.get_patient_history(patient_id)
        if not history:
            print(f"No exams found for patient {patient_id}")
            sys.exit(1)
        accession = history[-1].accession_number
        print(f"Using latest accession number: {accession}")

    report = create_last_report(patient_id, accession, max_slices=max_slices)

    print("\n" + "=" * 80)
    print(f"GENERATED REPORT — Patient {patient_id} / Accession {accession}")
    print("=" * 80)
    print(report.to_text())

    print("\n" + "=" * 80)
    print("STRUCTURED JSON")
    print("=" * 80)
    print(report.model_dump_json(indent=2))
