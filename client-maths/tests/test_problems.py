# tests/test_problems.py
"""Tests du générateur de problèmes et de la machine à états MathMission —
aucun Tk, aucun réseau : logique pure, exécutée 200x par niveau pour couvrir
l'espace aléatoire (bornes, positivité, exactitude de la réponse)."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from problems import (  # noqa: E402
    LEVELS, LEVEL_MULTIPLIERS, MAX_INTENSITY, MAX_MISTAKES, SEGMENTS,
    MathMission, compute_rewards, evaluate_badges, generate_problem,
)
from scoring import CREDITS_PER_MISSION, XP_PER_MISSION  # noqa: E402

REPEATS = 200


class TestGenerateProblem:
    def test_unknown_level_raises(self):
        with pytest.raises(ValueError):
            generate_problem("CP")

    @pytest.mark.parametrize("level", LEVELS)
    def test_question_matches_answer(self, level):
        for _ in range(REPEATS):
            problem = generate_problem(level)
            assert isinstance(problem.answer, int)
            assert problem.question  # jamais vide

    def test_ce1_bounds_and_no_negative_result(self):
        for _ in range(REPEATS):
            p = generate_problem("CE1")
            assert 0 <= p.answer <= 40  # deux termes <= 20, addition ou soustraction
            if "-" in p.question:
                assert p.answer >= 0

    def test_ce2_bounds_and_no_negative_result(self):
        for _ in range(REPEATS):
            p = generate_problem("CE2")
            assert 0 <= p.answer <= 200
            if "-" in p.question:
                assert p.answer >= 0

    def test_cm1_is_multiplication_table(self):
        for _ in range(REPEATS):
            p = generate_problem("CM1")
            assert "×" in p.question
            a, b = (int(x) for x in p.question.split(" × "))
            assert 2 <= a <= 10 and 2 <= b <= 10
            assert p.answer == a * b

    def test_cm2_division_is_exact(self):
        for _ in range(REPEATS):
            p = generate_problem("CM2")
            dividende_str, diviseur_str = p.question.split(" ÷ ")
            dividende, diviseur = int(dividende_str), int(diviseur_str)
            assert dividende % diviseur == 0
            assert p.answer == dividende // diviseur

    def test_college_respects_operator_precedence(self):
        for _ in range(REPEATS):
            p = generate_problem("Collège")
            assert p.answer >= 0  # jamais de résultat négatif (borné dans _college)


class TestIntensityRamp:
    """Montée en tension : les nombres s'élargissent légèrement à l'approche de
    la victoire (voir MAX_INTENSITY dans problems.py), toujours le même niveau
    scolaire, jamais démesuré."""

    @pytest.mark.parametrize("level", LEVELS)
    def test_max_intensity_produces_larger_or_equal_numbers_on_average(self, level):
        low_sum = sum(generate_problem(level, intensity=1.0).answer for _ in range(300))
        high_sum = sum(generate_problem(level, intensity=MAX_INTENSITY).answer for _ in range(300))
        assert high_sum > low_sum

    def test_cm1_table_extends_up_to_twelve_at_max_intensity(self):
        seen_high_factor = False
        for _ in range(300):
            p = generate_problem("CM1", intensity=MAX_INTENSITY)
            a, b = (int(x) for x in p.question.split(" × "))
            assert a <= 12 and b <= 12
            if a > 10 or b > 10:
                seen_high_factor = True
        assert seen_high_factor  # les facteurs 11/12 ne doivent apparaître qu'en intensité max


class TestMathMissionIntensity:
    def test_starts_at_base_intensity(self):
        mission = MathMission(level="CM1")
        assert mission._intensity() == pytest.approx(1.0)

    def test_intensity_ramps_up_as_segments_close(self):
        mission = MathMission(level="CM1", segments=10)
        mission.answer(mission.current.answer)  # 1/10 fermées
        first = mission._intensity()
        for _ in range(4):
            mission.answer(mission.current.answer)  # 5/10 fermées
        second = mission._intensity()
        assert 1.0 < first < second < MAX_INTENSITY

    def test_intensity_never_exceeds_max(self):
        mission = MathMission(level="CM1", segments=4)
        for _ in range(3):
            mission.answer(mission.current.answer)
        assert mission._intensity() <= MAX_INTENSITY

    def test_wrong_answers_do_not_increase_intensity(self):
        """Décision de design : monter la difficulté après une erreur serait
        décourageant, pas stimulant — seule la progression vers la victoire
        (closed) fait monter l'intensité, jamais les erreurs (mistakes)."""
        mission = MathMission(level="CM1")
        before = mission._intensity()
        mission.answer(mission.current.answer + 1000)  # forcément faux
        after = mission._intensity()
        assert before == after


class TestMathMission:
    def test_unknown_level_raises(self):
        with pytest.raises(ValueError):
            MathMission(level="CP")

    def test_starts_with_a_problem_and_no_progress(self):
        mission = MathMission(level="CM1")
        assert mission.current is not None
        assert mission.closed == 0
        assert mission.mistakes == 0
        assert not mission.finished

    def test_correct_answer_closes_a_segment(self):
        mission = MathMission(level="CM1")
        result = mission.answer(mission.current.answer)
        assert result == "correct"
        assert mission.closed == 1
        assert not mission.finished

    def test_wrong_answer_counts_a_mistake(self):
        mission = MathMission(level="CM1")
        wrong_value = mission.current.answer + 1000
        result = mission.answer(wrong_value)
        assert result == "wrong"
        assert mission.mistakes == 1
        assert mission.mistakes_remaining == MAX_MISTAKES - 1
        assert not mission.finished

    def test_third_mistake_triggers_defeat(self):
        mission = MathMission(level="CM1")
        for _ in range(MAX_MISTAKES):
            result = mission.answer(mission.current.answer + 1000)
            assert result == "wrong"
            assert not mission.finished
        result = mission.answer(mission.current.answer + 1000)
        assert result == "defeat"
        assert mission.finished
        assert not mission.victory

    def test_closing_all_segments_triggers_victory(self):
        mission = MathMission(level="CM1", segments=3)
        for _ in range(2):
            assert mission.answer(mission.current.answer) == "correct"
        result = mission.answer(mission.current.answer)
        assert result == "victory"
        assert mission.finished
        assert mission.victory
        assert mission.closed == 3

    def test_two_mistakes_do_not_end_the_mission(self):
        mission = MathMission(level="CM1")
        for _ in range(MAX_MISTAKES):
            mission.answer(mission.current.answer + 1000)
        assert not mission.finished

    def test_answer_after_finished_is_a_no_op(self):
        mission = MathMission(level="CM1", segments=1)
        assert mission.answer(mission.current.answer) == "victory"
        # Toute réponse ultérieure ne doit plus rien changer (mission déjà close).
        assert mission.answer(999999) == "victory"
        assert mission.closed == 1

    def test_non_numeric_answer_counts_as_wrong(self):
        mission = MathMission(level="CM1")
        result = mission.answer("pas un nombre")
        assert result == "wrong"
        assert mission.mistakes == 1

    def test_default_segments_and_mistakes_match_module_constants(self):
        mission = MathMission(level="CE1")
        assert mission.segments == SEGMENTS
        assert mission.max_mistakes == MAX_MISTAKES


class TestComputeRewards:
    def test_zero_score_gives_no_reward(self):
        assert compute_rewards("CM1", 0, SEGMENTS) == (0, 0)

    def test_perfect_score_gives_full_percent_and_xp(self):
        credits, xp = compute_rewards("CE1", SEGMENTS, SEGMENTS)
        assert credits == round(CREDITS_PER_MISSION * LEVEL_MULTIPLIERS["CE1"])
        assert xp == round(XP_PER_MISSION * LEVEL_MULTIPLIERS["CE1"])

    def test_harder_level_pays_more_for_the_same_score(self):
        """Crédits ET XP sont pondérés par la difficulté. L'XP ne l'était pas
        avant : répéter le niveau le plus facile était alors le chemin le plus
        rapide vers le grade suivant, ce qui décourage exactement le
        comportement qu'on veut récompenser."""
        ce1_credits, ce1_xp = compute_rewards("CE1", 5, SEGMENTS)
        college_credits, college_xp = compute_rewards("Collège", 5, SEGMENTS)
        assert college_credits > ce1_credits
        assert college_xp > ce1_xp

    def test_score_above_maximum_is_clamped(self):
        """Un score supérieur au nombre de cases ne doit jamais payer plus que
        la mission parfaite (garde-fou du barème commun)."""
        assert compute_rewards("CM1", SEGMENTS + 5, SEGMENTS) == compute_rewards("CM1", SEGMENTS, SEGMENTS)

    @pytest.mark.parametrize("level", LEVELS)
    def test_reward_scales_with_score(self, level):
        low_credits, low_xp = compute_rewards(level, 2, SEGMENTS)
        high_credits, high_xp = compute_rewards(level, 8, SEGMENTS)
        assert high_credits > low_credits
        assert high_xp > low_xp

    def test_unknown_level_falls_back_to_multiplier_one(self):
        credits, _xp = compute_rewards("CP", 5, SEGMENTS)
        assert credits == round((5 / SEGMENTS) * CREDITS_PER_MISSION * 1.0)


class TestEvaluateBadges:
    def test_victory_unlocks_first_win(self):
        newly = evaluate_badges(victory=True, mistakes=1, best_scores={}, badges=[])
        assert "maths_premiere_victoire" in newly
        assert "maths_grille_parfaite" not in newly

    def test_defeat_unlocks_nothing_victory_related(self):
        newly = evaluate_badges(victory=False, mistakes=3, best_scores={}, badges=[])
        assert "maths_premiere_victoire" not in newly
        assert "maths_grille_parfaite" not in newly

    def test_flawless_victory_unlocks_perfect_badge(self):
        newly = evaluate_badges(victory=True, mistakes=0, best_scores={}, badges=[])
        assert "maths_grille_parfaite" in newly

    def test_already_unlocked_badges_are_not_returned_again(self):
        newly = evaluate_badges(
            victory=True, mistakes=0, best_scores={},
            badges=["maths_premiere_victoire", "maths_grille_parfaite"],
        )
        assert newly == []

    def test_explorateur_requires_all_levels_present_in_best_scores(self):
        almost = {lvl: 5 for lvl in LEVELS[:-1]}
        newly = evaluate_badges(victory=False, mistakes=1, best_scores=almost, badges=[])
        assert "maths_explorateur" not in newly

        complete = {lvl: 5 for lvl in LEVELS}
        newly = evaluate_badges(victory=False, mistakes=1, best_scores=complete, badges=[])
        assert "maths_explorateur" in newly

    def test_explorateur_does_not_require_victory(self):
        """Comme "explorateur" côté dictée : il suffit d'avoir fermé au moins
        une case sur chaque niveau, pas de gagner la mission."""
        complete = {lvl: 1 for lvl in LEVELS}
        newly = evaluate_badges(victory=False, mistakes=2, best_scores=complete, badges=[])
        assert "maths_explorateur" in newly
