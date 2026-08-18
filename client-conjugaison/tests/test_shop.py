# tests/test_shop.py
"""Économie de la boutique de client-conjugaison (main.py) : SHOP_ITEMS,
_buy_item, _consume_charge, et les bonus de mission
(_use_traqueur/_use_bouclier/_use_ralenti).

Même stratégie que client-maths/tests/test_shop.py : les VRAIES méthodes non
liées sont reliées à un double minimal (SimpleNamespace), jamais de fenêtre Tk,
jamais le vrai user_profile.json. Les effets visuels (highlight_correct,
slow_ships) sont vérifiés sur les méthodes de TurretScene via leur contrepartie
`scene` mockée — la logique de seuils (charges, mission terminée) est du code de
production réel.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from problems import ConjugationMission


@pytest.fixture(scope="session")
def ConjugaisonApp():
    """La classe ConjugaisonApp elle-même (jamais instanciée)."""
    import main as main_module
    return main_module.ConjugaisonApp


@pytest.fixture
def fake_shop_app(ConjugaisonApp):
    """Double de test pour la logique d'achat/consommation, sans Tk ni IO."""
    app = SimpleNamespace()
    app.SHOP_ITEMS = ConjugaisonApp.SHOP_ITEMS
    app.shop_charges = {}
    app.credits = 0
    app._save_profile = MagicMock()
    app._update_credits_chip = MagicMock()
    app._refresh_boost_buttons = MagicMock()
    app._buy_item = ConjugaisonApp._buy_item.__get__(app)
    app._consume_charge = ConjugaisonApp._consume_charge.__get__(app)
    return app


def _item(ConjugaisonApp, key):
    return next(it for it in ConjugaisonApp.SHOP_ITEMS if it["key"] == key)


class TestShopItems:
    def test_all_keys_are_unique(self, ConjugaisonApp):
        keys = [item["key"] for item in ConjugaisonApp.SHOP_ITEMS]
        assert len(keys) == len(set(keys))

    def test_all_prices_and_helps_are_positive(self, ConjugaisonApp):
        for item in ConjugaisonApp.SHOP_ITEMS:
            assert item["price"] > 0
            assert item["helps"] > 0

    def test_required_keys_present(self, ConjugaisonApp):
        keys = [item["key"] for item in ConjugaisonApp.SHOP_ITEMS]
        for required in ("traqueur", "bouclier", "ralenti"):
            assert required in keys


class TestBuyItem:
    def test_cannot_buy_without_enough_credits(self, ConjugaisonApp, fake_shop_app, monkeypatch):
        import main as main_module

        mock_messagebox = MagicMock()
        monkeypatch.setattr(main_module, "messagebox", mock_messagebox)

        app = fake_shop_app
        item = _item(ConjugaisonApp, "traqueur")  # price 150
        app.credits = 50

        app._buy_item(item)

        assert app.credits == 50  # inchangé
        assert app.shop_charges == {}
        app._save_profile.assert_not_called()
        mock_messagebox.showwarning.assert_called_once()
        mock_messagebox.showinfo.assert_not_called()

    def test_buying_with_enough_credits_deducts_exact_price_and_adds_charges(
        self, ConjugaisonApp, fake_shop_app, monkeypatch
    ):
        import main as main_module

        monkeypatch.setattr(main_module, "messagebox", MagicMock())

        app = fake_shop_app
        item = _item(ConjugaisonApp, "bouclier")  # price 200, helps 1
        app.credits = 500

        app._buy_item(item)

        assert app.credits == 300
        assert app.shop_charges["bouclier"] == 1
        app._save_profile.assert_called_once()

    def test_credits_never_go_negative_from_a_purchase(self, ConjugaisonApp, fake_shop_app, monkeypatch):
        import main as main_module

        monkeypatch.setattr(main_module, "messagebox", MagicMock())

        app = fake_shop_app
        item = _item(ConjugaisonApp, "bouclier")  # price 200
        app.credits = 199

        app._buy_item(item)

        assert app.credits == 199  # achat refusé, aucun débit

    def test_repeated_purchases_accumulate_charges(self, ConjugaisonApp, fake_shop_app, monkeypatch):
        import main as main_module

        monkeypatch.setattr(main_module, "messagebox", MagicMock())

        app = fake_shop_app
        item = _item(ConjugaisonApp, "traqueur")  # price 150, helps 1
        app.credits = 1000

        app._buy_item(item)
        app._buy_item(item)

        assert app.credits == 700
        assert app.shop_charges["traqueur"] == 2


class TestConsumeCharge:
    def test_no_charge_does_nothing(self, fake_shop_app):
        app = fake_shop_app
        app.shop_charges = {"traqueur": 0}

        app._consume_charge("traqueur")

        assert app.shop_charges == {"traqueur": 0}
        app._save_profile.assert_not_called()

    def test_consumes_exactly_one_and_saves(self, fake_shop_app):
        app = fake_shop_app
        app.shop_charges = {"ralenti": 3}

        app._consume_charge("ralenti")
        app._consume_charge("ralenti")

        assert app.shop_charges["ralenti"] == 1
        assert app._save_profile.call_count == 2


class TestMissionBoosters:
    @pytest.fixture
    def app(self, ConjugaisonApp, fake_shop_app):
        app = fake_shop_app
        app.mission = ConjugationMission(level="CE1")
        app.turret_scene = MagicMock()
        app._refresh_mission_labels = MagicMock()
        app._use_traqueur = ConjugaisonApp._use_traqueur.__get__(app)
        app._use_bouclier = ConjugaisonApp._use_bouclier.__get__(app)
        app._use_ralenti = ConjugaisonApp._use_ralenti.__get__(app)
        return app

    def test_traqueur_highlights_correct_ship_and_consumes_charge(self, app):
        app.shop_charges = {"traqueur": 1}

        app._use_traqueur()

        app.turret_scene.highlight_correct.assert_called_once_with(3.0)
        assert app.shop_charges == {"traqueur": 0}

    def test_traqueur_does_nothing_without_charge(self, app):
        app.shop_charges = {}
        app._use_traqueur()
        app.turret_scene.highlight_correct.assert_not_called()

    def test_traqueur_does_nothing_when_mission_finished(self, app):
        app.shop_charges = {"traqueur": 1}
        app.mission.finished = True
        app._use_traqueur()
        app.turret_scene.highlight_correct.assert_not_called()
        assert app.shop_charges == {"traqueur": 1}  # charge non consommée

    def test_bouclier_adds_one_mistake_allowance(self, app):
        app.shop_charges = {"bouclier": 1}
        before = app.mission.max_mistakes

        app._use_bouclier()

        assert app.mission.max_mistakes == before + 1
        assert app.shop_charges == {"bouclier": 0}
        app._refresh_mission_labels.assert_called_once()

    def test_ralenti_slows_current_wave_and_consumes_charge(self, app):
        app.shop_charges = {"ralenti": 1}

        app._use_ralenti()

        app.turret_scene.slow_ships.assert_called_once_with(2.0)
        assert app.shop_charges == {"ralenti": 0}


class TestShopChargesPersistence:
    def test_round_trip_is_faithful(self, make_profile_app):
        writer = make_profile_app(shop_charges={"traqueur": 1, "bouclier": 2})
        writer._save_profile()

        reader = make_profile_app(profile_path=writer.profile_path)
        reader._load_profile()

        assert reader.shop_charges == {"traqueur": 1, "bouclier": 2}

    def test_missing_key_falls_back_to_empty_dict(self, make_profile_app):
        app = make_profile_app()
        app._load_profile()
        assert app.shop_charges == {}


class TestTurretSceneBoosters:
    """Effets visuels (boutique) sur TurretScene : le traqueur a une fenêtre
    de temps, le ralenti rallonge le vol des vaisseaux encore vivants."""

    @pytest.fixture
    def scene(self):
        from ui_components import TurretScene

        scene = TurretScene.__new__(TurretScene)  # pas de constructeur Tk
        scene._ships = []
        scene._highlight_until = 0.0
        scene.slow_ships = TurretScene.slow_ships.__get__(scene)
        scene.highlight_correct = TurretScene.highlight_correct.__get__(scene)
        return scene

    def test_highlight_correct_sets_future_deadline(self, scene):
        scene.highlight_correct(3.0)
        assert scene._highlight_until > 0.0

    def test_slow_ships_only_touches_alive_ships(self, scene):
        alive = SimpleNamespace(alive=True, flight_time=8.0)
        dead = SimpleNamespace(alive=False, flight_time=8.0)
        scene._ships = [alive, dead]

        scene.slow_ships(2.0)

        assert alive.flight_time == 10.0
        assert dead.flight_time == 8.0  # vaisseau déjà résolu : inchangé
