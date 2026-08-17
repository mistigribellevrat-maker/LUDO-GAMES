# tests/conftest.py
"""Fixtures partagées pour la suite de tests de DICTATION WAR.

Stratégie générale : `DictationApp` (main.py) est une classe Tkinter monolithique
qui construit toute son UI dans __init__. On ne l'instancie donc JAMAIS dans les
tests (ce qui ouvrirait une vraie fenêtre Tk, jouerait de la musique et taperait
sur le vrai user_profile.json). À la place, on relie les VRAIES méthodes non liées
(`DictationApp.une_methode.__get__(fake_self)`) à un objet factice minimal
(`types.SimpleNamespace` + `unittest.mock.MagicMock` pour les widgets/IO). On teste
ainsi le code de production exact, sans dupliquer sa logique et sans dépendance Tk.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# main.py, services.py, ui_components.py vivent à la racine du projet, pas dans
# tests/. Il faut donc ajouter la racine au sys.path avant de pouvoir `import main`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as main_module  # noqa: E402  (import après modification de sys.path)

DictationAppClass = main_module.DictationApp


@pytest.fixture(scope="session")
def DictationApp():
    """La classe DictationApp elle-même (jamais instanciée)."""
    return DictationAppClass


@pytest.fixture
def fake_colors():
    """Sous-ensemble de la palette utilisée par les méthodes testées."""
    return {
        "bg": "#0b0f19",
        "panel": "#0f1630",
        "panel2": "#0c142b",
        "accent": "#00e5ff",
        "accent2": "#00ff9c",
        "text": "#c3eaff",
        "muted": "#7aa0c4",
        "danger": "#ff3b5e",
        "warning": "#ffb74d",
    }


@pytest.fixture
def fake_display_errors_app(fake_colors):
    """Double de test pour exercer DictationApp.display_errors (comptage d'erreurs)
    sans widget Tk réel. On relie la vraie méthode display_errors ainsi que la
    vraie _tokenize_words (dont elle dépend) : le calcul de mistake_count testé
    ici est donc exactement celui exécuté en jeu, pas une copie qui pourrait diverger.
    """
    app = SimpleNamespace()
    app.colors = fake_colors
    app.user_text = MagicMock()
    app.errors_frame = MagicMock()
    app.status_label = MagicMock()
    app.lose_points = MagicMock()
    app._clear_errors_frame = MagicMock()
    app._create_error_ui = MagicMock()
    app._tokenize_words = DictationAppClass._tokenize_words.__get__(app)
    app.display_errors = DictationAppClass.display_errors.__get__(app)
    return app


@pytest.fixture
def fake_economy_app():
    """Double de test pour la logique d'économie (armes / aides), sans Tk ni IO."""
    app = SimpleNamespace()
    app.SHOP_ITEMS = DictationAppClass.SHOP_ITEMS
    app.weapon_help_pool = {}
    app.owned_weapons = {}
    app.help_tokens = 0
    app._weapon_spec = DictationAppClass._weapon_spec.__get__(app)
    app._recompute_total_help_tokens = DictationAppClass._recompute_total_help_tokens.__get__(app)
    app._consume_help_from_pool = DictationAppClass._consume_help_from_pool.__get__(app)
    return app


@pytest.fixture
def fake_buy_app(fake_economy_app):
    """Étend fake_economy_app avec ce qu'il faut pour exercer _buy_item()
    (achat en boutique) : credits + IO profil mockée."""
    app = fake_economy_app
    app.credits = 0
    app._save_profile = MagicMock()
    app._update_credits_label = MagicMock()
    app._update_helps_label = MagicMock()
    app._refresh_inventory_ui = MagicMock()
    app._buy_item = DictationAppClass._buy_item.__get__(app)
    return app


@pytest.fixture
def make_profile_app(tmp_path):
    """Fabrique de doubles de test pour _save_profile / _initialize_profile,
    pointant vers un fichier temporaire (tmp_path) : le vrai user_profile.json
    du projet n'est jamais touché.

    avatar_options est délibérément une liste NON VIDE de chemins inexistants
    (et non []) : en production cette liste contient toujours 4 entrées
    codées en dur (main.py __init__, lignes 76-81), qu'elles existent sur
    disque ou non. Une liste vide y déclencherait main.py:369
    (`self.avatar_options[0]` sans garde) -> IndexError sur le chemin de
    repli "profil corrompu" ; ce n'est pas atteignable en production avec la
    liste actuelle, donc on ne le simule pas ici (voir rapport de mission).
    """

    def _factory(**overrides):
        app = SimpleNamespace()
        app.SHOP_ITEMS = DictationAppClass.SHOP_ITEMS
        app.avatar_options = [
            str(tmp_path / "unused_avatar_1.mp4"),
            str(tmp_path / "unused_avatar_2.mp4"),
        ]
        app.profile_path = str(tmp_path / "user_profile.json")
        app.username = None
        app.player_id = None
        app.avatar_path = None
        app.credits = 0
        app.help_tokens = 0
        app.owned_weapons = {}
        app.weapon_help_pool = {}
        app.best_scores = {}
        app.badges = []
        app.levels_played = []
        app.last_play_date = ""
        app.streak = 0
        app.xp = 0
        # Évite d'ouvrir une vraie fenêtre Tk quand le profil est absent.
        app._show_profile_dialog = MagicMock()
        # Évite tout appel réseau (synchro serveur) pendant les tests de persistance.
        app._sync_profile_to_server = MagicMock()
        for key, value in overrides.items():
            setattr(app, key, value)
        app._save_profile = DictationAppClass._save_profile.__get__(app)
        app._initialize_profile = DictationAppClass._initialize_profile.__get__(app)
        return app

    return _factory
