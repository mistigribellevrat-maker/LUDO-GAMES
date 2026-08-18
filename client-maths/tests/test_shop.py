# tests/test_shop.py
"""Économie de la boutique de client-maths (main.py) : SHOP_ITEMS, _buy_item,
_consume_charge, et les bonus de mission (_use_indice/_use_bouclier/_use_horloge).

Même stratégie que client-dictee/tests/test_economy.py : les VRAIES méthodes
non liées sont reliées à un double minimal (SimpleNamespace), jamais de fenêtre
Tk, jamais le vrai user_profile.json. Invariants vérifiés :
- on ne peut pas acheter sans crédits suffisants (aucun débit, aucune sauvegarde) ;
- un achat débite le prix exact et crédite les charges ; les achats s'accumulent ;
- consommer une charge décrémente exactement une fois ; jamais sous zéro ;
- les bonus de mission appliquent leur effet et consomment une charge.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from problems import MathMission


@pytest.fixture(scope="session")
def MathsApp():
    """La classe MathsApp elle-même (jamais instanciée)."""
    import main as main_module
    return main_module.MathsApp


@pytest.fixture
def fake_shop_app(MathsApp):
    """Double de test pour la logique d'achat/consommation, sans Tk ni IO."""
    app = SimpleNamespace()
    app.SHOP_ITEMS = MathsApp.SHOP_ITEMS
    app.shop_charges = {}
    app.credits = 0
    app._save_profile = MagicMock()
    app._update_credits_chip = MagicMock()
    app._refresh_boost_buttons = MagicMock()
    app._buy_item = MathsApp._buy_item.__get__(app)
    app._consume_charge = MathsApp._consume_charge.__get__(app)
    return app


def _item(MathsApp, key):
    return next(it for it in MathsApp.SHOP_ITEMS if it["key"] == key)


class TestShopItems:
    def test_all_keys_are_unique(self, MathsApp):
        keys = [item["key"] for item in MathsApp.SHOP_ITEMS]
        assert len(keys) == len(set(keys))

    def test_all_prices_and_helps_are_positive(self, MathsApp):
        for item in MathsApp.SHOP_ITEMS:
            assert item["price"] > 0
            assert item["helps"] > 0

    def test_required_keys_present(self, MathsApp):
        keys = [item["key"] for item in MathsApp.SHOP_ITEMS]
        for required in ("indice", "bouclier", "horloge"):
            assert required in keys


class TestBuyItem:
    def test_cannot_buy_without_enough_credits(self, MathsApp, fake_shop_app, monkeypatch):
        import main as main_module

        mock_messagebox = MagicMock()
        monkeypatch.setattr(main_module, "messagebox", mock_messagebox)

        app = fake_shop_app
        item = _item(MathsApp, "indice")  # price 150
        app.credits = 50

        app._buy_item(item)

        assert app.credits == 50  # inchangé
        assert app.shop_charges == {}
        app._save_profile.assert_not_called()
        mock_messagebox.showwarning.assert_called_once()
        mock_messagebox.showinfo.assert_not_called()

    def test_buying_with_enough_credits_deducts_exact_price_and_adds_charges(
        self, MathsApp, fake_shop_app, monkeypatch
    ):
        import main as main_module

        monkeypatch.setattr(main_module, "messagebox", MagicMock())

        app = fake_shop_app
        item = _item(MathsApp, "bouclier")  # price 200, helps 1
        app.credits = 500

        app._buy_item(item)

        assert app.credits == 300
        assert app.shop_charges["bouclier"] == 1
        app._save_profile.assert_called_once()

    def test_credits_never_go_negative_from_a_purchase(self, MathsApp, fake_shop_app, monkeypatch):
        import main as main_module

        monkeypatch.setattr(main_module, "messagebox", MagicMock())

        app = fake_shop_app
        item = _item(MathsApp, "bouclier")  # price 200
        app.credits = 199

        app._buy_item(item)

        assert app.credits == 199  # achat refusé, aucun débit

    def test_repeated_purchases_accumulate_charges(self, MathsApp, fake_shop_app, monkeypatch):
        import main as main_module

        monkeypatch.setattr(main_module, "messagebox", MagicMock())

        app = fake_shop_app
        item = _item(MathsApp, "indice")  # price 150, helps 1
        app.credits = 1000

        app._buy_item(item)
        app._buy_item(item)
        app._buy_item(item)

        assert app.credits == 550
        assert app.shop_charges["indice"] == 3


class TestConsumeCharge:
    def test_no_charge_does_nothing(self, fake_shop_app):
        app = fake_shop_app
        app.shop_charges = {"indice": 0}

        app._consume_charge("indice")

        assert app.shop_charges == {"indice": 0}
        app._save_profile.assert_not_called()

    def test_consumes_exactly_one_and_saves(self, fake_shop_app):
        app = fake_shop_app
        app.shop_charges = {"bouclier": 2}

        app._consume_charge("bouclier")
        app._consume_charge("bouclier")

        assert app.shop_charges["bouclier"] == 0
        assert app._save_profile.call_count == 2


class TestMissionBoosters:
    @pytest.fixture
    def app(self, MathsApp, fake_shop_app):
        app = fake_shop_app
        app.mission = MathMission(level="CE1")
        app._refresh_mission_labels = MagicMock()
        app._update_timer_display = MagicMock()
        app.answer_var = MagicMock()
        app._time_left = 10
        app._use_indice = MathsApp._use_indice.__get__(app)
        app._use_bouclier = MathsApp._use_bouclier.__get__(app)
        app._use_horloge = MathsApp._use_horloge.__get__(app)
        return app

    def test_indice_reveals_answer_and_consumes_charge(self, app):
        app.shop_charges = {"indice": 1}
        expected = str(app.mission.current.answer)

        app._use_indice()

        app.answer_var.set.assert_called_once_with(expected)
        assert app.shop_charges == {"indice": 0}

    def test_indice_does_nothing_without_charge(self, app):
        app.shop_charges = {}
        app._use_indice()
        app.answer_var.set.assert_not_called()

    def test_indice_does_nothing_when_mission_finished(self, app):
        app.shop_charges = {"indice": 1}
        app.mission.finished = True
        app._use_indice()
        app.answer_var.set.assert_not_called()
        assert app.shop_charges == {"indice": 1}  # charge non consommée

    def test_bouclier_adds_one_mistake_allowance(self, app):
        app.shop_charges = {"bouclier": 1}
        before = app.mission.max_mistakes

        app._use_bouclier()

        assert app.mission.max_mistakes == before + 1
        assert app.shop_charges == {"bouclier": 0}
        app._refresh_mission_labels.assert_called_once()

    def test_horloge_adds_three_seconds_to_current_question(self, app):
        app.shop_charges = {"horloge": 1}
        app._time_left = 4

        app._use_horloge()

        assert app._time_left == 7
        assert app.shop_charges == {"horloge": 0}
        app._update_timer_display.assert_called_once()


class TestShopChargesPersistence:
    def test_round_trip_is_faithful(self, make_profile_app):
        writer = make_profile_app(shop_charges={"indice": 2, "bouclier": 1})
        writer._save_profile()

        reader = make_profile_app(profile_path=writer.profile_path)
        reader._load_profile()

        assert reader.shop_charges == {"indice": 2, "bouclier": 1}

    def test_missing_key_falls_back_to_empty_dict(self, make_profile_app):
        app = make_profile_app()
        app._load_profile()
        assert app.shop_charges == {}
