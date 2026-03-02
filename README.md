# RadioAssist — Clinical Report Generator

**RadioAssist** est une application d'aide à la rédaction de comptes rendus de radiologie oncologique, développée lors du Hackathon Unboxed 2026 à Lyon. Elle génère des rapports structurés à partir d'examens DICOM (scanner thoracique, abdominal et pelvien) en combinant une analyse déterministe et des agents LLM.

---

## Présentation

L'objectif de RadioAssist est d'assister les radiologues dans la rédaction de leurs comptes rendus en automatisant l'analyse des images médicales tout en conservant un contrôle humain à chaque étape (*human-in-the-loop*).

L'application prend en entrée des données DICOM (images CT, masques de segmentation, rapports structurés) ainsi que des informations cliniques (fichier Excel), et produit un rapport complet couvrant :

- La **localisation et caractérisation des lésions**
- L'évaluation de l'**infiltration** (vaisseaux, structures adjacentes)
- Les **findings négatifs** (structures normales)
- L'évaluation des **organes**
- Les **découvertes fortuites**
- Les **conclusions** avec recommandation et classification RECIST

---

## Fonctionnalités

### Génération de rapports

- **Quick Generate** : génération directe en une passe (~30 s), sans validation intermédiaire.
- **Generate Report** : pipeline interactif en 6 étapes avec validation et possibilité de relance à chaque étape.

### Pipeline interactif

Le rapport est construit progressivement en 6 étapes. À chaque étape, le radiologue peut valider, modifier manuellement ou relancer l'agent avec une remarque :

1. **Lésions** — localisation anatomique, caractérisation, niveau de confiance
2. **Infiltration** — niveau (aucun, contact simple, suspicion, certain) et indicateurs
3. **Findings négatifs** — structures normales identifiées
4. **Évaluation des organes** — état normal ou anormal par organe
5. **Découvertes fortuites** — anomalies non attendues
6. **Conclusions** — synthèse, recommandation, classification RECIST

### Visualisation

- Carrousel d'images avec overlay des masques de segmentation
- Navigation dans le volume 3D (slider entre les coupes)
- Comparaison côte à côte avec l'examen précédent

### Export

- Copie texte
- Export JSON
- Export PDF (via jsPDF)

---

## Architecture

```
Hackathon-Lyon/
├── main.py                         # Point d'entrée FastAPI
├── requirements.txt
├── .env                            # Clé API Mistral
│
├── app/                            # Frontend (HTML / CSS / JS vanilla)
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── src/
│   ├── api/                        # Contrôleurs et services HTTP
│   │   ├── report_controller.py    #   Routes /api/v1/reports
│   │   ├── image_service.py        #   Préparation des images
│   │   └── session_manager.py      #   Gestion des sessions en mémoire
│   │
│   ├── domain/                     # Modèles Pydantic (entités métier)
│   │   ├── clinical_report.py
│   │   ├── report_findings.py
│   │   ├── report_determinist.py
│   │   ├── report_agent.py
│   │   └── ...
│   │
│   ├── agents/                     # Agents LLM (Mistral vision + texte)
│   │   ├── lesions_agent.py
│   │   ├── infiltration_agent.py
│   │   ├── negative_findings_agent.py
│   │   ├── organ_assessments_agent.py
│   │   ├── incidental_findings_agent.py
│   │   ├── conclusions_agent.py
│   │   ├── remark_guard_agent.py
│   │   └── ...
│   │
│   ├── determinist/                # Analyse déterministe (sans LLM)
│   │   ├── report_determinist/
│   │   │   ├── builder.py          #   Construction du rapport
│   │   │   ├── recist.py           #   Calculs RECIST 1.1
│   │   │   └── seg_analyzer.py     #   Analyse des segmentations
│   │   └── advanced_metrics/       #   Métriques avancées (TGR, hétérogénéité)
│   │
│   ├── services/                   # Services externes
│   │   ├── llm_service.py          #   Client Mistral AI
│   │   └── llm_prompt_service.py   #   Construction des prompts
│   │
│   ├── repositories/               # Accès aux données
│   │   ├── data_repo.py            #   Lecture DICOM
│   │   └── liste_examen_repo.py    #   Lecture Excel
│   │
│   └── uses_cases/                 # Cas d'usage
│       ├── create_last_report.py
│       └── interactive_pipeline.py
```

### Flux de données

```
Données DICOM (CT, SEG, SR)  ──┐
                                ├──▶  ExamContext  ──▶  Analyse déterministe (RECIST, volumes)
Données cliniques (Excel)    ──┘                   ──▶  Agents LLM (Mistral vision)
                                                               │
                                                               ▼
                                                       ClinicalReport
```

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend | **FastAPI** + uvicorn |
| LLM | **Mistral AI** (`mistral-large-latest`, vision) |
| Imagerie médicale | SimpleITK, MONAI, OpenCV, scikit-image |
| DICOM | pydicom, dicom2nifti, nibabel |
| Données cliniques | pandas, openpyxl |
| Frontend | HTML / CSS / JS vanilla, jsPDF |
| Configuration | python-dotenv |

---

## Démarrage du projet

### 1. Créer l'environnement virtuel

```bash
python3 -m venv env
```

### 2. Activer l'environnement virtuel

**Sur macOS / Linux :**
```bash
source env/bin/activate
```

**Sur Windows (PowerShell) :**
```powershell
.\env\Scripts\Activate.ps1
```

**Sur Windows (cmd) :**
```cmd
.\env\Scripts\activate.bat
```

Une fois activé, le préfixe `(env)` apparaît dans votre terminal.

### 3. Configurer la clé API

Copier `.env_template` vers `.env` et renseigner votre clé API Mistral :

```bash
cp .env_template .env
```

### 4. Installer les dépendances

```bash
pip install -r requirements.txt
```

> ⚠️ **Attention** : pas d'espace entre `-r` et le nom du fichier. Utilisez `pip install -r requirements.txt` et non `pip install - r requirements.txt`.

### 5. Lancer l'application

Depuis la racine du projet (avec l'environnement virtuel activé) :

```bash
uvicorn main:app --reload
```

L'interface sera disponible à l'adresse : **http://localhost:8000**

- `--reload` recharge automatiquement le serveur quand vous modifiez le code (optionnel en développement).

---

## Commandes utiles

| Action | Commande |
|--------|----------|
| Désactiver le venv | `deactivate` |
| Mettre à jour pip | `pip install --upgrade pip` |

---

## Illustrations

<!-- Remplacez les chemins ci-dessous par vos captures d'écran -->

![Capture 1 — Interface principale](docs/screenshot-1.png)

![Capture 2 — Rapport généré](docs/screenshot-2.png)
