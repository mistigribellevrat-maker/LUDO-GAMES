# tests/test_identity_sync.py
"""HubApp._sync_identity_to_game est une @staticmethod pure (écriture d'un
fichier JSON) : testable sans instancier le Hub, donc sans fenêtre Tk.

Ce que ces tests protègent : le profil local d'un jeu contient AUSSI sa
progression propre (meilleurs scores, inventaire d'armes). Le Hub n'a le droit
d'y écrire que le pseudo et l'avatar — écraser le reste ferait perdre au joueur
ce qu'il a gagné dans le jeu."""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as hub_main  # noqa: E402

sync = hub_main.HubApp._sync_identity_to_game


@pytest.fixture
def game_dir(tmp_path):
    return str(tmp_path)


def read_profile(game_dir):
    with open(Path(game_dir) / "user_profile.json", encoding="utf-8") as f:
        return json.load(f)


class TestSyncIdentity:
    def test_creates_profile_when_missing(self, game_dir):
        sync(game_dir, "Arthur")
        assert read_profile(game_dir) == {"username": "Arthur"}

    def test_writes_avatar_when_provided(self, game_dir):
        sync(game_dir, "Arthur", r"C:\jeux\commun\assets\avatars\1a.mp4")
        data = read_profile(game_dir)
        assert data["username"] == "Arthur"
        assert data["avatar_path"].endswith("1a.mp4")

    def test_preserves_the_games_own_progress(self, game_dir):
        path = Path(game_dir) / "user_profile.json"
        path.write_text(json.dumps({
            "username": "Oscar", "credits": 250,
            "best_scores": {"CM1": 18}, "owned_weapons": {"couteau_laser": 1},
        }), encoding="utf-8")

        sync(game_dir, "Arthur", "/x/1b.mp4")

        data = read_profile(game_dir)
        assert data["username"] == "Arthur"
        assert data["avatar_path"] == "/x/1b.mp4"
        assert data["credits"] == 250
        assert data["best_scores"] == {"CM1": 18}
        assert data["owned_weapons"] == {"couteau_laser": 1}

    def test_no_avatar_given_leaves_the_existing_one_alone(self, game_dir):
        """Le Hub peut ne pas connaître l'avatar (serveur injoignable) : il ne
        doit pas effacer celui que le jeu a déjà."""
        path = Path(game_dir) / "user_profile.json"
        path.write_text(json.dumps({"username": "Arthur", "avatar_path": "/x/1c.mp4"}), encoding="utf-8")

        sync(game_dir, "Arthur", None)

        assert read_profile(game_dir)["avatar_path"] == "/x/1c.mp4"

    def test_identical_identity_does_not_rewrite_the_file(self, game_dir):
        sync(game_dir, "Arthur", "/x/1.mp4")
        path = Path(game_dir) / "user_profile.json"
        before = path.stat().st_mtime_ns
        path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")  # même contenu
        sync(game_dir, "Arthur", "/x/1.mp4")
        assert read_profile(game_dir)["avatar_path"] == "/x/1.mp4"
        assert before is not None  # le fichier existait déjà, aucune exception

    def test_corrupted_profile_is_replaced_not_fatal(self, game_dir):
        (Path(game_dir) / "user_profile.json").write_text("{pas du json", encoding="utf-8")
        sync(game_dir, "Arthur")
        assert read_profile(game_dir) == {"username": "Arthur"}

    def test_unwritable_directory_does_not_raise(self, tmp_path):
        """Un jeu absent (dossier supprimé) ne doit jamais faire planter le Hub."""
        sync(str(tmp_path / "jeu-inexistant"), "Arthur")
