"""Example Agent: Extract Clinical Information from images.

This is a concrete example of how to use the Agent base class.
Customize this for your specific use case.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.agents.agent_base import JsonAgent
from src.domain.clinical_information import ClinicalInformation
from src.services.llm_prompt_service import LLMPrompt, PromptMessage

if TYPE_CHECKING:
    pass


class ClinicalInfoAgent(JsonAgent[ClinicalInformation]):
    """
    Agent that extracts clinical information from medical images.

    Usage:
        agent = ClinicalInfoAgent()
        clinical_info = await agent.process(
            output_model=ClinicalInformation,
            image_paths=[Path("scan.dcm")],
            patient_context="Patient with suspected lung nodule"
        )
    """

    def build_prompt(self, **kwargs) -> LLMPrompt:
        """Build prompt to extract clinical information."""
        image_paths = kwargs.get("image_paths", [])
        patient_context = kwargs.get("patient_context", "")
        seg_path = kwargs.get("seg_path")  # Optional segmentation file

        system_msg = PromptMessage(
            role="system",
            text=(
                "You are a radiologist assistant. Extract clinical information "
                "from the provided medical images and context. Return your response "
                "as a JSON object with the following structure:\n"
                "{\n"
                '  "primary_diagnosis": "Main diagnosis or clinical finding",\n'
                '  "clinical_context": "Additional clinical context or notes",\n'
                '  "patient_sex": "M/F or null",\n'
                '  "patient_age": "Age in format like 054Y or null"\n'
                "}"
            ),
        )

        user_text = "Extract clinical information from these images"
        if patient_context:
            user_text += f".\n\nPatient context: {patient_context}"

        user_msg = PromptMessage(
            role="user",
            text=user_text,
            image_paths=[Path(p) if isinstance(p, str) else p for p in image_paths],
            seg_path=Path(seg_path)
            if seg_path and isinstance(seg_path, str)
            else seg_path,
        )

        return LLMPrompt(messages=[system_msg, user_msg])


class StudyTechniqueAgent(JsonAgent):
    """
    Agent that extracts study technique information from DICOM metadata.

    Usage:
        from src.domain.study_technique import StudyTechnique

        agent = StudyTechniqueAgent()
        technique = await agent.process(
            output_model=StudyTechnique,
            image_paths=[Path("scan.dcm")],
            comparison_date="2025-01-15"
        )
    """

    def build_prompt(self, **kwargs) -> LLMPrompt:
        """Build prompt to extract study technique details."""
        image_paths = kwargs.get("image_paths", [])
        comparison_date = kwargs.get("comparison_date")

        system_msg = PromptMessage(
            role="system",
            text=(
                "You are a radiologist. Extract study technique information "
                "from medical imaging. Return a JSON object:\n"
                "{\n"
                '  "study_description": "Description of regions scanned",\n'
                '  "contrast": "Contrast type used (e.g., IV) or null",\n'
                '  "scanner_model": "Scanner model or null",\n'
                '  "tube_voltage_kvp": 120,\n'
                '  "slice_thickness_mm": 1.5,\n'
                '  "reconstruction_kernel": "Kernel name or null",\n'
                '  "scan_mode": "Scan mode (e.g., HELICAL MODE) or null",\n'
                '  "comparison_study_date": "Date of comparison study or null",\n'
                '  "comparison_accession_number": null\n'
                "}"
            ),
        )

        user_text = "Analyze the imaging study and extract the technique information"
        if comparison_date:
            user_text += f".\n\nPrevious study date: {comparison_date}"

        user_msg = PromptMessage(
            role="user",
            text=user_text,
            image_paths=[Path(p) if isinstance(p, str) else p for p in image_paths],
        )

        return LLMPrompt(messages=[system_msg, user_msg])
