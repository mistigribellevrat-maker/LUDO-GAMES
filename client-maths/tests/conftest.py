# tests/conftest.py
"""Fixtures partagées — même stratégie que client-dictee/tests/conftest.py :
`MathsApp` n'est JAMAIS instanciée dans les tests (ce qui ouvrirait une vraie
fenêtre Tk). On relie les VRAIES méthodes non liées à un double de test minimal
(`types.SimpleNamespace`), pour tester le code de production exact sans Tk."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as main_module  # noqa: E402

MathsAppClass = main_module.MathsApp


@pytest.fixture
def make_profile_app(tmp_path):
    """Fabrique de doubles de test pour _load_profile / _save_profile, pointant
    vers un fichier sous tmp_path : le vrai user_profile.json du projet n'est
    jamais touché."""

    def _factory(**overrides):
        app = SimpleNamespace()
        app.profile_path = str(tmp_path / "user_profile.json")
        app.username = None
        app.avatar_path = None
        app.best_scores = {}
        app.credits = 0
        app.xp = 0
        app.badges = []
        app.streak = 0
        app.last_play_date = ""
        app.high_scores_enabled = False  # pas d'appel réseau dans ces tests
        app.high_score_service = None
        for key, value in overrides.items():
            setattr(app, key, value)
        app._sync_profile_to_server = MagicMock()
        app._load_profile = MathsAppClass._load_profile.__get__(app)
        app._save_profile = MathsAppClass._save_profile.__get__(app)
        return app

    return _factory
