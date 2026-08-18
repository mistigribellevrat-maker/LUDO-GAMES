# tests/test_profile.py
"""Persistance du profil local (main.py: _load_profile / _save_profile) —
même stratégie de double de test que client-dictee/tests/test_profile_persistence.py."""

import json


class TestSaveThenReload:
    def test_round_trip_is_faithful(self, make_profile_app):
        writer = make_profile_app(username="Zoé", best_scores={"CE1": 8, "CM1": 5})
        writer._save_profile()

        reader = make_profile_app(profile_path=writer.profile_path)
        reader._load_profile()

        assert reader.username == "Zoé"
        assert reader.best_scores == {"CE1": 8, "CM1": 5}

    def test_global_progress_round_trips(self, make_profile_app):
        """Crédits/XP/badges/série sont une progression globale partagée avec les
        autres jeux (voir serveur/server.py) : le cache local doit les conserver
        fidèlement, comme le reste du profil."""
        writer = make_profile_app(
            username="Zoé", credits=250, xp=430,
            badges=["premiere_victoire"], streak=4, last_play_date="2026-08-16",
        )
        writer._save_profile()

        reader = make_profile_app(profile_path=writer.profile_path)
        reader._load_profile()

        assert reader.credits == 250
        assert reader.xp == 430
        assert reader.badges == ["premiere_victoire"]
        assert reader.streak == 4
        assert reader.last_play_date == "2026-08-16"

    def test_avatar_path_kept_only_if_file_exists(self, make_profile_app, tmp_path):
        real_avatar = tmp_path / "avatar.jpg"
        real_avatar.write_bytes(b"")
        writer = make_profile_app(username="X", avatar_path=str(real_avatar))
        writer._save_profile()

        reader = make_profile_app(profile_path=writer.profile_path)
        reader._load_profile()
        assert reader.avatar_path == str(real_avatar)

    def test_missing_avatar_file_falls_back_to_none(self, make_profile_app, tmp_path):
        writer = make_profile_app(username="X", avatar_path=str(tmp_path / "does_not_exist.jpg"))
        writer._save_profile()

        reader = make_profile_app(profile_path=writer.profile_path)
        reader._load_profile()
        assert reader.avatar_path is None

    def test_does_not_leave_a_leftover_tmp_file(self, make_profile_app, tmp_path):
        app = make_profile_app(username="X")
        app._save_profile()
        assert not (tmp_path / "user_profile.json.tmp").exists()
        assert (tmp_path / "user_profile.json").exists()


class TestMissingOrCorruptProfile:
    def test_missing_file_leaves_defaults_untouched(self, make_profile_app, tmp_path):
        app = make_profile_app()
        assert not (tmp_path / "user_profile.json").exists()
        app._load_profile()  # ne doit pas lever d'exception
        assert app.username is None
        assert app.best_scores == {}

    def test_invalid_json_leaves_defaults_untouched(self, make_profile_app, tmp_path):
        profile_path = tmp_path / "user_profile.json"
        profile_path.write_text("{pas du json valide", encoding="utf-8")
        app = make_profile_app(profile_path=str(profile_path))
        app._load_profile()  # ne doit pas lever d'exception
        assert app.username is None

    def test_non_dict_json_does_not_crash(self, make_profile_app, tmp_path):
        profile_path = tmp_path / "user_profile.json"
        profile_path.write_text("[1, 2, 3]", encoding="utf-8")
        app = make_profile_app(profile_path=str(profile_path))
        app._load_profile()  # ne doit pas lever d'exception
        assert app.username is None

    def test_missing_keys_fall_back_to_defaults(self, make_profile_app, tmp_path):
        profile_path = tmp_path / "user_profile.json"
        profile_path.write_text("{}", encoding="utf-8")
        app = make_profile_app(profile_path=str(profile_path))
        app._load_profile()
        assert app.username is None
        assert app.best_scores == {}
