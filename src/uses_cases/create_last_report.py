from __future__ import annotations

import logging

from src.repositories.liste_examen_repo import ListeExamenRepo
from src.repositories.data_repo import DataRepo
from src.services.llm_prompt_service import LLMPromptService
from src.services.llm_service import LLMService

logger = logging.getLogger(__name__)


def create_last_report(
    patient_id: str,
    max_slices_per_exam: int = 20,
    llm_service: LLMService | None = None,
    prompt_service: LLMPromptService | None = None,
) -> str:
    """Generate the clinical report for a patient's latest exam.

    Returns the LLM-generated report as a string.
    """
    prompt_service = prompt_service or LLMPromptService()
    llm_service = llm_service or LLMService()

    logger.info("Building prompt for patient %s", patient_id)
    prompt = prompt_service.build_report_prompt(
        patient_id=patient_id,
        max_slices_per_exam=max_slices_per_exam,
    )

    logger.info(
        "Prompt ready: %d messages, %d images",
        len(prompt.messages),
        len(prompt.all_image_paths),
    )

    report = llm_service.send(prompt)
    logger.info("Report generated for patient %s (%d chars)", patient_id, len(report))
    return report


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    patient_id = sys.argv[1] if len(sys.argv) > 1 else "0301B7D6"
    max_slices = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    report = create_last_report(patient_id, max_slices_per_exam=max_slices)

    print("\n" + "=" * 80)
    print(f"GENERATED REPORT — Patient {patient_id}")
    print("=" * 80)
    print(report)
