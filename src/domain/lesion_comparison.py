from __future__ import annotations

from pydantic import BaseModel, Field


class LesionComparison(BaseModel):
    """Evolution of a lesion between the current and a previous exam."""

    location: str
    current_dimensions_mm: list[float]
    previous_dimensions_mm: list[float]
    current_volume_mm3: float | None = Field(default=None, description="Current lesion volume in mm³")
    previous_volume_mm3: float | None = Field(default=None, description="Previous lesion volume in mm³")
    change_description: str = Field(description="Evolution qualifier (e.g. 'stable', 'decreased', 'increased')")
    change_percent: float | None = Field(default=None, description="Percentage change of the largest diameter")
    volume_change_percent: float | None = Field(default=None, description="Percentage change of the volume")
