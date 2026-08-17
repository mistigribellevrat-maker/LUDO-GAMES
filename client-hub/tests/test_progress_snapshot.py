# tests/test_progress_snapshot.py
"""HubApp._read_progress_snapshot est une @staticmethod pure (lecture de
fichier local, aucun Tk) : testable directement sans construire de fenêtre."""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as hub_main  # noqa: E402

read_snapshot = hub_main.HubApp._read_progress_snapshot


@pytest.fixture
def fake_game_dir(tmp_path, monkeypatch):
    """Simule _HERE (dossier du hub) pour que game_dir se résolve sous tmp_path,
    sans jamais toucher aux vrais dossiers de jeux du projet."""
    monkeypatch.setattr(hub_main, "_HERE", str(tmp_path))
    game_dir = tmp_path / "client-fake"
    game_dir.mkdir()
    return game_dir, "client-fake"


class TestReadProgressSnapshot:
    def test_missing_profile_returns_zeroed_snapshot(self, fake_game_dir):
        _game_dir, rel = fake_game_dir
        assert read_snapshot(rel) == {"credits": 0, "xp": 0, "badges": []}

    def test_reads_credits_xp_badges(self, fake_game_dir):
        game_dir, rel = fake_game_dir
        (game_dir / "user_profile.json").write_text(
            json.dumps({"credits": 250, "xp": 430, "badges": ["premiere_victoire"]}),
            encoding="utf-8",
        )
        assert read_snapshot(rel) == {"credits": 250, "xp": 430, "badges": ["premiere_victoire"]}

    def test_malformed_json_falls_back_to_zeroed_snapshot(self, fake_game_dir):
        game_dir, rel = fake_game_dir
        (game_dir / "user_profile.json").write_text("{pas du json valide", encoding="utf-8")
        assert read_snapshot(rel) == {"credits": 0, "xp": 0, "badges": []}

    def test_non_dict_json_falls_back_to_zeroed_snapshot(self, fake_game_dir):
        game_dir, rel = fake_game_dir
        (game_dir / "user_profile.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert read_snapshot(rel) == {"credits": 0, "xp": 0, "badges": []}

    def test_missing_keys_default_safely(self, fake_game_dir):
        game_dir, rel = fake_game_dir
        (game_dir / "user_profile.json").write_text("{}", encoding="utf-8")
        assert read_snapshot(rel) == {"credits": 0, "xp": 0, "badges": []}

    def test_non_list_badges_default_to_empty_list(self, fake_game_dir):
        game_dir, rel = fake_game_dir
        (game_dir / "user_profile.json").write_text(
            json.dumps({"badges": "pas-une-liste"}), encoding="utf-8"
        )
        assert read_snapshot(rel)["badges"] == []
