from __future__ import annotations

from pydantic import BaseModel, Field


class IncidentalFinding(BaseModel):
    """A finding unrelated to the primary pathology."""

    location: str
    description: str
    is_new: bool = Field(
        default=False, description="Whether this is a new finding vs previously known"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Agent confidence in this finding (0.0-1.0)",
    )
