"""Agent that identifies anatomical location and characterization for each lesion."""

from __future__ import annotations

import json
import logging

from src.domain.lesion_agent import LesionAgent
from src.services.llm_service import LLMService
from src.agents.common import ExamContext, build_exam_context, make_prompt

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior radiologist. You are given CT images from a patient's current \
examination. Lesions annotated by the radiologist are highlighted in red overlays.

Your task is to provide, for each lesion, its **anatomical location**, a \
**characterization** of its appearance, and a **confidence** score (0.0-1.0) \
reflecting how certain you are about your assessment.

Confidence guidelines:
- 0.9-1.0: Very clear, unambiguous finding
- 0.7-0.89: Confident but minor uncertainty
- 0.5-0.69: Moderate confidence, some ambiguity
- 0.3-0.49: Low confidence, significant uncertainty
- 0.0-0.29: Very uncertain, speculative

Respond ONLY with a JSON object:
{
  "lesions": [
    {
      "location": "<precise anatomical location>",
      "characterization": "<appearance description>",
      "confidence": 0.85
    }
  ]
}

Return exactly as many entries as there are lesions indicated below.\
"""


def _build_user_text(ctx: ExamContext) -> str:
    parts = [
        f"This patient has **{ctx.n_lesions}** annotated lesion(s) on the current exam.",
        "Red overlays on the images indicate the segmented lesion regions.",
    ]
    if ctx.previous_report_text:
        parts.append("")
        parts.append("### Previous report (REPORT section) for context:")
        parts.append(ctx.previous_report_text)
    parts.append("")
    parts.append(
        f"Identify the anatomical location and characterization for each of "
        f"the {ctx.n_lesions} lesion(s). Include a confidence score for each. Return the JSON."
    )
    return "\n".join(parts)


def run_lesions_agent(
    patient_id: str,
    accession_number: int,
    llm: LLMService | None = None,
    ctx: ExamContext | None = None,
    max_slices: int = 8,
) -> list[LesionAgent]:
    ctx = ctx or build_exam_context(patient_id, accession_number, max_slices=max_slices)
    llm = llm or LLMService()

    prompt = make_prompt(SYSTEM_PROMPT, _build_user_text(ctx), ctx)
    raw = llm.send(prompt, json_mode=True)

    try:
        data = json.loads(raw)
        return [LesionAgent(**item) for item in data.get("lesions", [])]
    except (json.JSONDecodeError, TypeError, KeyError):
        logger.error("Failed to parse lesions agent response: %s", raw)
        return []
