"""Aggregate results from multiple sub-agents (one per image group) into a single result.

Used when a task is split across n image groups; each sub-agent returns a result
and we merge them (by segment, by organ, by indicator, etc.) with confidence
averaged where applicable.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from src.agents.common import SegMeasurement
from src.domain.lesion_agent import LesionAgent
from src.domain.infiltration_assessment import (
    InfiltrationAssessment,
    InfiltrationIndicator,
    MimicContext,
    TemporalEvolution,
    LinguisticCertainty,
    CERTAINTY_WEIGHTS,
)
from src.domain.organ_assessment import OrganAssessment
from src.domain.incidental_finding import IncidentalFinding

logger = logging.getLogger(__name__)


def aggregate_lesions(
    sub_results: list[list[LesionAgent]],
    seg_measurements: list[SegMeasurement],
    group_slice_indices: list[list[int]],
) -> list[LesionAgent]:
    """Merge n lesion lists into one per segment.

    For each segment, pick the sub-agent that saw the best slice for that
    segment (from seg_measurements.best_slice_global_index). Use that
    agent's location/characterization; confidence = mean of confidences from
    all sub-agents that saw that segment's best slice.
    """
    n_lesions = len(seg_measurements)
    if n_lesions == 0:
        return []

    merged: list[LesionAgent] = []
    for s in range(n_lesions):
        best_global = seg_measurements[s].best_slice_global_index
        # Which groups contain this slice?
        groups_with_slice = [
            g
            for g, indices in enumerate(group_slice_indices)
            if best_global in indices and g < len(sub_results)
        ]
        if not groups_with_slice:
            # Fallback: use first group's result for this segment index
            groups_with_slice = [0] if sub_results else []

        # Prefer the first group that has this segment's best slice
        chosen_group = groups_with_slice[0]
        sub_list = sub_results[chosen_group]
        if s < len(sub_list):
            chosen = sub_list[s]
        else:
            chosen = LesionAgent(
                location="",
                characterization=None,
                confidence=0.5,
            )

        # Average confidence over all groups that saw this segment
        confs = []
        for g in groups_with_slice:
            if g < len(sub_results) and s < len(sub_results[g]):
                confs.append(sub_results[g][s].confidence)
        avg_conf = sum(confs) / len(confs) if confs else chosen.confidence

        merged.append(
            LesionAgent(
                location=chosen.location,
                characterization=chosen.characterization,
                confidence=round(avg_conf, 2),
            )
        )
    return merged


def aggregate_infiltration(
    sub_results: list[InfiltrationAssessment],
) -> InfiltrationAssessment:
    """Merge n infiltration assessments: union of indicators (max certainty), mean confidence."""
    if not sub_results:
        return InfiltrationAssessment()
    if len(sub_results) == 1:
        return sub_results[0]

    # Union of indicators by name: keep the one with highest certainty when present in several
    by_name: dict[str, InfiltrationIndicator] = {}
    for ass in sub_results:
        for ind in ass.indicators:
            if not ind.present:
                continue
            weight = CERTAINTY_WEIGHTS.get(
                ind.certainty
                if isinstance(ind.certainty, LinguisticCertainty)
                else LinguisticCertainty.POSSIBLE,
                0.2,
            )
            if ind.name not in by_name or weight > CERTAINTY_WEIGHTS.get(
                by_name[ind.name].certainty, 0
            ):
                by_name[ind.name] = ind

    first = sub_results[0]
    merged_indicators = list(by_name.values()) if by_name else first.indicators

    # Mimic: union (if any says true, true)
    mimic = MimicContext(
        inflammation=any(a.mimic_context.inflammation for a in sub_results),
        fibrosis=any(a.mimic_context.fibrosis for a in sub_results),
        atelectasis=any(a.mimic_context.atelectasis for a in sub_results),
        post_therapy_changes=any(
            a.mimic_context.post_therapy_changes for a in sub_results
        ),
        artifact_present=any(a.mimic_context.artifact_present for a in sub_results),
    )

    temporal = TemporalEvolution(
        progression_toward_structure=any(
            a.temporal.progression_toward_structure for a in sub_results
        ),
        new_loss_of_interface=any(
            a.temporal.new_loss_of_interface for a in sub_results
        ),
    )

    summaries = [a.summary for a in sub_results if a.summary]
    summary = " ".join(summaries) if summaries else first.summary
    confidence = sum(a.confidence for a in sub_results) / len(sub_results)

    return InfiltrationAssessment(
        indicators=merged_indicators,
        mimic_context=mimic,
        temporal=temporal,
        summary=summary,
        confidence=round(confidence, 2),
    )


def aggregate_negative_findings(
    sub_results: list[tuple[list[str], float]],
) -> tuple[list[str], float]:
    """Intersection of finding lists (only keep if all sub-agents list it); confidence = mean."""
    if not sub_results:
        return [], 0.0
    if len(sub_results) == 1:
        return sub_results[0][0], sub_results[0][1]

    findings_sets = [set(f for f in findings) for findings, _ in sub_results]
    intersection = set.intersection(*findings_sets) if findings_sets else set()
    # Preserve order from first list
    order = sub_results[0][0]
    merged = [f for f in order if f in intersection]
    conf = sum(c for _, c in sub_results) / len(sub_results)
    return merged, round(conf, 2)


def aggregate_organ_assessments(
    sub_results: list[list[OrganAssessment]],
) -> list[OrganAssessment]:
    """One assessment per organ: if any sub-agent says abnormal, use that; else normal; confidence = mean."""
    by_organ: dict[str, list[OrganAssessment]] = defaultdict(list)
    for ass_list in sub_results:
        for oa in ass_list:
            key = oa.organ.strip().lower()
            by_organ[key].append(oa)

    # Preserve order from first list
    order_organs = []
    seen = set()
    for ass_list in sub_results:
        for oa in ass_list:
            key = oa.organ.strip().lower()
            if key not in seen:
                seen.add(key)
                order_organs.append(key)

    merged: list[OrganAssessment] = []
    for key in order_organs:
        list_oa = by_organ.get(key, [])
        if not list_oa:
            continue
        abnormal = [x for x in list_oa if not x.is_normal]
        chosen = abnormal[0] if abnormal else list_oa[0]
        confs = [x.confidence for x in list_oa]
        merged.append(
            OrganAssessment(
                organ=chosen.organ,
                finding=chosen.finding,
                is_normal=chosen.is_normal,
                confidence=round(sum(confs) / len(confs), 2),
            )
        )
    return merged


def aggregate_incidental_findings(
    sub_results: list[list[IncidentalFinding]],
) -> list[IncidentalFinding]:
    """Deduplicate by location (normalized); is_new = any true; confidence = mean per finding."""
    by_location: dict[str, list[IncidentalFinding]] = defaultdict(list)
    for inc_list in sub_results:
        for inc in inc_list:
            key = inc.location.strip().lower()
            by_location[key].append(inc)

    merged: list[IncidentalFinding] = []
    for loc, incs in by_location.items():
        is_new = any(i.is_new for i in incs)
        conf = sum(i.confidence for i in incs) / len(incs)
        # Use first description
        first = incs[0]
        merged.append(
            IncidentalFinding(
                location=first.location,
                description=first.description,
                is_new=is_new,
                confidence=round(conf, 2),
            )
        )
    return merged
