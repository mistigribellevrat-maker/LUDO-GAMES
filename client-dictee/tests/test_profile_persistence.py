# tests/test_profile_persistence.py
"""Tests de persistance du profil utilisateur (main.py: _save_profile /
_initialize_profile), via la fabrique `make_profile_app` (voir conftest.py) qui
pointe TOUJOURS vers un fichier sous tmp_path : le vrai user_profile.json du
projet n'est jamais lu ni écrit par cette suite.

Couvre : round-trip fidèle, fichier absent, JSON invalide, fichier vide, clés
manquantes -- aucun de ces cas ne doit faire planter le chargement.
"""

import json

import pytest


class TestSaveProfile:
    def test_writes_readable_json_file(self, make_profile_app):
        app = make_profile_app(
            username="Zoé", avatar_path="assets/videos/1a.mp4",
            credits=555, help_tokens=8, owned_weapons={"couteau_laser": 1},
            weapon_help_pool={"couteau_laser": 1, "sabre_quantique": 7},
        )
        app._save_profile()

        with open(app.profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["username"] == "Zoé"
        assert data["avatar_path"] == "assets/videos/1a.mp4"
        assert data["credits"] == 555
        assert data["help_tokens"] == 8
        assert data["owned_weapons"] == {"couteau_laser": 1}
        assert data["weapon_help_pool"] == {"couteau_laser": 1, "sabre_quantique": 7}

    def test_does_not_leave_a_leftover_tmp_file(self, make_profile_app, tmp_path):
        app = make_profile_app(username="X")
        app._save_profile()
        assert not (tmp_path / "user_profile.json.tmp").exists()
        assert (tmp_path / "user_profile.json").exists()


class TestRoundTrip:
    def test_save_then_reload_is_faithful(self, make_profile_app):
        writer = make_profile_app(
            username="Commandant Zoé",
            credits=777,
            owned_weapons={"couteau_laser": 1, "sabre_quantique": 1},
            weapon_help_pool={"couteau_laser": 1, "sabre_quantique": 7},
        )
        # _initialize_profile n'adopte un avatar_path relu que s'il pointe vers un
        # fichier existant (voir test_missing_keys_fall_back_to_defaults_without_crashing
        # ci-dessous) : on matérialise donc l'une des options factices de la fabrique
        # plutôt que de dépendre d'un chemin d'asset réel du projet.
        chosen_avatar = writer.avatar_options[0]
        open(chosen_avatar, "wb").close()
        writer.avatar_path = chosen_avatar
        writer._save_profile()

        reader = make_profile_app(profile_path=writer.profile_path)
        reader._initialize_profile()

        assert reader.username == "Commandant Zoé"
        assert reader.avatar_path == chosen_avatar
        assert reader.credits == 777
        assert reader.weapon_help_pool == {"couteau_laser": 1, "sabre_quantique": 7}
        # help_tokens est toujours resynchronisé sur la somme du pool par arme,
        # jamais lu tel quel depuis le fichier (voir main.py _initialize_profile,
        # section "Synchroniser le total des aides avec le pool").
        assert reader.help_tokens == 8
        reader._show_profile_dialog.assert_not_called()

    def test_help_tokens_field_on_disk_is_ignored_in_favor_of_pool_sum(self, make_profile_app, tmp_path):
        """Documente/verrouille le comportement de resynchronisation : même si le
        fichier contient un help_tokens incohérent avec le pool, c'est la somme du
        pool qui fait foi après chargement."""
        profile_path = tmp_path / "user_profile.json"
        profile_path.write_text(
            json.dumps({
                "username": "Test",
                "avatar_path": None,
                "credits": 10,
                "help_tokens": 999,  # délibérément incohérent
                "owned_weapons": {"couteau_laser": 1},
                "weapon_help_pool": {"couteau_laser": 1},
            }),
            encoding="utf-8",
        )
        app = make_profile_app(profile_path=str(profile_path))

        app._initialize_profile()

        assert app.help_tokens == 1  # somme réelle du pool, pas 999


class TestMissingOrCorruptProfile:
    def test_missing_file_falls_back_to_dialog_without_crashing(self, make_profile_app, tmp_path):
        app = make_profile_app()
        assert not (tmp_path / "user_profile.json").exists()

        app._initialize_profile()  # ne doit pas lever d'exception

        app._show_profile_dialog.assert_called_once_with(initial=True)
        assert app.username == "Commandant"  # valeur par défaut appliquée après coup
        # Aucune des options d'avatar factices n'existe sur disque -> repli sur None.
        assert app.avatar_path is None

    def test_invalid_json_resets_to_safe_defaults_without_crashing(self, make_profile_app, tmp_path):
        profile_path = tmp_path / "user_profile.json"
        profile_path.write_text("{ceci n'est pas du json valide", encoding="utf-8")
        app = make_profile_app(profile_path=str(profile_path), username="ancien", credits=42)

        app._initialize_profile()  # ne doit pas lever d'exception

        assert app.username == "Commandant"
        assert app.credits == 0
        assert app.help_tokens == 0
        assert app.owned_weapons == {}
        assert app.weapon_help_pool == {}
        # Le fichier existe : on ne doit PAS retomber sur le dialogue de première
        # configuration, seulement réinitialiser silencieusement.
        app._show_profile_dialog.assert_not_called()

    def test_empty_file_resets_to_safe_defaults_without_crashing(self, make_profile_app, tmp_path):
        profile_path = tmp_path / "user_profile.json"
        profile_path.write_text("", encoding="utf-8")
        app = make_profile_app(profile_path=str(profile_path), username="ancien")

        app._initialize_profile()  # ne doit pas lever d'exception

        assert app.username == "Commandant"
        assert app.credits == 0
        app._show_profile_dialog.assert_not_called()

    def test_missing_keys_fall_back_to_defaults_without_crashing(self, make_profile_app, tmp_path):
        profile_path = tmp_path / "user_profile.json"
        profile_path.write_text("{}", encoding="utf-8")
        app = make_profile_app(profile_path=str(profile_path))

        app._initialize_profile()  # ne doit pas lever d'exception

        assert app.username == "Commandant"
        assert app.avatar_path is None
        assert app.credits == 0
        assert app.help_tokens == 0
        assert app.owned_weapons == {}
        assert app.weapon_help_pool == {}

    def test_non_dict_json_value_does_not_crash(self, make_profile_app, tmp_path):
        """Le fichier contient du JSON valide mais qui n'est pas un objet
        (ex: une simple liste) : .get() sur une liste lèverait AttributeError si
        ce n'était pas intercepté par le except Exception englobant."""
        profile_path = tmp_path / "user_profile.json"
        profile_path.write_text("[1, 2, 3]", encoding="utf-8")
        app = make_profile_app(profile_path=str(profile_path), username="ancien")

        app._initialize_profile()  # ne doit pas lever d'exception

        assert app.username == "Commandant"
        app._show_profile_dialog.assert_not_called()
