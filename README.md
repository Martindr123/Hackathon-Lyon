# Hackathon Lyon

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

### 3. Installer les dépendances

```bash
pip install -r requirements.txt
```

> ⚠️ **Attention** : pas d'espace entre `-r` et le nom du fichier. Utilisez `pip install -r requirements.txt` et non `pip install - r requirements.txt`.

### 4. Lancer l'application

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
