from __future__ import annotations

from pydantic import BaseModel, Field


class LesionAgent(BaseModel):
    """Per-lesion data that requires LLM / agent interpretation of images."""

    location: str = Field(
        description="Anatomical location (e.g. 'right supraclavicular fossa', 'right paravertebral apical')"
    )
    characterization: str | None = Field(
        default=None,
        description="Appearance description (e.g. 'neoplastic appearance', 'fibrocicatricial', 'necrotic changes')",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Agent confidence in location + characterization (0.0-1.0)",
    )
