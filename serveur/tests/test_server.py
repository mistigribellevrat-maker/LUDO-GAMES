# tests/test_server.py
"""Tests du serveur de scores (server.py) — stdlib HTTP + SQLite, sans réseau externe.

On démarre un vrai `ThreadingHTTPServer` sur un port libre (127.0.0.1:0) et on le
frappe avec `requests` (voir requirements-dev.txt). La base SQLite vit dans un
fichier temporaire : aucune donnée réelle n'est touchée.
"""

import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server as server_module  # noqa: E402


class _Server:
    def __init__(self, db_path, token=""):
        self.store = server_module.ScoreStore(str(db_path))
        handler = server_module.make_handler(self.store, token)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(tmp_path):
    fx = _Server(tmp_path / "scores.db")
    yield fx
    fx.close()


def _identify(base, name, game="dictee", avatar_path=None):
    payload = {"name": name, "game": game}
    if avatar_path is not None:
        payload["avatar_path"] = avatar_path
    return requests.post(f"{base}/api/identify", json=payload, timeout=5).json()


def _add_score(base, name, difficulty, score, duration=30.0, game="dictee"):
    return requests.post(
        f"{base}/api/scores",
        json={"name": name, "game": game, "difficulty": difficulty, "score": score, "duration": duration},
        timeout=5,
    )


def _top(base, game, difficulty):
    return requests.get(f"{base}/api/scores/{game}/{difficulty}", timeout=5).json()["scores"]


def _save_profile(base, name, game, profile=None, **global_fields):
    payload = {"name": name, "game": game, "profile": profile if profile is not None else {}}
    payload.update({k: v for k, v in global_fields.items() if v is not None})
    return requests.post(f"{base}/api/profile", json=payload, timeout=5)


def test_health(server):
    r = requests.get(f"{server.base}/api/health", timeout=5)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_identify_creates_and_reconnects(server):
    first = _identify(server.base, "Arthur")
    assert first["player_id"] > 0
    assert first["name"] == "Arthur"

    again = _identify(server.base, "Arthur")
    assert again["player_id"] == first["player_id"]


def test_identify_is_case_insensitive(server):
    a = _identify(server.base, "Zoé")
    b = _identify(server.base, "zoé")
    assert a["player_id"] == b["player_id"]


def test_identify_rejects_empty_name(server):
    r = requests.post(f"{server.base}/api/identify", json={"name": "   ", "game": "dictee"}, timeout=5)
    assert r.status_code == 400


def test_identify_rejects_empty_game(server):
    r = requests.post(f"{server.base}/api/identify", json={"name": "Arthur", "game": ""}, timeout=5)
    assert r.status_code == 400


def test_profile_roundtrip(server):
    profile = {
        "avatar_path": "assets/videos/1a.mp4",
        "credits": 420,
        "help_tokens": 3,
        "owned_weapons": {"couteau_laser": 1},
        "weapon_help_pool": {"couteau_laser": 1},
    }
    saved = requests.post(
        f"{server.base}/api/profile",
        json={"name": "Arthur", "game": "dictee", "profile": profile},
        timeout=5,
    )
    assert saved.status_code == 200
    assert saved.json()["player_id"] > 0

    info = _identify(server.base, "Arthur")
    assert info["profile"] == profile


def test_identify_new_player_has_no_profile(server):
    info = _identify(server.base, "Nouveau")
    assert info["profile"] is None


def test_new_player_has_no_avatar(server):
    info = _identify(server.base, "Nouveau")
    assert info["avatar_path"] is None


def test_avatar_is_global_across_games(server):
    """Le pseudo ET l'avatar sont une identité partagée entre tous les jeux,
    contrairement au profil (crédits/armes/XP) qui reste propre à chaque jeu."""
    _identify(server.base, "Arthur", game="dictee", avatar_path="assets/videos/1a.mp4")

    maths_info = _identify(server.base, "Arthur", game="maths")
    assert maths_info["avatar_path"] == "assets/videos/1a.mp4"
    assert maths_info["profile"] is None  # le profil, lui, ne fuite pas entre jeux


def test_avatar_can_be_updated_from_any_game(server):
    _identify(server.base, "Arthur", game="dictee", avatar_path="assets/videos/1a.mp4")
    _identify(server.base, "Arthur", game="maths", avatar_path="assets/videos/1c.mp4")

    dictee_info = _identify(server.base, "Arthur", game="dictee")
    assert dictee_info["avatar_path"] == "assets/videos/1c.mp4"


def test_identify_without_avatar_keeps_previous_value(server):
    _identify(server.base, "Arthur", game="dictee", avatar_path="assets/videos/1a.mp4")
    again = _identify(server.base, "Arthur", game="dictee")
    assert again["avatar_path"] == "assets/videos/1a.mp4"


def test_new_player_has_zeroed_global_progress(server):
    info = _identify(server.base, "Nouveau")
    assert info["credits"] == 0
    assert info["xp"] == 0
    assert info["badges"] == []
    assert info["streak"] == 0
    assert info["last_play_date"] is None


def test_global_progress_is_shared_across_games(server):
    """C'est la garantie centrale de la progression globale : crédits/XP/badges/
    série gagnés dans un jeu doivent apparaître immédiatement dans l'autre."""
    r = _save_profile(server.base, "Arthur", "dictee", profile={"owned_weapons": {}},
                       credits=250, xp=430, badges=["premiere_victoire", "sans_faute"],
                       streak=3, last_play_date="2026-08-16")
    assert r.status_code == 200

    maths_info = _identify(server.base, "Arthur", game="maths")
    assert maths_info["credits"] == 250
    assert maths_info["xp"] == 430
    assert maths_info["badges"] == ["premiere_victoire", "sans_faute"]
    assert maths_info["streak"] == 3
    assert maths_info["last_play_date"] == "2026-08-16"


def test_per_game_profile_stays_separate_while_global_progress_is_shared(server):
    _save_profile(server.base, "Arthur", "dictee", profile={"owned_weapons": {"sabre": 1}}, credits=100)
    _save_profile(server.base, "Arthur", "maths", profile={"best_scores": {"CM1": 8}})

    dictee_info = _identify(server.base, "Arthur", game="dictee")
    maths_info = _identify(server.base, "Arthur", game="maths")

    assert dictee_info["profile"] == {"owned_weapons": {"sabre": 1}}
    assert maths_info["profile"] == {"best_scores": {"CM1": 8}}
    # Le crédit posé via dictée est bien visible depuis maths (identité globale).
    assert dictee_info["credits"] == 100
    assert maths_info["credits"] == 100


def test_saving_profile_without_global_fields_does_not_reset_wallet(server):
    """Un jeu qui ne pousse que son profil (ex: maths sans économie propre) ne doit
    jamais remettre les crédits/XP accumulés ailleurs à zéro."""
    _save_profile(server.base, "Arthur", "dictee", profile={}, credits=500, xp=200)
    r = _save_profile(server.base, "Arthur", "maths", profile={"best_scores": {"CE1": 10}})
    assert r.status_code == 200

    info = _identify(server.base, "Arthur", game="dictee")
    assert info["credits"] == 500
    assert info["xp"] == 200


def test_save_profile_rejects_bad_global_values(server):
    r = _save_profile(server.base, "Arthur", "dictee", profile={}, credits=-5)
    assert r.status_code == 400

    r = _save_profile(server.base, "Arthur", "dictee", profile={}, badges="pas-une-liste")
    assert r.status_code == 400


def test_save_profile_rejects_non_dict(server):
    r = requests.post(
        f"{server.base}/api/profile",
        json={"name": "X", "game": "dictee", "profile": [1, 2, 3]},
        timeout=5,
    )
    assert r.status_code == 400


def test_add_score_returns_rank_and_leaderboard(server):
    r1 = _add_score(server.base, "Arthur", "CM1", 18, duration=60.0)
    assert r1.status_code == 200
    body = r1.json()
    assert body["rank"] == 1
    assert body["total"] == 1
    assert body["top"][0]["name"] == "Arthur"

    _add_score(server.base, "Zoé", "CM1", 20, duration=45.0)
    _add_score(server.base, "Léo", "CM1", 18, duration=30.0)

    top = _top(server.base, "dictee", "CM1")
    names = [e["name"] for e in top]
    # Meilleur score d'abord ; à score égal, durée la plus courte d'abord.
    assert names[0] == "Zoé"
    assert names[1] == "Léo"
    assert names[2] == "Arthur"


def test_top_keeps_only_the_best_attempt_of_each_player(server):
    """Le classement d'un jeu/niveau ne doit jamais montrer deux fois le même
    joueur : sans ça, celui qui rejoue le plus occupe tout le top et éjecte les
    autres — le défaut le plus visible quand une fratrie se compare."""
    for score, duration in ((12, 90.0), (20, 70.0), (17, 50.0)):
        _add_score(server.base, "Arthur", "CM1", score, duration=duration)
    _add_score(server.base, "Zoé", "CM1", 18, duration=40.0)

    top = _top(server.base, "dictee", "CM1")
    names = [e["name"] for e in top]
    assert names == ["Arthur", "Zoé"]
    assert top[0]["score"] == 20  # sa meilleure tentative, pas la dernière


def test_top_ties_are_broken_by_the_players_fastest_best_run(server):
    _add_score(server.base, "Arthur", "CM1", 18, duration=90.0)
    _add_score(server.base, "Arthur", "CM1", 18, duration=30.0)
    _add_score(server.base, "Zoé", "CM1", 18, duration=45.0)

    top = _top(server.base, "dictee", "CM1")
    assert [e["name"] for e in top] == ["Arthur", "Zoé"]
    assert top[0]["duration"] == 30.0


def test_rank_and_total_count_players_not_attempts(server):
    """Le rang annoncé au joueur doit correspondre à la ligne qu'il voit :
    rejouer moins bien ne le déclasse pas et n'ajoute pas de ligne."""
    _add_score(server.base, "Zoé", "CM1", 20, duration=40.0)
    _add_score(server.base, "Arthur", "CM1", 18, duration=40.0)

    body = _add_score(server.base, "Arthur", "CM1", 5, duration=200.0).json()
    assert body["rank"] == 2   # toujours 2e grâce à son 18, pas 3e
    assert body["total"] == 2  # 2 joueurs classés, pas 3 tentatives


def test_leaderboard_is_global_and_sorted_by_xp(server):
    """Vue « qui est le meilleur commandant, toutes missions confondues » :
    triée par XP (jamais dépensable), pas par crédits (qui se dépensent en
    boutique et ne disent donc pas le niveau réel)."""
    _save_profile(server.base, "Arthur", "dictee", credits=10, xp=900,
                  badges=["premiere_victoire", "sans_faute"])
    _save_profile(server.base, "Zoé", "maths", credits=5000, xp=1500)
    _add_score(server.base, "Arthur", "CM1", 18, game="dictee")
    _add_score(server.base, "Arthur", "CM1", 20, game="dictee")
    _add_score(server.base, "Arthur", "CE1", 7, game="maths")

    board = requests.get(f"{server.base}/api/leaderboard", timeout=5).json()["leaderboard"]
    names = [e["name"] for e in board]
    assert names[0] == "Zoé"      # 1500 XP devant 900, malgré moins de crédits
    assert names[1] == "Arthur"
    assert [e["rank"] for e in board] == [1, 2]

    arthur = board[1]
    assert arthur["badges"] == ["premiere_victoire", "sans_faute"]
    assert arthur["plays"] == 3
    recap = {g["game"]: g for g in arthur["games"]}
    assert recap["dictee"]["plays"] == 2
    assert recap["dictee"]["best_score"] == 20
    assert recap["maths"]["plays"] == 1


def test_leaderboard_lists_players_without_any_score(server):
    """Un joueur inscrit mais qui n'a encore rien joué doit apparaître (à 0),
    pas disparaître du classement."""
    _identify(server.base, "Cloclo")
    board = requests.get(f"{server.base}/api/leaderboard", timeout=5).json()["leaderboard"]
    assert [e["name"] for e in board] == ["Cloclo"]
    assert board[0]["xp"] == 0
    assert board[0]["games"] == []
    assert board[0]["plays"] == 0


def test_get_scores_bad_route(server):
    r = requests.get(f"{server.base}/api/scores/dictee", timeout=5)
    assert r.status_code == 400


def test_add_score_rejects_bad_values(server):
    r = _add_score(server.base, "Arthur", "CM1", -1)
    assert r.status_code == 400


def test_add_score_rejects_empty_game(server):
    r = requests.post(
        f"{server.base}/api/scores",
        json={"name": "Arthur", "game": "", "difficulty": "CM1", "score": 10, "duration": 10},
        timeout=5,
    )
    assert r.status_code == 400


def test_scores_isolated_per_game(server):
    """Garantie centrale du serveur multi-jeux : deux univers ne partagent jamais
    leur classement, même avec le même joueur et la même étiquette de difficulté."""
    _add_score(server.base, "Arthur", "CM1", 20, duration=10.0, game="dictee")
    _add_score(server.base, "Arthur", "CM1", 5, duration=99.0, game="maths")

    dictee_top = _top(server.base, "dictee", "CM1")
    maths_top = _top(server.base, "maths", "CM1")

    assert len(dictee_top) == 1
    assert dictee_top[0]["score"] == 20
    assert len(maths_top) == 1
    assert maths_top[0]["score"] == 5


def test_profile_isolated_per_game(server):
    """Le profil (crédits, avatar, ...) d'un jeu ne doit jamais fuiter vers un autre."""
    requests.post(
        f"{server.base}/api/profile",
        json={"name": "Arthur", "game": "dictee", "profile": {"credits": 100}},
        timeout=5,
    )
    requests.post(
        f"{server.base}/api/profile",
        json={"name": "Arthur", "game": "maths", "profile": {"credits": 7}},
        timeout=5,
    )

    dictee_info = _identify(server.base, "Arthur", game="dictee")
    maths_info = _identify(server.base, "Arthur", game="maths")

    assert dictee_info["player_id"] == maths_info["player_id"]  # même identité globale
    assert dictee_info["profile"] == {"credits": 100}
    assert maths_info["profile"] == {"credits": 7}


def test_token_required(tmp_path):
    fx = _Server(tmp_path / "scores.db", token="secret")
    try:
        r = requests.post(f"{fx.base}/api/scores", json={"name": "X", "game": "dictee"}, timeout=5)
        assert r.status_code == 401

        ok = requests.post(
            f"{fx.base}/api/identify",
            json={"name": "X", "game": "dictee"},
            headers={"X-Auth-Token": "secret"},
            timeout=5,
        )
        assert ok.status_code == 200
    finally:
        fx.close()
