"""Advanced oncological metrics computed from DICOM SEG + CT data.

These metrics complement RECIST 1.1 with volumetric analysis, growth kinetics,
heterogeneity assessment, and temporal trend tracking.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LesionAdvancedMetrics(BaseModel):
    """Per-lesion advanced metrics: growth kinetics and tissue heterogeneity."""

    segment_number: int = Field(description="1-based segment number from the SEG")

    doubling_time_days: float | None = Field(
        default=None,
        description="Estimated tumor volume doubling time in days (lower = more aggressive)",
    )
    growth_rate_percent_per_month: float | None = Field(
        default=None,
        description="Tumor Growth Rate: volume change expressed as %/month",
    )

    hu_mean: float | None = Field(
        default=None, description="Mean Hounsfield Units within the lesion mask"
    )
    hu_std: float | None = Field(
        default=None,
        description="Standard deviation of Hounsfield Units within the lesion mask",
    )
    hu_heterogeneity_index: float | None = Field(
        default=None,
        description="Coefficient of variation (std / |mean|) — higher = more heterogeneous",
    )


class TrendPoint(BaseModel):
    """Snapshot of tumour burden at a single exam time-point."""

    study_date: str
    accession_number: int
    sum_of_diameters_mm: float | None = None
    total_volume_ml: float | None = None
    lesion_count: int = 0


class AdvancedMetrics(BaseModel):
    """Patient-level advanced oncological metrics."""

    total_tumor_burden_ml: float | None = Field(
        default=None, description="Sum of all lesion volumes (mL)"
    )
    previous_total_tumor_burden_ml: float | None = Field(
        default=None, description="Sum of all lesion volumes at previous exam (mL)"
    )
    tumor_burden_change_percent: float | None = Field(
        default=None, description="% change in total tumor burden vs previous exam"
    )

    v_recist_conclusion: str | None = Field(
        default=None,
        description="Volumetric RECIST: CR, PR, SD, or PD based on total volume change",
    )
    v_recist_justification: str | None = Field(
        default=None, description="Human-readable volumetric RECIST explanation"
    )

    lesion_metrics: list[LesionAdvancedMetrics] = Field(
        default_factory=list, description="Per-lesion growth kinetics and heterogeneity"
    )

    trend: list[TrendPoint] = Field(
        default_factory=list,
        description="Historical tumour burden trajectory across all exams",
    )
    nadir_sum_of_diameters_mm: float | None = Field(
        default=None, description="Lowest sum of diameters ever recorded (best response)"
    )
    change_from_nadir_percent: float | None = Field(
        default=None,
        description="% increase from nadir — used to detect rebound after response",
    )
    consecutive_stable_exams: int | None = Field(
        default=None, description="Number of consecutive exams classified as SD"
    )
    trend_direction: str | None = Field(
        default=None,
        description="Overall trajectory: improving, stable, worsening, or accelerating",
    )

    days_since_previous_exam: int | None = Field(
        default=None, description="Calendar days between current and previous exam"
    )
