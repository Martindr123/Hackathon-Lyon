from __future__ import annotations

from pydantic import BaseModel, Field


class LesionMeasurement(BaseModel):
    """A single lesion measurement on one exam."""

    location: str = Field(description="Anatomical location (e.g. 'right supraclavicular fossa')")
    dimensions_mm: list[float] = Field(description="Measured dimensions in mm (e.g. [34, 54])")
    slice_index: int | None = Field(default=None, description="CT slice number where the lesion is best visible")
    characterization: str | None = Field(default=None, description="Appearance description (e.g. 'neoplastic', 'fibrocicatricial', 'necrotic changes')")
    is_target: bool = Field(default=True, description="RECIST target vs non-target lesion")
