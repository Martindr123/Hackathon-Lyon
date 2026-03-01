from __future__ import annotations

from pydantic import BaseModel, Field


class LesionDeterminist(BaseModel):
    """Deterministic per-lesion data extracted from DICOM SEG + Excel."""

    dimensions_mm: list[float] = Field(
        description="Current measured dimensions in mm (e.g. [34, 54])"
    )
    short_axis_mm: float | None = Field(
        default=None,
        description="Short-axis diameter in mm (RECIST standard for lymph nodes)",
    )
    previous_dimensions_mm: list[float] | None = Field(
        default=None, description="Dimensions from the previous exam (e.g. [37, 54])"
    )
    previous_short_axis_mm: float | None = Field(
        default=None, description="Short-axis diameter from the previous exam"
    )
    evolution: str | None = Field(
        default=None,
        description="Size evolution qualifier (e.g. 'Size stability', 'Decrease in size', 'Significant increase')",
    )
    slice_index: int | None = Field(
        default=None,
        description="CT slice number where the lesion is best visible (e.g. 'image 2')",
    )
    volume_mm3: float | None = Field(
        default=None,
        description="Lesion volume in mm³ computed from the segmentation mask",
    )
    volume_ml: float | None = Field(default=None, description="Lesion volume in mL")
    previous_volume_mm3: float | None = Field(
        default=None, description="Previous exam lesion volume in mm³"
    )
    change_percent: float | None = Field(
        default=None,
        description="Percentage change of the largest diameter vs previous",
    )
    volume_change_percent: float | None = Field(
        default=None, description="Percentage change of the volume vs previous"
    )
