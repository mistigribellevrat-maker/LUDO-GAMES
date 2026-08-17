# tests/conftest.py
"""Chemins d'import partagés par la suite du Hub.

Les modules du Hub (`main`, `leaderboard`, `avatar_picker`) importent le code
partagé de `commun/` (thème, widgets, barème, client serveur). En exécution,
c'est `main.py` qui ajoute `commun/` au sys.path au démarrage — mais un test
qui importe directement `avatar_picker` n'est pas passé par là. On refait donc
ici la même résolution que `main.py` : dossier `commun/` distribué à côté, ou
dossier frère en dev."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

for _candidate in (PROJECT_ROOT / "commun", PROJECT_ROOT.parent / "commun"):
    if _candidate.is_dir():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break
else:  # pragma: no cover - filet de sécurité, jamais atteint dans le dépôt
    raise RuntimeError(f"Dossier commun/ introuvable depuis {PROJECT_ROOT}")

os.environ.setdefault("SERVER_URL", "")  # aucun test du Hub ne parle au réseau
