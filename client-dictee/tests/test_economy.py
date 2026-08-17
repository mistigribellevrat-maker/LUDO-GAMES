# tests/test_economy.py
"""Tests de l'économie du jeu (main.py) : LEVEL_MULTIPLIERS, SHOP_ITEMS,
_weapon_spec, _recompute_total_help_tokens, _consume_help_from_pool, _buy_item.

Invariants vérifiés :
- on ne peut pas acheter sans crédits suffisants ;
- le total d'aides (help_tokens) reste cohérent avec la somme du pool par arme ;
- consommer une aide décrémente exactement une fois le pool de l'arme concernée ;
- on ne peut jamais descendre sous zéro aide/crédit.
"""

from unittest.mock import MagicMock

import pytest


class TestLevelMultipliers:
    def test_every_difficulty_level_has_a_multiplier(self, DictationApp):
        for level in DictationApp.DIFFICULTY_LEVELS:
            assert level in DictationApp.LEVEL_MULTIPLIERS

    def test_multiplier_keys_match_difficulty_levels_exactly(self, DictationApp):
        assert set(DictationApp.LEVEL_MULTIPLIERS.keys()) == set(DictationApp.DIFFICULTY_LEVELS)

    @pytest.mark.parametrize(
        "level,expected",
        [
            ("CE1", 1.0),
            ("CE2", 1.25),
            ("CM1", 1.5),
            ("CM2", 1.75),
            ("Collège", 2.0),
        ],
    )
    def test_expected_multiplier_values(self, DictationApp, level, expected):
        assert DictationApp.LEVEL_MULTIPLIERS[level] == expected

    def test_multipliers_increase_with_difficulty(self, DictationApp):
        values = [DictationApp.LEVEL_MULTIPLIERS[lvl] for lvl in DictationApp.DIFFICULTY_LEVELS]
        assert values == sorted(values), "un niveau plus dur doit rapporter au moins autant qu'un niveau plus facile"


class TestShopItems:
    def test_all_keys_are_unique(self, DictationApp):
        keys = [item["key"] for item in DictationApp.SHOP_ITEMS]
        assert len(keys) == len(set(keys))

    def test_all_prices_and_helps_are_positive(self, DictationApp):
        for item in DictationApp.SHOP_ITEMS:
            assert item["price"] > 0
            assert item["helps"] > 0

    def test_more_expensive_weapons_grant_more_helps(self, DictationApp):
        prices = [item["price"] for item in DictationApp.SHOP_ITEMS]
        helps = [item["helps"] for item in DictationApp.SHOP_ITEMS]
        assert prices == sorted(prices)
        assert helps == sorted(helps)


class TestWeaponSpec:
    def test_returns_matching_item(self, DictationApp):
        app_self = MagicMock()
        app_self.SHOP_ITEMS = DictationApp.SHOP_ITEMS
        spec = DictationApp._weapon_spec(app_self, "sabre_quantique")
        assert spec is not None
        assert spec["name"] == "Sabre quantique"
        assert spec["helps"] == 10

    def test_returns_none_for_unknown_key(self, DictationApp):
        app_self = MagicMock()
        app_self.SHOP_ITEMS = DictationApp.SHOP_ITEMS
        assert DictationApp._weapon_spec(app_self, "arme_inexistante") is None


class TestRecomputeTotalHelpTokens:
    def test_sums_pool_values(self, fake_economy_app):
        app = fake_economy_app
        app.weapon_help_pool = {"couteau_laser": 3, "sabre_quantique": 7}
        app._recompute_total_help_tokens()
        assert app.help_tokens == 10

    def test_empty_pool_gives_zero_tokens(self, fake_economy_app):
        app = fake_economy_app
        app.weapon_help_pool = {}
        app._recompute_total_help_tokens()
        assert app.help_tokens == 0

    def test_non_dict_pool_defensively_gives_zero(self, fake_economy_app):
        app = fake_economy_app
        app.weapon_help_pool = None
        app._recompute_total_help_tokens()
        assert app.help_tokens == 0


class TestConsumeHelpFromPool:
    def test_no_tokens_available_returns_false_and_changes_nothing(self, fake_economy_app):
        app = fake_economy_app
        app.weapon_help_pool = {}
        app.owned_weapons = {}
        app.help_tokens = 0
        consumed = app._consume_help_from_pool()
        assert consumed is False
        assert app.weapon_help_pool == {}
        assert app.help_tokens == 0

    def test_consumes_from_the_highest_tier_weapon_first(self, fake_economy_app):
        app = fake_economy_app
        # sabre_quantique (helps=10) est le palier le plus élevé du catalogue ;
        # même si couteau_laser (helps=1) a aussi un pool non vide, c'est
        # sabre_quantique qui doit être décrémenté en premier.
        app.weapon_help_pool = {"couteau_laser": 5, "sabre_quantique": 3}
        app.owned_weapons = {"couteau_laser": 5, "sabre_quantique": 1}
        app.help_tokens = 8

        consumed = app._consume_help_from_pool()

        assert consumed is True
        assert app.weapon_help_pool["sabre_quantique"] == 2
        assert app.weapon_help_pool["couteau_laser"] == 5  # inchangé
        assert app.help_tokens == 7  # 5 + 2, resynchronisé

    def test_decrements_by_exactly_one_per_call(self, fake_economy_app):
        app = fake_economy_app
        app.weapon_help_pool = {"sabre_quantique": 3}
        app.owned_weapons = {"sabre_quantique": 1}
        app.help_tokens = 3

        app._consume_help_from_pool()
        assert app.weapon_help_pool["sabre_quantique"] == 2
        app._consume_help_from_pool()
        assert app.weapon_help_pool["sabre_quantique"] == 1
        app._consume_help_from_pool()
        assert app.weapon_help_pool["sabre_quantique"] == 0
        assert app.help_tokens == 0

    def test_owned_weapons_count_tracks_remaining_pool_capacity(self, fake_economy_app):
        app = fake_economy_app
        # sabre_quantique: 10 aides/unité. Avec 11 aides en pool -> 2 unités
        # affichées (ceil(11/10)=2) ; après une consommation -> 10 aides -> encore
        # 1 unité (ceil(10/10)=1).
        app.weapon_help_pool = {"sabre_quantique": 11}
        app.owned_weapons = {"sabre_quantique": 2}
        app.help_tokens = 11

        app._consume_help_from_pool()

        assert app.weapon_help_pool["sabre_quantique"] == 10
        assert app.owned_weapons["sabre_quantique"] == 1

    def test_cannot_go_negative_even_with_inconsistent_state(self, fake_economy_app):
        """État défensif : help_tokens>0 mais aucun pool par arme n'est réellement
        positif (incohérence). _consume_help_from_pool ne doit ni planter ni faire
        passer un pool sous zéro : il doit simplement échouer proprement."""
        app = fake_economy_app
        app.weapon_help_pool = {"couteau_laser": 0, "sabre_quantique": 0}
        app.owned_weapons = {}
        app.help_tokens = 5  # incohérent avec le pool, volontairement pour le test

        consumed = app._consume_help_from_pool()

        assert consumed is False
        assert app.weapon_help_pool == {"couteau_laser": 0, "sabre_quantique": 0}
        assert all(v >= 0 for v in app.weapon_help_pool.values())


class TestBuyItem:
    def _item(self, DictationApp, key):
        return next(it for it in DictationApp.SHOP_ITEMS if it["key"] == key)

    def test_cannot_buy_without_enough_credits(self, DictationApp, fake_buy_app, monkeypatch):
        import main as main_module

        mock_messagebox = MagicMock()
        monkeypatch.setattr(main_module, "messagebox", mock_messagebox)

        app = fake_buy_app
        item = self._item(DictationApp, "couteau_laser")  # price 120
        app.credits = 50

        app._buy_item(item, MagicMock())

        assert app.credits == 50  # inchangé
        assert app.weapon_help_pool == {}
        app._save_profile.assert_not_called()
        mock_messagebox.showwarning.assert_called_once()
        mock_messagebox.showinfo.assert_not_called()

    def test_buying_with_enough_credits_deducts_exact_price_and_credits_pool(
        self, DictationApp, fake_buy_app, monkeypatch
    ):
        import main as main_module

        mock_messagebox = MagicMock()
        monkeypatch.setattr(main_module, "messagebox", mock_messagebox)

        app = fake_buy_app
        item = self._item(DictationApp, "couteau_laser")  # price 120, helps 1
        app.credits = 200

        app._buy_item(item, MagicMock())

        assert app.credits == 80
        assert app.weapon_help_pool["couteau_laser"] == 1
        assert app.owned_weapons["couteau_laser"] == 1
        assert app.help_tokens == 1
        app._save_profile.assert_called_once()
        mock_messagebox.showinfo.assert_called_once()
        mock_messagebox.showwarning.assert_not_called()

    def test_credits_never_go_negative_from_a_purchase(self, DictationApp, fake_buy_app, monkeypatch):
        import main as main_module

        monkeypatch.setattr(main_module, "messagebox", MagicMock())

        app = fake_buy_app
        item = self._item(DictationApp, "sabre_quantique")  # price 900
        app.credits = 899

        app._buy_item(item, MagicMock())

        assert app.credits == 899  # achat refusé, aucun débit
        assert app.credits >= 0

    def test_repeated_purchases_accumulate_pool_and_units(self, DictationApp, fake_buy_app, monkeypatch):
        import main as main_module

        monkeypatch.setattr(main_module, "messagebox", MagicMock())

        app = fake_buy_app
        item = self._item(DictationApp, "pistolet_plasma")  # price 250, helps 2
        app.credits = 1000

        app._buy_item(item, MagicMock())
        app._buy_item(item, MagicMock())

        assert app.credits == 500
        assert app.weapon_help_pool["pistolet_plasma"] == 4
        assert app.owned_weapons["pistolet_plasma"] == 2
        assert app.help_tokens == 4
