"""Structured infiltration assessment — hybrid LLM + deterministic scoring.

The LLM identifies which indicators are present and their linguistic certainty.
The scoring is then computed deterministically from the structured data.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, computed_field, field_validator


class InfiltrationLevel(str, Enum):
    NONE = "none"
    SIMPLE_CONTACT = "simple_contact"
    SUSPICION = "suspicion"
    CERTAIN = "certain"


class LinguisticCertainty(str, Enum):
    CERTAIN = "certain"
    HIGH_PROBABILITY = "high_probability"
    COMPATIBLE = "compatible"
    SUSPICION = "suspicion"
    CANNOT_EXCLUDE = "cannot_exclude"
    POSSIBLE = "possible"


CERTAINTY_WEIGHTS: dict[LinguisticCertainty, float] = {
    LinguisticCertainty.CERTAIN: 1.0,
    LinguisticCertainty.HIGH_PROBABILITY: 0.8,
    LinguisticCertainty.COMPATIBLE: 0.6,
    LinguisticCertainty.SUSPICION: 0.5,
    LinguisticCertainty.CANNOT_EXCLUDE: 0.3,
    LinguisticCertainty.POSSIBLE: 0.2,
}


class InfiltrationIndicator(BaseModel):
    """A single radiological sign detected by the LLM."""

    name: str = Field(description="Indicator identifier (e.g. 'loss_of_fat_plane')")
    category: str = Field(description="morphological | vascular | thoracic | indirect")
    present: bool = Field(default=False)
    certainty: LinguisticCertainty | None = Field(
        default=None,
        description="Linguistic certainty when present=True; None when present=False",
    )
    description: str | None = Field(
        default=None, description="Free-text detail from LLM"
    )

    @field_validator("certainty", mode="before")
    @classmethod
    def _empty_certainty_to_none(cls, v: object) -> LinguisticCertainty | None:
        if v is None or v == "":
            return None
        return v

    @property
    def score(self) -> float:
        if not self.present:
            return 0.0
        weight = _INDICATOR_WEIGHTS.get(self.name, 1.0)
        cert = self.certainty or LinguisticCertainty.POSSIBLE
        return weight * CERTAINTY_WEIGHTS[cert]


_INDICATOR_WEIGHTS: dict[str, float] = {
    "loss_of_fat_plane": 2.0,
    "loss_of_interface": 2.0,
    "abnormal_tissue_continuity": 1.5,
    "irregular_contours": 1.0,
    "extension_beyond_compartment": 1.5,
    "partial_encasement": 1.5,
    "circumferential_encasement": 2.5,
    "vascular_stenosis": 2.0,
    "tumor_thrombosis": 3.0,
    "perivascular_fat_obliteration": 1.5,
    "vessel_deformation": 1.0,
    "mediastinal_fat_infiltration": 2.0,
    "contact_over_180": 1.5,
    "fissure_effacement": 1.0,
    "irregular_pleural_extension": 1.5,
    "fixed_organ_deformation": 1.0,
    "persistent_adherence": 1.0,
    "asymmetric_spatial_progression": 1.5,
}


class MimicContext(BaseModel):
    """Situations that can mimic infiltration and reduce confidence."""

    inflammation: bool = Field(default=False)
    fibrosis: bool = Field(default=False)
    atelectasis: bool = Field(default=False)
    post_therapy_changes: bool = Field(default=False)
    artifact_present: bool = Field(default=False)

    @property
    def penalty(self) -> float:
        p = 0.0
        if self.inflammation:
            p += 0.15
        if self.fibrosis:
            p += 0.2
        if self.post_therapy_changes:
            p += 0.25
        if self.artifact_present:
            p += 0.3
        if self.atelectasis:
            p += 0.1
        return min(p, 0.5)


class TemporalEvolution(BaseModel):
    """Changes compared to previous exam."""

    progression_toward_structure: bool = Field(default=False)
    new_loss_of_interface: bool = Field(default=False)

    @property
    def boost(self) -> float:
        b = 0.0
        if self.progression_toward_structure:
            b += 0.5
        if self.new_loss_of_interface:
            b += 0.7
        return b


class InfiltrationAssessment(BaseModel):
    """Full structured infiltration assessment — LLM fills indicators, scoring is deterministic."""

    indicators: list[InfiltrationIndicator] = Field(default_factory=list)
    mimic_context: MimicContext = Field(default_factory=MimicContext)
    temporal: TemporalEvolution = Field(default_factory=TemporalEvolution)
    summary: str | None = Field(
        default=None, description="LLM free-text summary of infiltration findings"
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="LLM self-reported confidence"
    )

    @computed_field
    @property
    def raw_score(self) -> float:
        return sum(ind.score for ind in self.indicators)

    @computed_field
    @property
    def final_score(self) -> float:
        base = self.raw_score * (1 - self.mimic_context.penalty)
        return base + self.temporal.boost

    @computed_field
    @property
    def level(self) -> InfiltrationLevel:
        s = self.final_score
        if s <= 0:
            return InfiltrationLevel.NONE
        if s < 2:
            return InfiltrationLevel.SIMPLE_CONTACT
        if s < 5:
            return InfiltrationLevel.SUSPICION
        return InfiltrationLevel.CERTAIN

    @computed_field
    @property
    def present_indicators(self) -> list[str]:
        return [ind.name for ind in self.indicators if ind.present]
