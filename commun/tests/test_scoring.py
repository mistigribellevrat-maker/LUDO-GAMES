# tests/test_scoring.py
"""Tests du barème commun (scoring.py) — le contrat qui garantit qu'une même
performance vaut la même chose dans tous les jeux. Aucune dépendance : ni Tk,
ni réseau, ni fichier."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scoring import (  # noqa: E402
    CREDITS_PER_MISSION, GRADES, LEVEL_MULTIPLIERS, XP_PER_MISSION,
    clamp_ratio, compute_rewards, grade_info, grade_name,
)


class TestClampRatio:
    def test_normal_ratios(self):
        assert clamp_ratio(20, 20) == 1.0
        assert clamp_ratio(10, 20) == 0.5
        assert clamp_ratio(0, 20) == 0.0

    def test_out_of_range_is_clamped(self):
        assert clamp_ratio(25, 20) == 1.0
        assert clamp_ratio(-5, 20) == 0.0

    def test_absurd_maximum_never_raises(self):
        """Un barème ne doit jamais faire planter une fin de mission."""
        assert clamp_ratio(5, 0) == 0.0
        assert clamp_ratio(5, None) == 0.0
        assert clamp_ratio("bof", 20) == 0.0


class TestComputeRewards:
    def test_zero_ratio_pays_nothing(self):
        assert compute_rewards("CM1", 0.0) == (0, 0)

    def test_perfect_ce1_mission_matches_the_historical_scale(self):
        """Barème crédits inchangé par la mise en commun : 100 % en CE1 = 100
        crédits, exactement comme avant la refonte."""
        assert compute_rewards("CE1", 1.0) == (CREDITS_PER_MISSION, XP_PER_MISSION)

    @pytest.mark.parametrize("level", list(LEVEL_MULTIPLIERS))
    def test_credits_and_xp_both_follow_the_level_multiplier(self, level):
        mult = LEVEL_MULTIPLIERS[level]
        credits, xp = compute_rewards(level, 1.0)
        assert credits == round(CREDITS_PER_MISSION * mult)
        assert xp == round(XP_PER_MISSION * mult)

    def test_harder_level_pays_strictly_more_xp(self):
        """Le cœur de la refonte : sans ça, répéter le niveau le plus facile
        reste le chemin le plus rapide vers le grade suivant."""
        assert compute_rewards("Collège", 1.0)[1] > compute_rewards("CE1", 1.0)[1]

    def test_same_ratio_pays_the_same_in_every_game(self):
        """Deux jeux d'égal poids : « 80 % au niveau CM2 » vaut pareil des deux
        côtés, sinon les XP accumulées ne sont plus comparables entre joueurs
        qui ne jouent pas aux mêmes jeux."""
        dictee = compute_rewards("CM2", clamp_ratio(16, 20))     # 16/20 en dictée
        maths = compute_rewards("CM2", clamp_ratio(8, 10))       # 8/10 cases fermées
        assert dictee == maths

    def test_game_weight_scales_xp_only(self):
        """Un futur jeu plus long peut peser plus en XP sans déséquilibrer
        l'économie de boutique, commune à tous les jeux."""
        base_credits, base_xp = compute_rewards("CE1", 1.0)
        heavy_credits, heavy_xp = compute_rewards("CE1", 1.0, game_weight=2.0)
        assert heavy_credits == base_credits
        assert heavy_xp == base_xp * 2

    def test_unknown_level_falls_back_to_multiplier_one(self):
        assert compute_rewards("CP", 1.0) == (CREDITS_PER_MISSION, XP_PER_MISSION)

    def test_ratio_above_one_is_clamped(self):
        assert compute_rewards("CE1", 3.0) == compute_rewards("CE1", 1.0)


class TestGrades:
    def test_grades_are_sorted_and_start_at_zero(self):
        thresholds = [g["xp"] for g in GRADES]
        assert thresholds[0] == 0
        assert thresholds == sorted(thresholds)
        assert len(set(thresholds)) == len(thresholds)

    def test_first_and_last_grade(self):
        assert grade_info(0) == ("Recrue", "Soldat", 0, GRADES[1]["xp"])
        last = GRADES[-1]
        assert grade_info(last["xp"]) == (last["name"], None, last["xp"], 0)

    def test_progress_within_a_tier(self):
        name, nxt, xp_in, xp_needed = grade_info(GRADES[1]["xp"] + 100)
        assert name == GRADES[1]["name"]
        assert nxt == GRADES[2]["name"]
        assert xp_in == 100
        assert xp_needed == GRADES[2]["xp"] - GRADES[1]["xp"]

    def test_top_grade_needs_many_missions(self):
        """Garde-fou de calibrage : le dernier palier doit rester un horizon
        lointain, pas une étape atteinte en quelques jours (le défaut de
        l'ancienne échelle, plafonnée à 1000 XP)."""
        best_xp_per_mission = compute_rewards("Collège", 1.0)[1]
        assert GRADES[-1]["xp"] / best_xp_per_mission > 100

    def test_grade_name_matches_grade_info(self):
        for xp in (0, 499, 500, 12345, 10 ** 6):
            assert grade_name(xp) == grade_info(xp)[0]

    def test_invalid_xp_is_treated_as_zero(self):
        assert grade_name(None) == "Recrue"
        assert grade_name("beaucoup") == "Recrue"
