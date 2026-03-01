"""Agent that assesses non-segmented organs visible on CT images."""

from __future__ import annotations

import json
import logging

from src.domain.organ_assessment import OrganAssessment
from src.services.llm_service import LLMService
from src.agents.common import ExamContext, build_exam_context, make_prompt

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior radiologist. You are given CT images from a patient's current \
examination.

Your task is to provide a systematic assessment of the **non-segmented organs** \
visible on the images. These are the organs that are NOT highlighted with a red \
segmentation overlay but are still visible and must be reviewed.

You MUST assess each of the following organs/structures:
- Liver
- Spleen
- Pancreas
- Kidneys (left and right)
- Adrenal glands
- Gallbladder
- Urinary bladder
- Uterus and adnexa (for female patients — if absent, state so and suggest \
  prior surgical history such as hysterectomy/oophorectomy)
- Visible bowel segments
- Vascular structures (aorta, major branches)
- Bones (spine, ribs, pelvis)
- Lungs (non-segmented parenchyma — look for effusions, ground glass, etc.)
- Mediastinum (cardiomegaly, pericardial effusion, mediastinal shift)

IMPORTANT — Absent organs:
If an organ that should normally be visible is NOT visualized (e.g. uterus \
absent in a female patient, gallbladder absent, spleen absent), you MUST \
report this as a finding and suggest probable surgical cause (e.g. \
hysterectomy, cholecystectomy, splenectomy). Set is_normal to false.

For each organ, include a **confidence** score (0.0-1.0) reflecting how \
certain you are about your assessment given the image quality and visibility.

Respond ONLY with a JSON object:
{
  "organ_assessments": [
    {
      "organ": "<organ name>",
      "finding": "<description or 'No suspicious focal lesions'>",
      "is_normal": true,
      "confidence": 0.85
    }
  ]
}

Set is_normal to false if any abnormality is noted or if the organ is absent.\
"""


def _build_user_text(ctx: ExamContext) -> str:
    parts = [
        "Provide a systematic review of all non-segmented organs visible on these CT images.",
        "Check every organ in the list above. Report absent organs explicitly.",
    ]
    if ctx.previous_report_text:
        parts.append("")
        parts.append("### Previous report (REPORT section) for context:")
        parts.append(ctx.previous_report_text)
    parts.append("")
    parts.append("Return the JSON with your assessment and confidence for each organ.")
    return "\n".join(parts)


def run_organ_assessments_agent(
    patient_id: str,
    accession_number: int,
    llm: LLMService | None = None,
    ctx: ExamContext | None = None,
    max_slices: int = 8,
) -> list[OrganAssessment]:
    ctx = ctx or build_exam_context(patient_id, accession_number, max_slices=max_slices)
    llm = llm or LLMService()

    prompt = make_prompt(SYSTEM_PROMPT, _build_user_text(ctx), ctx)
    raw = llm.send(prompt, json_mode=True)

    try:
        data = json.loads(raw)
        return [OrganAssessment(**item) for item in data.get("organ_assessments", [])]
    except (json.JSONDecodeError, TypeError, KeyError):
        logger.error("Failed to parse organ assessments agent response: %s", raw)
        return []
