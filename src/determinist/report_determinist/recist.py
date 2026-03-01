"""RECIST 1.1 criteria computation."""

from __future__ import annotations

RECIST_PR_THRESHOLD = -30.0  # ≥ 30% decrease → Partial Response
RECIST_PD_THRESHOLD = 20.0  # ≥ 20% increase → Progressive Disease
RECIST_PD_ABS_MM = 5.0  # minimum absolute increase for PD


def compute_evolution(current_max: float, previous_max: float) -> str:
    """Qualitative evolution of a single lesion based on largest diameter change."""
    if previous_max <= 0:
        return "New lesion"

    pct = (current_max - previous_max) / previous_max * 100

    if pct >= RECIST_PD_THRESHOLD:
        return "Significant increase"
    if pct > 5:
        return "Increase in size"
    if pct <= RECIST_PR_THRESHOLD:
        return "Significant decrease"
    if pct < -5:
        return "Decrease in size"
    return "Size stability"


def compute_change_percent(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    return (current - previous) / previous * 100


def compute_recist_conclusion(
    current_sizes: list[float],
    previous_sizes: list[float] | None,
) -> str | None:
    """RECIST 1.1 overall response from the sum of longest diameters.

    - CR: all target lesions have disappeared (sum == 0)
    - PR: ≥ 30% decrease in sum of diameters
    - PD: ≥ 20% increase AND ≥ 5 mm absolute increase
    - SD: neither PR nor PD
    """
    if not current_sizes:
        return None

    current_sum = sum(current_sizes)

    if previous_sizes is None or not previous_sizes:
        return None

    if current_sum == 0:
        return "CR"

    previous_sum = sum(previous_sizes)
    if previous_sum <= 0:
        return None

    pct_change = (current_sum - previous_sum) / previous_sum * 100
    abs_change = current_sum - previous_sum

    if pct_change <= RECIST_PR_THRESHOLD:
        return "PR"
    if pct_change >= RECIST_PD_THRESHOLD and abs_change >= RECIST_PD_ABS_MM:
        return "PD"
    return "SD"
