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
        technique_line += "."
        if tech.comparison_study_date:
            technique_line += f" Compares to previous CT available on {tech.comparison_study_date}."
        parts.append(technique_line)

        report_lines = ["REPORT."]
        for lc in self.report.lesion_comparisons:
            curr = "x".join(f"{d:.0f}" for d in lc.current_dimensions_mm)
            prev = "x".join(f"{d:.0f}" for d in lc.previous_dimensions_mm)
            report_lines.append(
                f"- {lc.location}: {curr}mm ({lc.change_description}, anterior {prev}mm)"
            )
        for lm in self.report.lesion_measurements:
            if not any(lc.location == lm.location for lc in self.report.lesion_comparisons):
                dims = "x".join(f"{d:.0f}" for d in lm.dimensions_mm)
                line = f"- {lm.location}: {dims}mm"
                if lm.characterization:
                    line += f", {lm.characterization}"
                report_lines.append(line)
        for oa in self.report.organ_assessments:
            report_lines.append(f"- {oa.organ}: {oa.finding}")
        for nf in self.report.negative_findings:
            report_lines.append(f"- {nf}")
        for inc in self.report.incidental_findings:
            report_lines.append(f"- {inc.location}: {inc.description}")
        if self.report.free_text:
            report_lines.append(self.report.free_text)
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
