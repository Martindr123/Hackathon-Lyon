from __future__ import annotations

from pydantic import BaseModel, Field


class LesionComparison(BaseModel):
    """Evolution of a lesion between the current and a previous exam."""

    location: str
    current_dimensions_mm: list[float]
    previous_dimensions_mm: list[float]
    change_description: str = Field(description="Evolution qualifier (e.g. 'stable', 'decreased', 'increased')")
    change_percent: float | None = Field(default=None, description="Percentage change of the largest diameter")
