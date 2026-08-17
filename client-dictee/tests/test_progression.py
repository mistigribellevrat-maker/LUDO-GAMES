# tests/test_progression.py
"""Tests de la logique de progression (main.py) : grades/XP, records personnels,
succès (badges) et objectif quotidien. Comme les autres suites, on relie les VRAIES
méthodes non liées à un `SimpleNamespace` factice : aucun widget Tk, aucun réseau,
aucun fichier réel. La progression suit le joueur (elle est persistée dans le profil
local et synchronisée sur le serveur) : ces calculs doivent être stables.
"""

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as main_module  # noqa: E402

DictationAppClass = main_module.DictationApp


def make_app(**overrides):
    app = SimpleNamespace()
    app.GRADES = DictationAppClass.GRADES
    app.ECLAIR_MAX_SECONDS = DictationAppClass.ECLAIR_MAX_SECONDS
    app.RICH_CREDITS_THRESHOLD = DictationAppClass.RICH_CREDITS_THRESHOLD
    app.DAILY_BONUS_BASE = DictationAppClass.DAILY_BONUS_BASE
    app.DAILY_BONUS_PER_STREAK = DictationAppClass.DAILY_BONUS_PER_STREAK
    app.DAILY_BONUS_CAP = DictationAppClass.DAILY_BONUS_CAP
    app.DIFFICULTY_LEVELS = DictationAppClass.DIFFICULTY_LEVELS
    app._LEVEL_SLUGS = DictationAppClass._LEVEL_SLUGS
    app.STREAK_MILESTONES = DictationAppClass.STREAK_MILESTONES
    app.xp = 0
    app.credits = 0
    app.best_scores = {}
    app.badges = []
    app.levels_played = []
    app.last_play_date = ""
    app.streak = 0
    app._update_xp_display = MagicMock()
    app._grade_info = DictationAppClass._grade_info.__get__(app)
    app._record_best_score = DictationAppClass._record_best_score.__get__(app)
    app._award_xp = DictationAppClass._award_xp.__get__(app)
    app._evaluate_badges = DictationAppClass._evaluate_badges.__get__(app)
    app._daily_objective_check = DictationAppClass._daily_objective_check.__get__(app)
    for key, value in overrides.items():
        setattr(app, key, value)
    return app


class TestGrades:
    def test_grade_thresholds(self):
        assert make_app(xp=0)._grade_info() == ("Recrue", "Soldat", 0, 500)
        assert make_app(xp=500)._grade_info() == ("Soldat", "Caporal", 0, 1000)
        assert make_app(xp=1500)._grade_info() == ("Caporal", "Vétéran", 0, 2000)
        assert make_app(xp=4000)._grade_info() == ("Vétéran", "Grand Stratège", 500, 3500)

    def test_grade_no_longer_caps_at_grand_stratege(self):
        """L'ancien plafond (Grand Stratège à 1000 XP) était atteint en quelques
        parties : une fois les 4 joueurs au maximum, plus rien ne les
        départageait — précisément au moment où ils commencent à se comparer."""
        assert make_app(xp=7000)._grade_info() == ("Grand Stratège", "Amiral", 0, 7000)
        assert make_app(xp=14000)._grade_info()[0] == "Amiral"
        assert make_app(xp=28000)._grade_info()[0] == "Maître de Guerre"

    def test_max_grade(self):
        assert make_app(xp=56000)._grade_info() == ("Légende Galactique", None, 56000, 0)
        # Même au grade maximum, l'XP continue de monter : c'est elle qui
        # départage deux joueurs au sommet dans le classement global.
        assert make_app(xp=99999)._grade_info() == ("Légende Galactique", None, 99999, 0)


class TestAwardXp:
    def test_credits_the_gain_computed_by_the_shared_scale(self):
        app = make_app()
        assert app._award_xp(300) == 300
        assert app.xp == 300
        app._update_xp_display.assert_called_once()

    def test_negative_or_missing_gain_never_removes_xp(self):
        app = make_app(xp=500)
        assert app._award_xp(None) == 0
        assert app._award_xp(-50) == 0
        assert app.xp == 500


class TestBestScore:
    def test_new_record_detected(self):
        app = make_app()
        assert app._record_best_score("CM1", 15) is True
        assert app.best_scores["CM1"] == 15

    def test_lower_score_is_not_a_record(self):
        app = make_app(best_scores={"CM1": 15})
        assert app._record_best_score("CM1", 10) is False
        assert app.best_scores["CM1"] == 15

    def test_higher_score_updates_record(self):
        app = make_app(best_scores={"CM1": 15})
        assert app._record_best_score("CM1", 18) is True
        assert app.best_scores["CM1"] == 18


class TestBadges:
    def test_victory_and_perfect_and_lightning(self):
        app = make_app()
        newly = app._evaluate_badges("CM1", 20, duration=60.0)
        assert set(newly) == {"premiere_victoire", "sans_faute", "sans_faute_cm1", "eclair"}

    def test_slow_run_does_not_unlock_lightning(self):
        app = make_app()
        newly = app._evaluate_badges("CM1", 20, duration=600.0)
        assert "eclair" not in newly
        assert "sans_faute" in newly

    def test_explorateur_and_grand_strategie(self):
        app = make_app(levels_played=["CE1", "CE2", "CM1", "CM2"])
        newly = app._evaluate_badges("Collège", 18, duration=300.0)
        assert "explorateur" in newly
        assert "grand_strategie" in newly
        assert app.levels_played == ["CE1", "CE2", "CM1", "CM2", "Collège"]

    def test_riche(self):
        app = make_app(credits=300)
        newly = app._evaluate_badges("CE1", 10, duration=300.0)
        assert "riche" in newly

    def test_badges_are_not_duplicated(self):
        app = make_app(badges=["premiere_victoire"])
        newly = app._evaluate_badges("CM1", 18, duration=60.0)
        assert "premiere_victoire" not in newly
        assert app.badges.count("premiere_victoire") == 1

    def test_sans_faute_is_specific_to_each_level(self):
        app = make_app()
        newly_cm1 = app._evaluate_badges("CM1", 20, duration=60.0)
        assert "sans_faute_cm1" in newly_cm1
        assert "sans_faute_ce1" not in newly_cm1

        newly_ce1 = app._evaluate_badges("CE1", 20, duration=60.0)
        assert "sans_faute_ce1" in newly_ce1
        # Le générique "sans_faute" est déjà acquis : ne doit plus être "newly".
        assert "sans_faute" not in newly_ce1

    def test_imperfect_score_does_not_unlock_any_sans_faute_badge(self):
        app = make_app()
        newly = app._evaluate_badges("CM1", 19, duration=60.0)
        assert not any(bid.startswith("sans_faute") for bid in newly)

    def test_streak_milestones_unlock_at_thresholds(self):
        app = make_app(streak=7)
        newly = app._evaluate_badges("CM1", 5, duration=60.0)
        assert "streak_7" in newly
        assert "streak_30" not in newly
        assert "streak_100" not in newly

    def test_streak_milestone_not_reached_stays_locked(self):
        app = make_app(streak=6)
        newly = app._evaluate_badges("CM1", 5, duration=60.0)
        assert not any(bid.startswith("streak_") for bid in newly)

    def test_streak_milestones_are_not_duplicated_once_unlocked(self):
        app = make_app(streak=7, badges=["streak_7"])
        newly = app._evaluate_badges("CM1", 5, duration=60.0)
        assert "streak_7" not in newly


class TestDailyObjective:
    def test_first_play_grants_base_bonus_and_streak_one(self):
        app = make_app()
        result = app._daily_objective_check()
        assert result == (DictationAppClass.DAILY_BONUS_BASE, 1)
        assert app.streak == 1
        assert app.last_play_date == date.today().isoformat()
        assert app.credits == DictationAppClass.DAILY_BONUS_BASE

    def test_second_play_same_day_grants_nothing(self):
        app = make_app(last_play_date=date.today().isoformat(), streak=1, credits=0)
        assert app._daily_objective_check() is None
        assert app.credits == 0

    def test_consecutive_day_increases_streak_and_bonus(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        app = make_app(last_play_date=yesterday, streak=1, credits=0)
        bonus, streak = app._daily_objective_check()
        assert streak == 2
        assert bonus == DictationAppClass.DAILY_BONUS_BASE + DictationAppClass.DAILY_BONUS_PER_STREAK
        assert app.credits == bonus

    def test_broken_streak_resets_to_one(self):
        old = (date.today() - timedelta(days=5)).isoformat()
        app = make_app(last_play_date=old, streak=7, credits=0)
        bonus, streak = app._daily_objective_check()
        assert streak == 1
        assert bonus == DictationAppClass.DAILY_BONUS_BASE

    def test_bonus_is_capped(self):
        app = make_app(streak=1000, credits=0)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        app.last_play_date = yesterday
        bonus, _ = app._daily_objective_check()
        assert bonus == DictationAppClass.DAILY_BONUS_CAP
