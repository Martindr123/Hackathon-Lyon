from __future__ import annotations

from pydantic import BaseModel

from src.domain.clinical_information import ClinicalInformation
from src.domain.study_technique import StudyTechnique
from src.domain.report_findings import ReportFindings
from src.domain.conclusions import Conclusions


class ClinicalReport(BaseModel):
    """Complete structured clinical radiology report."""

    patient_id: str
    accession_number: int
    clinical_information: ClinicalInformation
    study_technique: StudyTechnique
    report: ReportFindings
    conclusions: Conclusions

    def to_text(self) -> str:
        """Render the report as a human-readable text block."""
        parts: list[str] = []

        parts.append(
            f"CLINICAL INFORMATION. {self.clinical_information.primary_diagnosis}. "
            f"{self.clinical_information.clinical_context}"
        )

        tech = self.study_technique
        technique_line = f"STUDY TECHNIQUE. {tech.study_description}"
        if tech.contrast:
            technique_line += f" after administration of {tech.contrast} contrast"
        if tech.contrast_agent:
            technique_line += f" ({tech.contrast_agent})"
        technique_line += "."
        if tech.comparison_study_date:
            technique_line += (
                f" Compares to previous CT available on {tech.comparison_study_date}."
            )
        parts.append(technique_line)

        det = self.report.report_determinist
        agt = self.report.report_agent

        report_lines = ["REPORT."]

        n_lesions = max(len(det.lesions), len(agt.lesions))
        for i in range(n_lesions):
            d = det.lesions[i] if i < len(det.lesions) else None
            a = agt.lesions[i] if i < len(agt.lesions) else None

            location = a.location if a else f"Lesion {i + 1}"
            dims = "x".join(f"{v:.0f}" for v in d.dimensions_mm) if d else "?"
            line = f"- {location}: {dims}mm"
            if d and d.short_axis_mm is not None:
                line += f" (short axis {d.short_axis_mm:.0f}mm)"

            if d and d.previous_dimensions_mm:
                prev = "x".join(f"{v:.0f}" for v in d.previous_dimensions_mm)
                line += f" (anterior {prev}mm)"
            if d and d.evolution:
                line += f". {d.evolution}"
            if d and d.slice_index is not None:
                line += f" (image {d.slice_index})"
            if a and a.characterization:
                line += f". {a.characterization}"

            report_lines.append(line)

        if det.recist_conclusion:
            report_lines.append(f"RECIST 1.1: {det.recist_conclusion}")

        adv = det.advanced_metrics
        if adv.total_tumor_burden_ml is not None:
            burden_line = f"Total tumor burden: {adv.total_tumor_burden_ml:.1f} mL"
            if adv.tumor_burden_change_percent is not None:
                burden_line += f" ({adv.tumor_burden_change_percent:+.1f}%)"
            report_lines.append(burden_line)

        if adv.v_recist_conclusion:
            report_lines.append(f"Volumetric RECIST: {adv.v_recist_conclusion}")
            if adv.v_recist_justification:
                report_lines.append(f"  {adv.v_recist_justification}")

        for lm in adv.lesion_metrics:
            parts_lm: list[str] = []
            if lm.growth_rate_percent_per_month is not None:
                parts_lm.append(f"TGR {lm.growth_rate_percent_per_month:+.1f}%/month")
            if lm.doubling_time_days is not None:
                parts_lm.append(f"doubling time {lm.doubling_time_days:.0f}d")
            if lm.hu_heterogeneity_index is not None:
                parts_lm.append(
                    f"HU {lm.hu_mean:.0f}±{lm.hu_std:.0f} "
                    f"(heterogeneity {lm.hu_heterogeneity_index:.2f})"
                )
            if parts_lm:
                report_lines.append(
                    f"- Lesion {lm.segment_number}: {', '.join(parts_lm)}"
                )

        if adv.trend_direction:
            trend_line = f"Trend: {adv.trend_direction}"
            if adv.consecutive_stable_exams and adv.consecutive_stable_exams > 0:
                trend_line += (
                    f" ({adv.consecutive_stable_exams} consecutive stable exams)"
                )
            if adv.change_from_nadir_percent is not None and adv.change_from_nadir_percent > 0:
                trend_line += f", +{adv.change_from_nadir_percent:.1f}% from nadir"
            report_lines.append(trend_line)

        infilt = agt.infiltration
        if infilt.present_indicators:
            report_lines.append(
                f"- Infiltration ({infilt.level.value}): "
                f"{infilt.summary or 'See indicators'}"
            )
        for oa in agt.organ_assessments:
            report_lines.append(f"- {oa.organ}: {oa.finding}")
        for nf in agt.negative_findings:
            report_lines.append(f"- {nf}")
        for inc in agt.incidental_findings:
            report_lines.append(f"- {inc.location}: {inc.description}")

        parts.append("\n".join(report_lines))

        concl_lines = ["CONCLUSIONS."]
        if self.conclusions.recist_response:
            concl_lines.append(
                f"Findings compatible with {self.conclusions.recist_response} "
                f"according to RECIST criteria."
            )
        if self.conclusions.recist_justification:
            concl_lines.append(self.conclusions.recist_justification)
        for kf in self.conclusions.key_findings:
            concl_lines.append(f"- {kf}")
        if self.conclusions.recommendation:
            concl_lines.append(self.conclusions.recommendation)
        parts.append(" ".join(concl_lines))

        return "\n\n".join(parts)
