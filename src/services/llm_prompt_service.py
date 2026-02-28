from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import SimpleITK as sitk
import pydicom

from src.repositories.liste_examen_repo import ListeExamenRepo, Examen
from src.repositories.data_repo import DataRepo, StudyInfo


@dataclass
class PromptMessage:
    """A single message in the prompt conversation (text or image reference)."""

    role: str  # "system" or "user"
    text: str | None = None
    image_paths: list[Path] = field(default_factory=list)
    seg_path: Path | None = None
    series_files: list[Path] = field(default_factory=list)


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
2. CT scan images from the current (latest) examination that you must report on. \
Lesions annotated by the radiologist are highlighted in red on the images.

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
- Mention the comparison studies used.
- Red overlays on images indicate radiologist-annotated segmentation masks \
of lesions of interest.\
"""


def _extract_ct_metadata(ct_path: Path) -> dict[str, str]:
    """Read relevant metadata from a CT DICOM file."""
    ds = pydicom.dcmread(str(ct_path), stop_before_pixels=True)
    meta: dict[str, str] = {}
    tag_map = {
        "PatientSex": "Patient sex",
        "PatientAge": "Patient age",
        "StudyDate": "Study date",
        "StudyDescription": "Study description",
        "SeriesDescription": "Series description",
        "BodyPartExamined": "Body part",
        "Manufacturer": "Scanner manufacturer",
        "ManufacturerModelName": "Scanner model",
        "KVP": "Tube voltage (kVp)",
        "SliceThickness": "Slice thickness (mm)",
        "ConvolutionKernel": "Reconstruction kernel",
        "ContrastBolusRoute": "Contrast route",
        "ScanOptions": "Scan mode",
        "PatientComments": "Protocol",
        "WindowCenter": "Default window center",
        "WindowWidth": "Default window width",
    }
    for attr, label in tag_map.items():
        val = getattr(ds, attr, None)
        if val is not None and str(val).strip():
            meta[label] = str(val)

    pixel_spacing = getattr(ds, "PixelSpacing", None)
    if pixel_spacing:
        meta["Pixel spacing (mm)"] = f"{pixel_spacing[0]:.3f} x {pixel_spacing[1]:.3f}"

    return meta


def _format_metadata_block(metadata: dict[str, str]) -> str:
    lines = ["### CT acquisition metadata"]
    for label, value in metadata.items():
        lines.append(f"- {label}: {value}")
    return "\n".join(lines)


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
        max_slices_per_exam: int = 20,
    ) -> LLMPrompt:
        """Build a full prompt to generate the clinical report for the latest exam.

        Only the CT series matching the Excel "Série avec les masques de DICOM SEG"
        column is included (the clinically relevant one). Slices are evenly
        subsampled to keep the image count manageable for LLMs.
        Images are sent as overlays with the segmentation mask highlighted in red.
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

        # 2. Previous exams: text only (reports already describe the images)
        if previous_exams:
            history_text_parts = [
                f"## Patient history ({len(previous_exams)} previous exam(s))\n"
            ]

            for exam in previous_exams:
                study = self._data_repo.get_study(patient_id, exam.accession_number)
                history_text_parts.append(_format_exam_history_block(exam, study))

            prompt.messages.append(
                PromptMessage(
                    role="user",
                    text="\n".join(history_text_parts),
                )
            )

        # 3. Current exam: metadata + overlay images
        current_study = self._data_repo.get_study(patient_id, current_exam.accession_number)

        ct_series = self._match_series(current_study, current_exam.serie) if current_study else None
        all_series_files = ct_series.dicom_files if ct_series else []

        seg_path = None
        if current_study and current_study.segmentation and current_study.segmentation.dicom_files:
            seg_path = current_study.segmentation.dicom_files[0]

        sampled_files = _subsample(all_series_files, max_slices_per_exam, seg_path)

        # Extract CT metadata from the first available slice
        ct_metadata: dict[str, str] = {}
        if sampled_files:
            ct_metadata = _extract_ct_metadata(sampled_files[0])

        current_text_parts = [
            "## Current examination to report on\n",
            f"AccessionNumber: {current_exam.accession_number}",
            f"Study: {current_study.description if current_study else 'N/A'}",
            f"Series with segmentation masks: {current_exam.serie}",
            f"Lesion sizes (mm): {', '.join(f'{s:.1f}' for s in current_exam.lesion_sizes_mm)}",
        ]
        if ct_metadata:
            current_text_parts.append("")
            current_text_parts.append(_format_metadata_block(ct_metadata))

        current_text_parts.extend([
            "",
            "The following CT images have the radiologist's segmentation overlaid "
            "in red where lesions were annotated.",
            "",
            "Please generate the clinical report for this examination, "
            "comparing with the previous exams provided above.",
        ])

        prompt.messages.append(
            PromptMessage(
                role="user",
                text="\n".join(current_text_parts),
                image_paths=sampled_files,
                seg_path=seg_path,
                series_files=all_series_files,
            )
        )

        return prompt

    @staticmethod
    def _match_series(study: StudyInfo, serie_label: str) -> "SeriesInfo | None":
        """Match the Excel 'Série avec les masques de DICOM SEG' value to an
        actual CT series folder.

        Excel label examples:  "S2 CEV torax"       → "CT CEV torax"
                               "S3 1.25 mm Pulmon"  → "CT 1.25mm Pulmn"
        """
        keywords = serie_label.lower().split()[1:]  # drop the "S2"/"S3" prefix
        for series in study.ct_series:
            name_lower = series.name.lower()
            if all(kw in name_lower for kw in keywords):
                return series
        if keywords:
            for series in study.ct_series:
                if keywords[0] in series.name.lower():
                    return series
        return None


def _subsample(
    files: list[Path],
    max_count: int,
    seg_path: Path | None = None,
) -> list[Path]:
    """Return at most *max_count* items from *files*.

    Slices containing a segmentation mask are always included first.
    The remaining budget is filled with evenly-spaced slices from the rest.
    """
    n = len(files)
    if n <= max_count:
        return files

    seg_indices: set[int] = set()
    if seg_path:
        try:
            seg_img = sitk.ReadImage(str(seg_path))
            seg_arr = sitk.GetArrayFromImage(seg_img)
            seg_indices = {i for i in range(min(seg_arr.shape[0], n)) if seg_arr[i].any()}
        except Exception:
            pass

    seg_indices = {i for i in seg_indices if i < n}

    if len(seg_indices) >= max_count:
        seg_list = sorted(seg_indices)
        step = len(seg_list) / max_count
        chosen = sorted({seg_list[int(i * step)] for i in range(max_count)})
        return [files[i] for i in chosen]

    remaining_budget = max_count - len(seg_indices)
    other_indices = [i for i in range(n) if i not in seg_indices]
    step = len(other_indices) / remaining_budget if remaining_budget > 0 else 1
    sampled_others = {other_indices[int(i * step)] for i in range(remaining_budget)}

    chosen = sorted(seg_indices | sampled_others)
    return [files[i] for i in chosen]


if __name__ == "__main__":
    import sys

    service = LLMPromptService()
    patient_id = sys.argv[1] if len(sys.argv) > 1 else "0301B7D6"
    max_slices = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    prompt = service.build_report_prompt(patient_id, max_slices_per_exam=max_slices)

    print(f"Patient: {patient_id}  |  max_slices_per_exam: {max_slices}")
    print(f"Messages: {len(prompt.messages)}")
    print(f"Total DICOM images: {len(prompt.all_image_paths)}")
    print("=" * 80)

    for i, msg in enumerate(prompt.messages):
        print(f"\n{'=' * 80}")
        print(f"MESSAGE {i}  |  role={msg.role}  |  images={len(msg.image_paths)}")
        if msg.seg_path:
            print(f"  SEG: {msg.seg_path.name}")
        print("=" * 80)
        if msg.text:
            print(msg.text)
        if msg.image_paths:
            print(f"\n  >> {len(msg.image_paths)} DICOM images attached (overlay)")
            print(f"     first: {msg.image_paths[0].name}")
            print(f"     last:  {msg.image_paths[-1].name}")
