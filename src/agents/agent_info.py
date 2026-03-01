"""Metadata for pipeline agents and image-legend text per task.

Used by the API to expose agent name, role, model and slice-selection rationale
to the frontend.
"""

from __future__ import annotations

# Model ID shown in UI; should match the one used in LLMService (e.g. mistral-large-latest)
DEFAULT_MODEL_ID = "mistral-large-latest"

# Step name (pipeline) -> display name, role, model_id
AGENT_INFO: dict[str, dict[str, str]] = {
    "lesions": {
        "name": "Agent lésions",
        "role": "Localise et caractérise les lésions sur chaque segment SEG.",
        "model_id": DEFAULT_MODEL_ID,
    },
    "infiltration": {
        "name": "Agent infiltrations",
        "role": "Évalue les indicateurs d'infiltration et le contexte (mimic, évolution).",
        "model_id": DEFAULT_MODEL_ID,
    },
    "negative_findings": {
        "name": "Agent findings négatifs",
        "role": "Recherche d'absence de lésion sur les structures clés.",
        "model_id": DEFAULT_MODEL_ID,
    },
    "organ_assessments": {
        "name": "Agent organes",
        "role": "Évalue l'état (normal / anormal) des organes par zone anatomique.",
        "model_id": DEFAULT_MODEL_ID,
    },
    "incidental_findings": {
        "name": "Agent incidental",
        "role": "Détecte les découvertes incidentelles sur tout le volume.",
        "model_id": DEFAULT_MODEL_ID,
    },
    "conclusions": {
        "name": "Agent conclusions",
        "role": "Synthèse (points clés, recommandation, RECIST) à partir du rapport structuré.",
        "model_id": DEFAULT_MODEL_ID,
    },
}

# Slice-selection task -> short legend for "Pourquoi ces images ?"
IMAGE_LEGEND: dict[str, str] = {
    "lesions": "Une image par segment (slice avec la plus grande surface de lésion).",
    "infiltration": "Slices avec pixels SEG non nuls, réparties en groupes pour couvrir tout le volume.",
    "negative_findings": "Deux slices par zone anatomique (thorax, abdomen, pelvis, etc.) pour la recherche d'absence de lésion.",
    "organ_assessments": "Deux slices par zone anatomique pour l'évaluation des organes.",
    "incidental_findings": "Slices réparties uniformément sur le volume pour la recherche de découvertes incidentelles.",
    "conclusions": "Cette étape ne s'appuie pas sur des images (synthèse du rapport).",
}


def get_agent_info(step_name: str) -> dict[str, str]:
    """Return agent metadata for a pipeline step."""
    return AGENT_INFO.get(step_name, {"name": step_name, "role": "", "model_id": DEFAULT_MODEL_ID}).copy()


def get_image_legend(task_or_step: str) -> str:
    """Return the legend text for why we show these images for this task/step."""
    return IMAGE_LEGEND.get(task_or_step, "Images sélectionnées pour cette analyse.")


def list_agent_infos(step_names: list[str]) -> list[dict]:
    """Return list of agent infos for the given step names (for /agent-info endpoint)."""
    return [{"step": s, **get_agent_info(s)} for s in step_names]
