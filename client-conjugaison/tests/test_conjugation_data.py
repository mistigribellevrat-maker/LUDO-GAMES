# tests/test_conjugation_data.py
"""Vérifie la COMPLÉTUDE de la table de conjugaison (6 temps × 6 pronoms par
verbe, rien de vide) et la cohérence des barèmes par niveau. Ne vérifie PAS
la justesse linguistique du contenu (non automatisable) — voir
conjugation_data.py pour cette mise en garde."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from conjugation_data import (  # noqa: E402
    ALL_VERBS, IRREGULAR_VERBS, PRONOUN_LABELS, REGULAR_VERBS, TENSE_BY_LEVEL,
    TENSE_LABELS, TENSES, VERB_POOL_BY_LEVEL, VERBS,
)
from problems import LEVELS  # noqa: E402


def test_all_verbs_have_all_tenses():
    for verb in ALL_VERBS:
        assert verb in VERBS, f"{verb} absent de VERBS"
        for tense in TENSES:
            assert tense in VERBS[verb], f"{verb}/{tense} manquant"


def test_every_form_is_six_non_empty_strings():
    for verb in ALL_VERBS:
        for tense in TENSES:
            forms = VERBS[verb][tense]
            assert len(forms) == len(PRONOUN_LABELS), f"{verb}/{tense} n'a pas 6 formes"
            for form in forms:
                assert isinstance(form, str) and form.strip(), f"{verb}/{tense} contient une forme vide"


def test_no_duplicate_verbs_between_regular_and_irregular():
    assert set(REGULAR_VERBS).isdisjoint(IRREGULAR_VERBS)
    assert ALL_VERBS == REGULAR_VERBS + IRREGULAR_VERBS


def test_tense_labels_cover_every_tense():
    for tense in TENSES:
        assert tense in TENSE_LABELS and TENSE_LABELS[tense].strip()


def test_level_scheme_matches_game_levels():
    assert set(TENSE_BY_LEVEL) == set(LEVELS)
    assert set(VERB_POOL_BY_LEVEL) == set(LEVELS)
    for level in LEVELS:
        for tense in TENSE_BY_LEVEL[level]:
            assert tense in TENSES, f"{level} référence un temps inconnu : {tense}"
        for verb in VERB_POOL_BY_LEVEL[level]:
            assert verb in VERBS, f"{level} référence un verbe inconnu : {verb}"
        assert len(VERB_POOL_BY_LEVEL[level]) >= 1
        assert len(TENSE_BY_LEVEL[level]) >= 1


def test_ce1_pool_is_regular_verbs_only():
    # CE1 doit rester la porte d'entrée : uniquement les verbes réguliers.
    assert set(VERB_POOL_BY_LEVEL["CE1"]) == set(REGULAR_VERBS)
