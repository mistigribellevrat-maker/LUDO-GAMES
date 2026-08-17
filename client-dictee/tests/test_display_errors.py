# tests/test_display_errors.py
"""Tests de DictationApp.display_errors (main.py) : c'est ce calcul qui retire des
points de bouclier à l'enfant, donc c'est la règle métier la plus sensible du jeu :

    mistake_count += max(i2 - i1, j2 - j1)   # pour chaque opcode difflib != 'equal'

Le nombre de fautes est affiché (statut "N anomalies détectées"), mais la perte de
bouclier est plafonnée à 1 point par validation (self.lose_points(1)) : une phrase
ne peut pas faire perdre plus d'un point, quelle que soit la gravité.

display_errors est une méthode d'instance qui touche des widgets Tk (self.user_text,
self.errors_frame, self.status_label) : on utilise le double `fake_display_errors_app`
(voir conftest.py) qui relie la VRAIE méthode display_errors (et _tokenize_words) à un
self factice avec des MagicMock à la place des widgets. On teste donc le code de
production exact, pas une réplique de la logique de comptage.

Les valeurs de référence (mistake_count attendu) ont été vérifiées indépendamment en
rejouant difflib.SequenceMatcher.get_opcodes() sur les mêmes paires de phrases.
"""

import tkinter as tk

import pytest


class TestMistakeCounting:
    def test_perfect_sentence_no_mistakes_no_penalty(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat dort", "Le chat dort", penalize=True)
        app.lose_points.assert_not_called()

    def test_perfect_sentence_case_insensitive_no_mistakes(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le Chat Dort", "le chat dort", penalize=True)
        app.lose_points.assert_not_called()

    def test_single_word_substitution_counts_as_one_mistake(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat noir dort", "Le chien noir dort", penalize=True)
        app.lose_points.assert_called_once_with(1)

    def test_missing_word_counts_as_one_mistake(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le petit chat dort", "Le chat dort", penalize=True)
        app.lose_points.assert_called_once_with(1)

    def test_extra_word_counts_as_one_mistake(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat dort", "Le petit chat dort", penalize=True)
        app.lose_points.assert_called_once_with(1)

    def test_multiple_mistakes_are_all_counted_but_penalty_capped_to_one(self, fake_display_errors_app):
        app = fake_display_errors_app
        # delete("grand") + replace("noir"->"blanc") + delete("vite") == 3 fautes
        # affichées, mais la perte de bouclier est plafonnée à 1 point.
        app.display_errors("Un grand chat noir court vite", "Un chat blanc court", penalize=True)
        app.lose_points.assert_called_once_with(1)

    def test_empty_user_answer_counts_every_original_word_as_missing(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat dort.", "", penalize=True)
        app.lose_points.assert_called_once_with(1)

    def test_student_types_sentence_twice_counts_the_repeat_as_extra_words(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat dort", "Le chat dort Le chat dort", penalize=True)
        app.lose_points.assert_called_once_with(1)

    def test_both_empty_no_mistakes(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("", "", penalize=True)
        app.lose_points.assert_not_called()

    def test_penalize_false_never_calls_lose_points_even_with_mistakes(self, fake_display_errors_app):
        """Utilisé par _on_help_ready() après auto-correction : il ne faut jamais
        pénaliser deux fois la même erreur."""
        app = fake_display_errors_app
        app.display_errors("Le chat noir dort", "Le chien noir dort", penalize=False)
        app.lose_points.assert_not_called()


class TestDisplayErrorsSideEffects:
    def test_clears_error_frame_every_call(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat dort", "Le chat dort", penalize=True)
        app._clear_errors_frame.assert_called_once()

    def test_removes_previous_error_tags_before_recomputing(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat dort", "Le chien dort", penalize=True)
        app.user_text.tag_remove.assert_called_once_with("error", "1.0", tk.END)

    def test_substitution_creates_one_error_ui_entry(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat noir dort", "Le chien noir dort", penalize=True)
        assert app._create_error_ui.call_count == 1

    def test_status_label_uses_singular_for_one_mistake(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat noir dort", "Le chien noir dort", penalize=True)
        text = app.status_label.config.call_args.kwargs["text"]
        assert text == "1 anomalie détectée."

    def test_status_label_uses_plural_for_multiple_mistakes(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Un grand chat noir court vite", "Un chat blanc court", penalize=True)
        text = app.status_label.config.call_args.kwargs["text"]
        assert text == "3 anomalies détectées."

    def test_status_label_untouched_when_no_mistakes(self, fake_display_errors_app):
        app = fake_display_errors_app
        app.display_errors("Le chat dort", "Le chat dort", penalize=True)
        app.status_label.config.assert_not_called()
