from __future__ import annotations

import logging

from src.repositories.liste_examen_repo import ListeExamenRepo
from src.services.llm_prompt_service import LLMPromptService
from src.services.llm_service import LLMService
from src.uses_cases.create_last_report import create_last_report

logger = logging.getLogger(__name__)


def create_last_reports(
    max_slices_per_exam: int = 20,
) -> dict[str, str]:
    """Generate the latest clinical report for every patient.

    Returns a dict mapping patient_id → generated report.
    """
    examen_repo = ListeExamenRepo()
    prompt_service = LLMPromptService(examen_repo=examen_repo)
    llm_service = LLMService()

    patient_ids = examen_repo.get_patient_ids()
    logger.info("Generating reports for %d patients: %s", len(patient_ids), patient_ids)

    reports: dict[str, str] = {}
    for i, patient_id in enumerate(patient_ids, 1):
        logger.info("--- [%d/%d] Patient %s ---", i, len(patient_ids), patient_id)
        try:
            report = create_last_report(
                patient_id=patient_id,
                max_slices_per_exam=max_slices_per_exam,
                llm_service=llm_service,
                prompt_service=prompt_service,
            )
            reports[patient_id] = report
        except Exception:
            logger.exception("Failed to generate report for patient %s", patient_id)
            reports[patient_id] = "ERROR: report generation failed"

    logger.info(
        "Done. %d/%d reports generated successfully.",
        sum(1 for r in reports.values() if not r.startswith("ERROR")),
        len(reports),
    )
    return reports


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    max_slices = int(sys.argv[1]) if len(sys.argv) > 1 else 20

    reports = create_last_reports(max_slices_per_exam=max_slices)

    for patient_id, report in reports.items():
        print("\n" + "=" * 80)
        print(f"GENERATED REPORT — Patient {patient_id}")
        print("=" * 80)
        print(report)
