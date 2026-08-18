# tests/test_problems.py
"""Tests de la logique pure (problems.py) — aucun Tk, aucun réseau. Répète
chaque vérification REPEATS fois par niveau pour couvrir statistiquement
l'espace aléatoire (choix du verbe/temps/pronom/leurres)."""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from conjugation_data import TENSE_BY_LEVEL, VERBS  # noqa: E402
from problems import (  # noqa: E402
    LEVELS, MAX_MISTAKES, SEGMENTS, SHIP_COUNT, ConjugationMission,
    compute_rewards, evaluate_badges, generate_wave,
)

REPEATS = 200


def test_generate_wave_has_exactly_one_correct_ship():
    for level in LEVELS:
        for _ in range(REPEATS):
            wave = generate_wave(level)
            correct = [s for s in wave.ships if s.is_correct]
            assert len(correct) == 1
            assert wave.correct_text == correct[0].text


def test_generate_wave_ship_count_matches_level():
    for level in LEVELS:
        for _ in range(REPEATS):
            wave = generate_wave(level)
            assert len(wave.ships) == SHIP_COUNT[level]
            # pas de doublon de texte dans une même vague
            texts = [s.text for s in wave.ships]
            assert len(texts) == len(set(texts))


def test_generate_wave_tense_respects_level():
    for level in LEVELS:
        for _ in range(REPEATS):
            wave = generate_wave(level)
            assert wave.tense in TENSE_BY_LEVEL[level]


def test_decoys_are_always_real_forms_of_the_same_verb():
    """Aucun leurre inventé : chaque leurre doit être la forme du même verbe,
    au même pronom, à un AUTRE temps réel de la table."""
    for level in LEVELS:
        for _ in range(REPEATS):
            wave = generate_wave(level)
            other_forms = {
                VERBS[wave.verb][t][wave.pronoun_index]
                for t in VERBS[wave.verb]
                if t != wave.tense
            }
            for ship in wave.ships:
                if not ship.is_correct:
                    assert ship.text in other_forms, (
                        f"leurre inventé détecté : {ship.text!r} pour {wave.verb}"
                    )


def test_mission_victory_after_enough_correct_hits():
    m = ConjugationMission(level="CE1")
    result = "correct"
    for _ in range(SEGMENTS - 1):
        result = m.resolve(True)
        assert result == "correct"
    result = m.resolve(True)
    assert result == "victory"
    assert m.finished and m.victory
    assert m.closed == SEGMENTS
    # une mission terminée n'a plus d'effet
    assert m.resolve(True) == "victory"


def test_mission_defeat_after_too_many_misses():
    m = ConjugationMission(level="CE2")
    for _ in range(MAX_MISTAKES):
        result = m.resolve(False)
        assert result == "wrong"
    result = m.resolve(False)
    assert result == "defeat"
    assert m.finished and not m.victory
    assert m.resolve(False) == "defeat"


def test_mistakes_remaining_property():
    m = ConjugationMission(level="CM1")
    assert m.mistakes_remaining == MAX_MISTAKES
    m.resolve(False)
    assert m.mistakes_remaining == MAX_MISTAKES - 1


def test_mission_rejects_unknown_level():
    with pytest.raises(ValueError):
        ConjugationMission(level="Prépa")


def test_evaluate_badges_first_victory_and_perfect():
    newly = evaluate_badges(victory=True, mistakes=0, best_scores={}, badges=[])
    assert "conj_premiere_victoire" in newly
    assert "conj_defense_parfaite" in newly

    newly = evaluate_badges(victory=True, mistakes=1, best_scores={}, badges=[])
    assert "conj_premiere_victoire" in newly
    assert "conj_defense_parfaite" not in newly

    newly = evaluate_badges(victory=False, mistakes=0, best_scores={}, badges=[])
    assert newly == []


def test_evaluate_badges_does_not_mutate_and_skips_already_unlocked():
    badges = ["conj_premiere_victoire"]
    newly = evaluate_badges(victory=True, mistakes=0, best_scores={}, badges=badges)
    assert "conj_premiere_victoire" not in newly
    assert badges == ["conj_premiere_victoire"]  # non muté


def test_evaluate_badges_polyglotte_needs_every_level():
    best_scores = {level: 5 for level in LEVELS[:-1]}
    newly = evaluate_badges(victory=False, mistakes=0, best_scores=best_scores, badges=[])
    assert "conj_polyglotte" not in newly

    best_scores = {level: 5 for level in LEVELS}
    newly = evaluate_badges(victory=False, mistakes=0, best_scores=best_scores, badges=[])
    assert "conj_polyglotte" in newly


def test_compute_rewards_zero_score_gives_nothing():
    assert compute_rewards("CE1", 0, SEGMENTS) == (0, 0)


def test_compute_rewards_positive_score_gives_positive_reward():
    credits, xp = compute_rewards("CM2", SEGMENTS, SEGMENTS)
    assert credits > 0
    assert xp > 0
