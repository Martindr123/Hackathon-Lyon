# Agent Template Guide

Ce dossier contient le système d'agents pour le traitement d'images médicales avec l'IA.

## Structure

- **`agent_base.py`** : Classe de base abstraite pour tous les agents
- **`example_agents.py`** : Exemples concrets d'implémentation

## Utilisation Rapide

### 1. Créer un agent simple

```python
from src.agents.agent_base import JsonAgent
from src.domain.my_output_model import MyOutput
from src.services.llm_prompt_service import LLMPrompt, PromptMessage
from pathlib import Path

class MyAgent(JsonAgent[MyOutput]):
    def build_prompt(self, **kwargs) -> LLMPrompt:
        # Construire votre prompt
        system_msg = PromptMessage(
            role="system",
            text="You are a radiologist..."
        )
        user_msg = PromptMessage(
            role="user",
            text="Analyze the images",
            image_paths=kwargs.get("image_paths", [])
        )
        return LLMPrompt(messages=[system_msg, user_msg])

# Utilisation
agent = MyAgent()
result = await agent.process(
    output_model=MyOutput,
    image_paths=[Path("image.dcm")]
)
```

### 2. Classe de base : `Agent[OutputType]`

La classe `Agent` est une classe générique abstraite qui gère :
- ✅ Communication avec le service LLM
- ✅ Parsing de la réponse
- ✅ Validation du schéma de sortie

**Méthodes à implémenter :**

| Méthode | Description |
|---------|-------------|
| `build_prompt(**kwargs)` | Construct le `LLMPrompt` |
| `parse_response(response)` | Extrait les données de la réponse LLM |
| `validate_output(data, model)` *optionnel* | Validation personnalisée |

### 3. Classe spécialisée : `JsonAgent[OutputType]`

Optimisée pour les LLMs qui retournent du JSON dans des blocs markdown.

**Hérite de :**
- Gestion automatique du parsing JSON
- Extraction depuis blocs ```json ... ```

**À implémenter :**
- Seulement `build_prompt()`

## Schéma de Sortie

Tous les agents utilisent des modèles **Pydantic** du domaine :

```python
from src.domain.clinical_information import ClinicalInformation
from src.domain.study_technique import StudyTechnique
from src.domain.clinical_report import ClinicalReport

# Retour structuré
agent = ClinicalInfoAgent()
info: ClinicalInformation = await agent.process(
    output_model=ClinicalInformation,
    image_paths=[...]
)
print(info.primary_diagnosis)
print(info.clinical_context)
```

## Architecture

```
Prompt Builder → LLM Service → Response Parser → Validator → Output Model
    (build_prompt)  (llm_service.query)  (parse_response) (Pydantic)
```

## Bonnes Pratiques

✅ **À faire :**
- Utiliser des types génériques pour la réutilisabilité
- Retourner des modèles Pydantic stricts
- Ajouter des logs via le logger
- Gérer les cas d'erreur de parsing

❌ **À éviter :**
- Retourner des dictionnaires bruts sans validation
- Ignorer les erreurs de parsing
- Ne pas documenter le schéma JSON attendu

## Exemple Complet

Voir `example_agents.py` pour des agents fonctionnels :
- `ClinicalInfoAgent` : Extraction d'informations cliniques
- `StudyTechniqueAgent` : Extraction des paramètres techniques

## Integration avec le LLM

Les agents utilisent automatiquement :
- **Service**: `LLMService` (Mistral AI)
- **Prompts**: `LLMPrompt` + `PromptMessage`
- **Support**: Images DICOM, masques de segmentation, contexte texte
