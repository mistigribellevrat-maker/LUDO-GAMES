# tests/test_server_config.py
"""Tests de la résolution de config du serveur de scores partagée entre jeux
(server_client.load_server_config / save_server_config_override / HighScoreService).

Isolé du vrai server_config.json / server_config.local.json via monkeypatch des
chemins : aucun fichier réel n'est lu ni écrit.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server_client  # noqa: E402


@pytest.fixture
def isolated_config_paths(tmp_path, monkeypatch):
    local = tmp_path / "server_config.local.json"
    default = tmp_path / "server_config.json"
    monkeypatch.setattr(server_client, "_LOCAL_SERVER_CONFIG", str(local))
    monkeypatch.setattr(server_client, "_DEFAULT_SERVER_CONFIG", str(default))
    monkeypatch.delenv("SERVER_URL", raising=False)
    monkeypatch.delenv("SERVER_TOKEN", raising=False)
    monkeypatch.delenv("SERVER_GAME", raising=False)
    return local, default


def test_no_config_anywhere_returns_empty(isolated_config_paths):
    config = server_client.load_server_config()
    assert config == {"server_url": "", "server_token": "", "game": ""}


def test_falls_back_to_env_vars(isolated_config_paths, monkeypatch):
    monkeypatch.setenv("SERVER_URL", "http://10.0.0.5:8000")
    monkeypatch.setenv("SERVER_TOKEN", "secret")
    monkeypatch.setenv("SERVER_GAME", "maths")
    config = server_client.load_server_config()
    assert config == {"server_url": "http://10.0.0.5:8000", "server_token": "secret", "game": "maths"}


def test_default_config_file_used_when_no_local_override(isolated_config_paths):
    local, default = isolated_config_paths
    default.write_text(
        '{"server_url": "http://192.168.1.50:8000", "server_token": "", "game": "dictee"}', encoding="utf-8"
    )
    config = server_client.load_server_config()
    assert config["server_url"] == "http://192.168.1.50:8000"
    assert config["game"] == "dictee"


def test_local_override_takes_priority_over_default(isolated_config_paths):
    local, default = isolated_config_paths
    default.write_text(
        '{"server_url": "http://192.168.1.50:8000", "server_token": "", "game": "dictee"}', encoding="utf-8"
    )
    local.write_text('{"server_url": "http://10.0.0.9:8000", "server_token": "abc"}', encoding="utf-8")
    config = server_client.load_server_config()
    # server_url/server_token viennent du fichier local (réglage propre à ce PC).
    # "game" reste TOUJOURS lu depuis le fichier par défaut, jamais depuis le
    # local : c'est une propriété du jeu installé dans ce dossier, pas du PC.
    # Sinon, corriger l'adresse du serveur dans Paramètres sur un jeu autre que
    # la dictée ferait retomber silencieusement sur "dictee" (bug réel détecté
    # en test d'intégration : voir git blame de ce commentaire).
    assert config == {"server_url": "http://10.0.0.9:8000", "server_token": "abc", "game": "dictee"}


def test_local_override_never_shadows_game_even_for_non_dictee_installs(isolated_config_paths):
    """Cas concret qui a révélé le bug : un jeu de maths (game="maths" dans son
    propre server_config.json) dont le joueur corrige l'adresse du serveur dans
    Paramètres (server_config.local.json, sans "game") doit continuer à
    soumettre ses scores/profil sous "maths", pas "dictee"."""
    local, default = isolated_config_paths
    default.write_text(
        '{"server_url": "http://192.168.1.50:8000", "server_token": "", "game": "maths"}', encoding="utf-8"
    )
    local.write_text('{"server_url": "http://10.0.0.9:8000", "server_token": ""}', encoding="utf-8")
    config = server_client.load_server_config()
    assert config["game"] == "maths"


def test_malformed_local_override_falls_back_to_default(isolated_config_paths):
    local, default = isolated_config_paths
    default.write_text(
        '{"server_url": "http://192.168.1.50:8000", "server_token": "", "game": "dictee"}', encoding="utf-8"
    )
    local.write_text("not json", encoding="utf-8")
    config = server_client.load_server_config()
    assert config["server_url"] == "http://192.168.1.50:8000"
    assert config["game"] == "dictee"


def test_save_server_config_override_writes_local_file(isolated_config_paths):
    local, _default = isolated_config_paths
    server_client.save_server_config_override("http://10.0.0.9:8000", "tok")
    assert local.exists()
    config = server_client.load_server_config()
    assert config["server_url"] == "http://10.0.0.9:8000"
    assert config["server_token"] == "tok"


def test_high_score_service_raises_without_config(isolated_config_paths):
    with pytest.raises(ConnectionError):
        server_client.HighScoreService()


def test_high_score_service_uses_resolved_config(isolated_config_paths):
    server_client.save_server_config_override("http://10.0.0.9:8000", "tok")
    svc = server_client.HighScoreService()
    assert svc.base_url == "http://10.0.0.9:8000"
    assert svc.token == "tok"


def test_high_score_service_game_defaults_to_dictee(isolated_config_paths):
    server_client.save_server_config_override("http://10.0.0.9:8000")
    svc = server_client.HighScoreService()
    assert svc.game == "dictee"


def test_high_score_service_game_from_config_file(isolated_config_paths):
    local, default = isolated_config_paths
    default.write_text(
        '{"server_url": "http://192.168.1.50:8000", "server_token": "", "game": "maths"}', encoding="utf-8"
    )
    svc = server_client.HighScoreService()
    assert svc.game == "maths"


def test_high_score_service_explicit_game_wins(isolated_config_paths):
    local, default = isolated_config_paths
    default.write_text(
        '{"server_url": "http://192.168.1.50:8000", "server_token": "", "game": "maths"}', encoding="utf-8"
    )
    svc = server_client.HighScoreService(game="histoire-geo")
    assert svc.game == "histoire-geo"
