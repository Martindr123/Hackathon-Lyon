"""Agent that generates key_findings and recommendation for the Conclusions section.

This agent receives a summary of the full report (deterministic + agent findings)
so it can synthesize the most important points and suggest follow-up.
"""

from __future__ import annotations

import json
import logging

from src.domain.conclusions import Conclusions
from src.domain.report_determinist import ReportDeterminist
from src.domain.report_agent import ReportAgent
from src.services.llm_service import LLMService
from src.services.llm_prompt_service import LLMPrompt, PromptMessage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior radiologist writing the CONCLUSIONS section of a clinical \
radiology report.

You will be given the full REPORT findings (lesion measurements, evolution, \
organ assessments, infiltration, incidental findings, negative findings, \
and the RECIST evaluation).

Your task is to produce:
1. **key_findings**: a concise bullet-point list (3-6 items) summarizing \
   the most clinically important findings from the report.
2. **recommendation**: a follow-up recommendation if clinically warranted \
   (e.g. "Continue monitoring every 3 months", "Consider biopsy"), or null \
   if no specific recommendation is needed.

Also provide a **confidence** score (0.0-1.0) reflecting how confident you \
are in your synthesis.

Respond ONLY with a JSON object:
{
  "key_findings": [
    "<finding 1>",
    "<finding 2>"
  ],
  "recommendation": "<recommendation or null>",
  "confidence": 0.85
}\
"""


def _format_report_summary(
    det: ReportDeterminist,
    agt: ReportAgent,
    conclusions_det: Conclusions,
    previous_report: str | None = None,
) -> str:
    """Build a text summary of the full report for the LLM."""
    parts: list[str] = []

    if previous_report:
        parts.append("### Previous report (REPORT section) for context:")
        parts.append(previous_report)
        parts.append("")

    parts.append("### Current report findings:\n")

    n_lesions = max(len(det.lesions), len(agt.lesions))
    for i in range(n_lesions):
        d = det.lesions[i] if i < len(det.lesions) else None
        a = agt.lesions[i] if i < len(agt.lesions) else None

        location = a.location if a else f"Lesion {i + 1}"
        line = f"**Lesion {i + 1}** — {location}"

        if d:
            dims = "x".join(f"{v:.1f}" for v in d.dimensions_mm)
            line += f": {dims} mm"
            if d.previous_dimensions_mm:
                prev = "x".join(f"{v:.1f}" for v in d.previous_dimensions_mm)
                line += f" (previous: {prev} mm)"
            if d.evolution:
                line += f" → {d.evolution}"
            if d.volume_ml is not None:
                line += f" | Volume: {d.volume_ml:.2f} mL"
                if d.volume_change_percent is not None:
                    line += f" ({d.volume_change_percent:+.1f}%)"
        if a and a.characterization:
            line += f" | {a.characterization}"

        parts.append(line)

    infilt = agt.infiltration
    if infilt.present_indicators:
        parts.append(
            f"\n**Infiltration** ({infilt.level.value}): {infilt.summary or 'N/A'}"
        )
        parts.append(
            f"  Score: {infilt.final_score:.2f} | Indicators: {', '.join(infilt.present_indicators)}"
        )

    if agt.organ_assessments:
        parts.append("\n**Organ assessments**:")
        for oa in agt.organ_assessments:
            status = "normal" if oa.is_normal else "ABNORMAL"
            parts.append(f"- {oa.organ} ({status}): {oa.finding}")

    if agt.negative_findings:
        parts.append("\n**Negative findings**:")
        for nf in agt.negative_findings:
            parts.append(f"- {nf}")

    if agt.incidental_findings:
        parts.append("\n**Incidental findings**:")
        for inc in agt.incidental_findings:
            new_tag = " [NEW]" if inc.is_new else ""
            parts.append(f"- {inc.location}: {inc.description}{new_tag}")

    if conclusions_det.recist_response:
        parts.append(f"\n**RECIST 1.1**: {conclusions_det.recist_response}")
        if conclusions_det.recist_justification:
            parts.append(conclusions_det.recist_justification)

    return "\n".join(parts)


def run_conclusions_agent(
    report_det: ReportDeterminist,
    report_agt: ReportAgent,
    conclusions_det: Conclusions,
    previous_report: str | None = None,
    llm: LLMService | None = None,
    radiologist_remark: str | None = None,
) -> Conclusions:
    """Generate key_findings and recommendation, then merge with deterministic conclusions.

    Returns a complete Conclusions object with all fields filled.
    """
    llm = llm or LLMService()

    user_text = _format_report_summary(
        report_det, report_agt, conclusions_det, previous_report
    )
    if radiologist_remark:
        user_text = user_text.rstrip() + "\n\nRemarque du radiologue à prendre en compte : " + radiologist_remark

    prompt = LLMPrompt()
    prompt.messages.append(PromptMessage(role="system", text=SYSTEM_PROMPT))
    prompt.messages.append(PromptMessage(role="user", text=user_text))

    raw = llm.send(prompt, json_mode=True)

    key_findings: list[str] = []
    recommendation: str | None = None
    confidence: float = 0.0

    try:
        data = json.loads(raw)
        key_findings = data.get("key_findings", [])
        recommendation = data.get("recommendation")
        confidence = float(data.get("confidence", 0.5))
    except (json.JSONDecodeError, TypeError):
        logger.error("Failed to parse conclusions agent response: %s", raw)

    return Conclusions(
        recist_response=conclusions_det.recist_response,
        recist_justification=conclusions_det.recist_justification,
        sum_of_diameters_mm=conclusions_det.sum_of_diameters_mm,
        previous_sum_of_diameters_mm=conclusions_det.previous_sum_of_diameters_mm,
        key_findings=key_findings,
        recommendation=recommendation,
        conclusions_confidence=confidence,
    )
