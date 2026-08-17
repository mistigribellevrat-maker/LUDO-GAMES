# tests/test_global_progress.py
"""Progression globale (crédits/XP/badges/série) partagée entre tous les jeux :
vérifie que main.py sépare correctement ce qui part dans le profil DE CE JEU
(armes, aides, meilleurs scores) de ce qui part dans la progression GLOBALE
(crédits, XP, badges, série), et que la réponse serveur applique bien le
global en priorité. Aucun réseau réel : `high_score_service` est un double
qui enregistre juste les appels reçus.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def app_with_fake_service(DictationApp):
    service = MagicMock()
    app = SimpleNamespace()
    app.username = "Arthur"
    app.player_id = 1
    app.avatar_path = None
    app.credits = 250
    app.help_tokens = 3
    app.owned_weapons = {"couteau_laser": 1}
    app.weapon_help_pool = {"couteau_laser": 1}
    app.best_scores = {"CM1": 18}
    app.badges = ["premiere_victoire"]
    app.levels_played = ["CM1"]
    app.last_play_date = "2026-08-16"
    app.streak = 4
    app.xp = 430
    app.high_scores_enabled = True
    app.high_score_service = service
    app._profile_payload = DictationApp._profile_payload.__get__(app)
    app._global_progress_payload = DictationApp._global_progress_payload.__get__(app)
    app._apply_server_profile = DictationApp._apply_server_profile.__get__(app)
    app._sync_profile_to_server = DictationApp._sync_profile_to_server.__get__(app)
    return app, service


class TestProfilePayloadSplit:
    def test_per_game_payload_excludes_global_fields(self, app_with_fake_service):
        app, _service = app_with_fake_service
        payload = app._profile_payload()
        for key in ("credits", "xp", "badges", "streak", "last_play_date", "avatar_path"):
            assert key not in payload

    def test_per_game_payload_keeps_dictee_specific_fields(self, app_with_fake_service):
        app, _service = app_with_fake_service
        payload = app._profile_payload()
        assert payload == {
            "help_tokens": 3,
            "owned_weapons": {"couteau_laser": 1},
            "weapon_help_pool": {"couteau_laser": 1},
            "best_scores": {"CM1": 18},
            "levels_played": ["CM1"],
        }

    def test_global_progress_payload_contains_only_shared_fields(self, app_with_fake_service):
        app, _service = app_with_fake_service
        assert app._global_progress_payload() == {
            "credits": 250,
            "xp": 430,
            "badges": ["premiere_victoire"],
            "streak": 4,
            "last_play_date": "2026-08-16",
        }


class TestSyncPushesBothPayloads:
    def test_sync_calls_save_profile_with_split_payloads(self, app_with_fake_service, monkeypatch):
        app, service = app_with_fake_service

        # _sync_profile_to_server lance un thread daemon ; on le rend synchrone
        # pour l'assertion (mêmes garanties, juste immédiat dans le test).
        import threading
        real_thread = threading.Thread

        class ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        monkeypatch.setattr(threading, "Thread", ImmediateThread)
        try:
            app._sync_profile_to_server()
        finally:
            monkeypatch.setattr(threading, "Thread", real_thread)

        service.save_profile.assert_called_once()
        args, kwargs = service.save_profile.call_args
        assert args[0] == "Arthur"
        assert args[1] == app._profile_payload()
        assert kwargs == app._global_progress_payload()


class TestApplyServerProfileNoLongerTouchesGlobalFields:
    def test_apply_server_profile_leaves_credits_xp_badges_untouched(self, app_with_fake_service):
        app, _service = app_with_fake_service
        app._apply_server_profile({
            "owned_weapons": {"sabre_quantique": 2},
            "weapon_help_pool": {"sabre_quantique": 20},
            "best_scores": {"CE1": 20},
            "levels_played": ["CE1", "CM1"],
            # Un ancien profil pourrait encore contenir ces clés (avant migration) :
            # elles ne doivent plus être lues par _apply_server_profile.
            "credits": 999999,
            "xp": 999999,
            "badges": ["ne_devrait_pas_apparaitre"],
        })
        assert app.credits == 250  # inchangé : ce n'est plus le rôle de cette méthode
        assert app.xp == 430
        assert app.badges == ["premiere_victoire"]
        assert app.owned_weapons == {"sabre_quantique": 2}
        assert app.best_scores == {"CE1": 20}
