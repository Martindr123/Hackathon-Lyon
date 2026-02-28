"""Agent that detects signs of infiltration from CT images.

Uses a structured approach inspired by clinical infiltration assessment:
- The LLM identifies which radiological indicators are present and their certainty
- Mimic context (inflammation, fibrosis, etc.) is assessed
- Temporal evolution is evaluated against the previous exam
- The final score and classification are computed deterministically
"""

from __future__ import annotations

import json
import logging

from src.domain.infiltration_assessment import (
    InfiltrationAssessment,
    InfiltrationIndicator,
    MimicContext,
    TemporalEvolution,
)
from src.services.llm_service import LLMService
from src.agents.common import ExamContext, build_exam_context, make_prompt

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior radiologist specializing in tumour infiltration assessment. \
You are given CT images from a patient's current examination with lesion \
segmentations overlaid in red.

Your task is to perform a STRUCTURED infiltration analysis. You must evaluate:

## 1. Infiltration Indicators
For each applicable indicator, state whether it is present, and your linguistic \
certainty level. Only include indicators you can meaningfully assess.

**Morphological indicators** (category: "morphological"):
- loss_of_fat_plane: Loss of the fat plane between tumour and adjacent structure
- loss_of_interface: Loss of clear interface between tumour and organ/vessel
- abnormal_tissue_continuity: Abnormal tissue continuity between tumour and structure
- irregular_contours: Irregular tumour contours at the contact zone
- extension_beyond_compartment: Extension of tumour beyond its anatomical compartment

**Vascular indicators** (category: "vascular"):
- partial_encasement: Partial vascular encasement (<180°)
- circumferential_encasement: Circumferential vascular encasement (≥180°)
- vascular_stenosis: Stenosis of an adjacent vessel
- tumor_thrombosis: Tumour thrombus within a vessel
- perivascular_fat_obliteration: Obliteration of perivascular fat
- vessel_deformation: Deformation of vessel contour

**Thoracic indicators** (category: "thoracic"):
- mediastinal_fat_infiltration: Infiltration of mediastinal fat
- contact_over_180: Contact arc with mediastinal structure > 180°
- fissure_effacement: Effacement of interlobar fissure
- irregular_pleural_extension: Irregular extension to the pleura

**Indirect indicators** (category: "indirect"):
- fixed_organ_deformation: Fixed deformation of adjacent organ
- persistent_adherence: Persistent adherence across exams
- asymmetric_spatial_progression: Asymmetric spatial progression toward a structure

## 2. Mimic Context
Identify conditions that could MIMIC infiltration (false positives):
- inflammation, fibrosis, atelectasis, post_therapy_changes, artifact_present

## 3. Temporal Evolution (only if previous report is available)
- progression_toward_structure: Has the tumour progressed toward an adjacent structure?
- new_loss_of_interface: Is there a NEW loss of interface not seen previously?

## 4. Confidence & Summary
- confidence: Your overall confidence (0.0-1.0)
- summary: Free-text description of infiltration findings

Certainty levels for each indicator:
- "certain": Definite finding
- "high_probability": Highly suggestive
- "compatible": Compatible with infiltration
- "suspicion": Suspicion of infiltration
- "cannot_exclude": Cannot be excluded
- "possible": Possible but uncertain

Respond ONLY with a JSON object:
{
  "indicators": [
    {
      "name": "<indicator_name>",
      "category": "<morphological|vascular|thoracic|indirect>",
      "present": true,
      "certainty": "high_probability",
      "description": "<brief description of what you see>"
    }
  ],
  "mimic_context": {
    "inflammation": false,
    "fibrosis": false,
    "atelectasis": false,
    "post_therapy_changes": false,
    "artifact_present": false
  },
  "temporal": {
    "progression_toward_structure": false,
    "new_loss_of_interface": false
  },
  "confidence": 0.75,
  "summary": "<free-text summary or null>"
}\
"""


def _build_user_text(ctx: ExamContext) -> str:
    parts = [
        "Perform a structured infiltration assessment on these CT images.",
        "The red overlays indicate segmented lesions.",
    ]
    if ctx.previous_report_text:
        parts.append("")
        parts.append("### Previous report (REPORT section) for context:")
        parts.append(ctx.previous_report_text)
        parts.append("")
        parts.append(
            "Compare with the previous report to assess temporal evolution "
            "(progression_toward_structure, new_loss_of_interface)."
        )
    else:
        parts.append("")
        parts.append(
            "No previous report available. Set temporal fields to false."
        )
    parts.append("")
    parts.append("Return the structured JSON with all indicators, mimic context, temporal data, confidence, and summary.")
    return "\n".join(parts)


def run_infiltration_agent(
    patient_id: str,
    accession_number: int,
    llm: LLMService | None = None,
    ctx: ExamContext | None = None,
    max_slices: int = 8,
) -> InfiltrationAssessment:
    ctx = ctx or build_exam_context(patient_id, accession_number, max_slices=max_slices)
    llm = llm or LLMService()

    prompt = make_prompt(SYSTEM_PROMPT, _build_user_text(ctx), ctx)
    raw = llm.send(prompt, json_mode=True)

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.error("Failed to parse infiltration agent response: %s", raw)
        return InfiltrationAssessment()

    try:
        indicators = [
            InfiltrationIndicator(**ind)
            for ind in data.get("indicators", [])
        ]
        mimic_ctx = MimicContext(**data.get("mimic_context", {}))
        temporal = TemporalEvolution(**data.get("temporal", {}))

        return InfiltrationAssessment(
            indicators=indicators,
            mimic_context=mimic_ctx,
            temporal=temporal,
            summary=data.get("summary"),
            confidence=float(data.get("confidence", 0.5)),
        )
    except Exception:
        logger.exception("Failed to build InfiltrationAssessment from data: %s", data)
        return InfiltrationAssessment()
