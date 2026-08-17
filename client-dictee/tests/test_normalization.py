# tests/test_normalization.py
"""Tests de DictationApp._normalize_text, _sanitize_explanation et _clamp_index
(main.py). Aucune de ces méthodes n'utilise `self` : on peut donc les appeler en
passant None comme `self`, sans double de test ni instanciation Tk."""

import pytest


def normalize(DictationApp, text):
    return DictationApp._normalize_text(None, text)


class TestNormalizeText:
    def test_accents_preserved_and_lowercased(self, DictationApp):
        assert normalize(DictationApp, "Élève") == "élève"
        assert normalize(DictationApp, "ÉTÉ") == "été"

    @pytest.mark.parametrize(
        "straight,typographic",
        [
            ("L'école", "L’école"),
            ("aujourd'hui", "aujourd’hui"),
        ],
    )
    def test_straight_and_typographic_apostrophes_are_equivalent(self, DictationApp, straight, typographic):
        assert normalize(DictationApp, straight) == normalize(DictationApp, typographic)

    def test_case_insensitive(self, DictationApp):
        assert normalize(DictationApp, "BONJOUR") == normalize(DictationApp, "bonjour") == "bonjour"
        assert normalize(DictationApp, "BoNjOuR") == "bonjour"

    def test_multiple_spaces_collapsed(self, DictationApp):
        assert normalize(DictationApp, "Le   chat    dort") == normalize(DictationApp, "Le chat dort")
        assert normalize(DictationApp, "Le   chat    dort") == "le chat dort"

    def test_empty_string(self, DictationApp):
        assert normalize(DictationApp, "") == ""

    def test_whitespace_only_string(self, DictationApp):
        assert normalize(DictationApp, "   \n\t  ") == ""

    def test_multiline_text_is_flattened(self, DictationApp):
        result = normalize(DictationApp, "Bonjour,\nComment ça va ?")
        assert "\n" not in result
        assert result == "bonjour comment ça va"

    def test_punctuation_is_stripped(self, DictationApp):
        assert normalize(DictationApp, "Le chat dort, il rêve.") == "le chat dort il rêve"

    def test_punctuation_directly_glued_to_words_merges_them(self, DictationApp):
        # Documente le comportement actuel : la ponctuation est retirée sans jamais
        # insérer d'espace. Si un mot est collé à sa ponctuation (aucun espace de
        # part et d'autre), les deux mots fusionnent après normalisation. C'est
        # cohérent avec le fait que la ponctuation est de toute façon ignorée dans
        # la comparaison finale (les deux côtés subissent le même traitement), mais
        # cela reste une particularité à connaître : ce n'est PAS une tokenisation
        # mot-à-mot (voir _tokenize_words pour ça).
        assert normalize(DictationApp, "Bonjour!Comment") == "bonjourcomment"
        assert normalize(DictationApp, "Bonjour ! Comment") == "bonjour comment"

    def test_identical_after_normalization_regardless_of_case_and_punctuation(self, DictationApp):
        original = "Le Chat, Noir, Dort."
        user = "le chat noir dort"
        assert normalize(DictationApp, original) == normalize(DictationApp, user)


class TestSanitizeExplanation:
    def test_empty_text_returns_empty_string(self, DictationApp):
        assert DictationApp._sanitize_explanation(None, "") == ""
        assert DictationApp._sanitize_explanation(None, None) == ""

    def test_strips_code_blocks(self, DictationApp):
        text = "Avant ```print('x')``` après"
        result = DictationApp._sanitize_explanation(None, text)
        assert "print" not in result
        assert "Avant" in result and "après" in result

    def test_strips_markdown_emphasis_and_backticks(self, DictationApp):
        text = "**gras** __gras2__ *italique* `code`"
        result = DictationApp._sanitize_explanation(None, text)
        assert "*" not in result
        assert "`" not in result
        assert "_" not in result

    def test_strips_list_bullets_and_headers(self, DictationApp):
        text = "# Titre\n- point un\n> citation\nsimple ligne"
        result = DictationApp._sanitize_explanation(None, text)
        assert "#" not in result
        assert result.startswith("Titre") or "Titre" in result
        assert "point un" in result
        assert "citation" in result

    def test_compacts_whitespace(self, DictationApp):
        text = "mot1     mot2\n\n\nmot3"
        result = DictationApp._sanitize_explanation(None, text)
        assert result == "mot1 mot2 mot3"

    def test_truncates_to_280_chars(self, DictationApp):
        text = "a" * 500
        result = DictationApp._sanitize_explanation(None, text)
        assert len(result) == 280


class TestClampIndex:
    def test_clamps_negative_to_zero(self, DictationApp):
        assert DictationApp._clamp_index(None, -5, 10) == 0

    def test_clamps_to_last_valid_index(self, DictationApp):
        assert DictationApp._clamp_index(None, 999, 10) == 9

    def test_within_bounds_is_unchanged(self, DictationApp):
        assert DictationApp._clamp_index(None, 4, 10) == 4

    def test_none_index_defaults_to_zero(self, DictationApp):
        assert DictationApp._clamp_index(None, None, 10) == 0

    def test_empty_text_length_returns_zero(self, DictationApp):
        assert DictationApp._clamp_index(None, 5, 0) == 0
        assert DictationApp._clamp_index(None, -5, 0) == 0
        assert DictationApp._clamp_index(None, 0, 0) == 0
