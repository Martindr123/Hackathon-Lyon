"""Agent that identifies incidental findings unrelated to the primary pathology."""

from __future__ import annotations

import json
import logging

from src.domain.incidental_finding import IncidentalFinding
from src.services.llm_service import LLMService
from src.agents.common import ExamContext, build_exam_context, make_prompt

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior radiologist. You are given CT images from a patient's current \
examination. The patient is being followed for a known primary pathology \
(lesions are highlighted in red overlays).

Your task is to identify any **incidental findings** — abnormalities that are \
UNRELATED to the primary pathology.

For each finding, include a **confidence** score (0.0-1.0) reflecting how \
certain you are about this finding.

Examples: "Anterior wedging fracture of T5", "Small hepatic cyst", \
"Coronary calcifications", "Hiatal hernia", "Thyroid nodule".

Respond ONLY with a JSON object:
{
  "incidental_findings": [
    {
      "location": "<anatomical location>",
      "description": "<finding description>",
      "is_new": false,
      "confidence": 0.85
    }
  ]
}

Set is_new to true only if the finding was NOT mentioned in the previous report. \
If no incidental findings are present, return an empty list.\
"""


def _build_user_text(ctx: ExamContext) -> str:
    parts = [
        "Look for incidental findings unrelated to the primary pathology.",
    ]
    if ctx.previous_report_text:
        parts.append("")
        parts.append("### Previous report (REPORT section) for context:")
        parts.append(ctx.previous_report_text)
        parts.append("")
        parts.append(
            "Use this previous report to determine whether each finding is new "
            "(is_new=true) or previously known (is_new=false)."
        )
    parts.append("")
    parts.append("Return the JSON with your findings and confidence scores.")
    return "\n".join(parts)


def run_incidental_findings_agent(
    patient_id: str,
    accession_number: int,
    llm: LLMService | None = None,
    ctx: ExamContext | None = None,
    max_slices: int = 8,
) -> list[IncidentalFinding]:
    ctx = ctx or build_exam_context(patient_id, accession_number, max_slices=max_slices)
    llm = llm or LLMService()

    prompt = make_prompt(SYSTEM_PROMPT, _build_user_text(ctx), ctx)
    raw = llm.send(prompt, json_mode=True)

    try:
        data = json.loads(raw)
        return [IncidentalFinding(**item) for item in data.get("incidental_findings", [])]
    except (json.JSONDecodeError, TypeError, KeyError):
        logger.error("Failed to parse incidental findings agent response: %s", raw)
        return []
