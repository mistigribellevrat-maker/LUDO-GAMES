# tests/test_precision_stars.py
"""Étoiles de précision (main.py: _compute_precision_stars) : une mesure de
maîtrise indépendante des crédits/bouclier, pour donner un objectif de
perfectionnement sans jamais punir un joueur qui termine la dictée."""

from types import SimpleNamespace

import pytest


@pytest.fixture
def make_precision_app(DictationApp):
    def _factory(sentences_needing_correction=0, helps_used=0):
        app = SimpleNamespace()
        app._sentences_needing_correction = sentences_needing_correction
        app._helps_used_this_dictation = helps_used
        app._compute_precision_stars = DictationApp._compute_precision_stars.__get__(app)
        return app

    return _factory


class TestComputePrecisionStars:
    def test_perfect_run_gives_three_stars(self, make_precision_app):
        app = make_precision_app(sentences_needing_correction=0, helps_used=0)
        assert app._compute_precision_stars() == 3

    def test_one_correction_gives_two_stars(self, make_precision_app):
        app = make_precision_app(sentences_needing_correction=1, helps_used=0)
        assert app._compute_precision_stars() == 2

    def test_one_help_without_correction_gives_two_stars(self, make_precision_app):
        app = make_precision_app(sentences_needing_correction=0, helps_used=1)
        assert app._compute_precision_stars() == 2

    def test_one_correction_and_one_help_gives_one_star(self, make_precision_app):
        app = make_precision_app(sentences_needing_correction=1, helps_used=1)
        assert app._compute_precision_stars() == 1

    def test_worst_case_never_goes_below_one_star(self, make_precision_app):
        """Contrairement au bouclier/crédits, la précision ne doit jamais
        décourager un enfant qui a fini la dictée : le plancher est 1 étoile,
        jamais 0, quel que soit le nombre de corrections/aides."""
        app = make_precision_app(sentences_needing_correction=3, helps_used=5)
        assert app._compute_precision_stars() == 1

    @pytest.mark.parametrize("corrections,helps,expected", [
        (0, 0, 3),
        (2, 0, 1),
        (0, 2, 1),
        (3, 3, 1),
    ])
    def test_matrix(self, make_precision_app, corrections, helps, expected):
        app = make_precision_app(sentences_needing_correction=corrections, helps_used=helps)
        assert app._compute_precision_stars() == expected
