"""Build the deterministic part of the Conclusions section.

Fills: recist_response, recist_justification, sum_of_diameters_mm,
       previous_sum_of_diameters_mm.
Leaves key_findings and recommendation to the agent.
"""

from __future__ import annotations

import logging

from src.domain.conclusions import Conclusions
from src.repositories.liste_examen_repo import ListeExamenRepo, Examen
from src.determinist.report_determinist.recist import (
    compute_recist_conclusion,
    compute_change_percent,
)

logger = logging.getLogger(__name__)

_RECIST_LABELS = {
    "CR": "Complete Response",
    "PR": "Partial Response",
    "SD": "Stable Disease",
    "PD": "Progressive Disease",
}


def _build_justification(
    recist: str,
    current_sum: float,
    previous_sum: float | None,
) -> str:
    """Generate a human-readable RECIST justification from the raw numbers."""
    if previous_sum is None or previous_sum <= 0:
        return f"Sum of longest diameters: {current_sum:.1f} mm (no prior exam for comparison)."

    pct = compute_change_percent(current_sum, previous_sum)
    pct_str = f"{pct:+.1f}%" if pct is not None else "N/A"
    label = _RECIST_LABELS.get(recist, recist)

    return (
        f"Sum of longest diameters: {current_sum:.1f} mm "
        f"(previous: {previous_sum:.1f} mm, change: {pct_str}). "
        f"Findings consistent with {label} per RECIST 1.1 criteria."
    )


def _find_previous_exam(
    examen_repo: ListeExamenRepo,
    patient_id: str,
    accession_number: int,
    data_repo: "DataRepo | None" = None,
) -> Examen | None:
    from src.repositories.data_repo import DataRepo  # noqa: F811

    history = examen_repo.get_patient_history(patient_id, data_repo)
    current_date = next(
        (e.study_date for e in history if e.accession_number == accession_number),
        None,
    )
    previous: Examen | None = None
    for exam in history:
        if exam.accession_number == accession_number:
            break
        if current_date and exam.study_date and exam.study_date >= current_date:
            continue
        previous = exam
    return previous


def build_conclusions_determinist(
    patient_id: str,
    accession_number: int,
    examen_repo: ListeExamenRepo | None = None,
    data_repo: "DataRepo | None" = None,
) -> Conclusions:
    """Build Conclusions with all deterministic fields filled.

    key_findings and recommendation are left empty for the agent.
    """
    examen_repo = examen_repo or ListeExamenRepo()

    current_exam = examen_repo.get_by_accession_number(accession_number)
    if current_exam is None:
        logger.warning("No exam found for accession %s", accession_number)
        return Conclusions()

    previous_exam = _find_previous_exam(examen_repo, patient_id, accession_number, data_repo)

    current_sizes = current_exam.lesion_sizes_mm
    previous_sizes = previous_exam.lesion_sizes_mm if previous_exam else None

    current_sum = sum(current_sizes) if current_sizes else None
    previous_sum = sum(previous_sizes) if previous_sizes else None

    recist = compute_recist_conclusion(current_sizes, previous_sizes)

    justification: str | None = None
    if recist and current_sum is not None:
        justification = _build_justification(recist, current_sum, previous_sum)

    return Conclusions(
        recist_response=recist,
        recist_justification=justification,
        sum_of_diameters_mm=current_sum,
        previous_sum_of_diameters_mm=previous_sum,
    )
