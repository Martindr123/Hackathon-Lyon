"""Agent that identifies confirmed negative findings from CT images."""

from __future__ import annotations

import json
import logging
from typing import NamedTuple

from src.services.llm_service import LLMService
from src.agents.common import ExamContext, build_exam_context, make_prompt

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior radiologist. You are given CT images from a patient's current \
examination with lesion segmentations overlaid in red.

Your task is to list **confirmed negative findings**: abnormalities that you \
have specifically looked for and can confirm are absent.

You MUST systematically check the following structures and report each one \
that is normal:

**Pleura & pericardium**:
- Pleural effusion (left, right, bilateral)
- Pericardial effusion

**Lymph nodes** (pathological = short axis ≥ 10 mm):
- Supraclavicular lymphadenopathy
- Axillary lymphadenopathy
- Infradiaphragmatic / retroperitoneal lymphadenopathy

**Fluids**:
- Free intra-abdominal fluid (ascites)

**Metastatic disease**:
- Bone lesions suspicious for metastasis
- Additional pulmonary nodules beyond known/tracked lesions
- Liver metastases

**Other**:
- Bowel obstruction or perforation
- Pneumothorax
- Deep vein thrombosis or pulmonary embolism (if visible)

Also provide a global **confidence** score (0.0-1.0) reflecting how certain \
you are about your negative findings given the image quality and coverage.

IMPORTANT: Only list a finding as negative if you have genuinely verified it \
on the images. If image coverage or quality prevents you from assessing a \
structure, do NOT claim it is negative — omit it instead.

Respond ONLY with a JSON object:
{
  "negative_findings": ["<finding 1>", "<finding 2>"],
  "confidence": 0.8
}

Only include findings that are clinically relevant to this patient.\
"""


class NegativeFindingsResult(NamedTuple):
    findings: list[str]
    confidence: float


def _build_user_text(ctx: ExamContext) -> str:
    parts = [
        "Analyze the CT images and systematically check each structure listed above.",
        "List all relevant confirmed negative findings.",
    ]
    if ctx.previous_report_text:
        parts.append("")
        parts.append("### Previous report (REPORT section) for context:")
        parts.append(ctx.previous_report_text)
        parts.append("")
        parts.append(
            "Pay special attention to any finding mentioned in the previous report "
            "that may have changed — e.g. if the previous report noted no pleural "
            "effusion, verify whether that is still the case."
        )
    parts.append("")
    parts.append("Return the JSON with your findings and confidence.")
    return "\n".join(parts)


def run_negative_findings_agent(
    patient_id: str,
    accession_number: int,
    llm: LLMService | None = None,
    ctx: ExamContext | None = None,
    max_slices: int = 8,
) -> NegativeFindingsResult:
    ctx = ctx or build_exam_context(patient_id, accession_number, max_slices=max_slices)
    llm = llm or LLMService()

    prompt = make_prompt(SYSTEM_PROMPT, _build_user_text(ctx), ctx)
    raw = llm.send(prompt, json_mode=True)

    try:
        data = json.loads(raw)
        findings = data.get("negative_findings", [])
        confidence = float(data.get("confidence", 0.5))
        return NegativeFindingsResult(findings=findings, confidence=confidence)
    except (json.JSONDecodeError, TypeError):
        logger.error("Failed to parse negative findings agent response: %s", raw)
        return NegativeFindingsResult(findings=[], confidence=0.0)
