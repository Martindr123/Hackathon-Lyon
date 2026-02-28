from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field

from src.repositories.liste_examen_repo import ListeExamenRepo, Examen
from src.repositories.data_repo import DataRepo, StudyInfo


@dataclass
class PromptMessage:
    """A single message in the prompt conversation (text or image reference)."""

    role: str  # "system" or "user"
    text: str | None = None
    image_paths: list[Path] = field(default_factory=list)


@dataclass
class LLMPrompt:
    """Complete prompt ready to be sent to a multimodal LLM."""

    messages: list[PromptMessage] = field(default_factory=list)

    @property
    def system_message(self) -> str | None:
        for m in self.messages:
            if m.role == "system":
                return m.text
        return None

    @property
    def all_image_paths(self) -> list[Path]:
        paths: list[Path] = []
        for m in self.messages:
            paths.extend(m.image_paths)
        return paths


SYSTEM_PROMPT = """\
You are a senior radiologist assistant. Your task is to generate a clinical \
radiology report for the patient's latest CT scan examination.

You will be provided with:
1. The patient's previous clinical reports (chronological order), including \
lesion measurements.
2. CT scan images from previous examinations for comparison.
3. CT scan images from the current (latest) examination that you must report on.

Based on all this information, write a structured clinical report for the \
current examination following this format:

CLINICAL INFORMATION. <relevant clinical context>
STUDY TECHNIQUE. <imaging technique used>
REPORT. <detailed findings, comparing with previous exams when relevant, \
noting any changes in lesion size or appearance>
CONCLUSIONS. <summary of key findings and recommendations>

Important guidelines:
- Compare lesion sizes with previous measurements when available.
- Note any new findings or changes from prior examinations.
- Use precise medical terminology.
- Mention the comparison studies used.\
"""


def _format_exam_history_block(examen: Examen, study: StudyInfo | None) -> str:
    """Format a single past exam into a text block for the prompt."""
    lines = [
        f"--- Exam (AccessionNumber: {examen.accession_number}) ---",
        f"Study: {study.description if study else 'N/A'}",
        f"Series with segmentation masks: {examen.serie}",
        f"Lesion sizes (mm): {', '.join(f'{s:.1f}' for s in examen.lesion_sizes_mm)}",
    ]
    if examen.max_lesion_size is not None:
        lines.append(f"Max lesion size: {examen.max_lesion_size:.1f} mm")

    lines.append("")
    lines.append("Clinical report:")
    lines.append(examen.clinical_info.strip())
    lines.append("")
    return "\n".join(lines)


class LLMPromptService:
    def __init__(
        self,
        examen_repo: ListeExamenRepo | None = None,
        data_repo: DataRepo | None = None,
    ):
        self._examen_repo = examen_repo or ListeExamenRepo()
        self._data_repo = data_repo or DataRepo()

    def build_report_prompt(
        self,
        patient_id: str,
        current_accession_number: int | None = None,
        ct_series_filter: str | None = None,
    ) -> LLMPrompt:
        """Build a full prompt to generate the clinical report for the latest exam.

        Args:
            patient_id: The patient ID.
            current_accession_number: The accession number of the exam to report on.
                If None, uses the last exam chronologically.
            ct_series_filter: Optional series name filter (e.g. "lung", "torax")
                to limit which CT images are included. If None, all CT series
                are included.
        """
        history = self._examen_repo.get_patient_history(patient_id)
        if not history:
            raise ValueError(f"No exams found for patient {patient_id}")

        if current_accession_number is not None:
            current_exam = next(
                (e for e in history if e.accession_number == current_accession_number),
                None,
            )
            if current_exam is None:
                raise ValueError(
                    f"Accession {current_accession_number} not found for patient {patient_id}"
                )
            previous_exams = [e for e in history if e.accession_number != current_accession_number]
        else:
            current_exam = history[-1]
            previous_exams = history[:-1]

        prompt = LLMPrompt()

        # 1. System message
        prompt.messages.append(PromptMessage(role="system", text=SYSTEM_PROMPT))

        # 2. Previous exams: text + images
        if previous_exams:
            history_text_parts = [
                f"## Patient history ({len(previous_exams)} previous exam(s))\n"
            ]
            previous_images: list[Path] = []

            for exam in previous_exams:
                study = self._data_repo.get_study(patient_id, exam.accession_number)
                history_text_parts.append(_format_exam_history_block(exam, study))

                if study:
                    previous_images.extend(
                        self._get_ct_images(study, ct_series_filter)
                    )

            prompt.messages.append(
                PromptMessage(
                    role="user",
                    text="\n".join(history_text_parts),
                    image_paths=previous_images,
                )
            )

        # 3. Current exam: metadata + images
        current_study = self._data_repo.get_study(patient_id, current_exam.accession_number)
        current_images = (
            self._get_ct_images(current_study, ct_series_filter) if current_study else []
        )

        current_text_parts = [
            "## Current examination to report on\n",
            f"AccessionNumber: {current_exam.accession_number}",
            f"Study: {current_study.description if current_study else 'N/A'}",
            f"Series with segmentation masks: {current_exam.serie}",
            f"Lesion sizes (mm): {', '.join(f'{s:.1f}' for s in current_exam.lesion_sizes_mm)}",
            "",
            "Please generate the clinical report for this examination, "
            "comparing with the previous exams provided above.",
        ]

        prompt.messages.append(
            PromptMessage(
                role="user",
                text="\n".join(current_text_parts),
                image_paths=current_images,
            )
        )

        return prompt

    def _get_ct_images(
        self, study: StudyInfo, series_filter: str | None
    ) -> list[Path]:
        if series_filter:
            lower = series_filter.lower()
            series_list = [s for s in study.ct_series if lower in s.name.lower()]
        else:
            series_list = study.ct_series
        return [f for series in series_list for f in series.dicom_files]
