# tests/test_tokenize.py
"""Tests de DictationApp._tokenize_words (main.py).

C'est le coeur du surlignage d'erreur dans le widget Tk : chaque span (start, end)
retourné DOIT pointer exactement sur le mot correspondant dans la chaîne d'origine,
sinon le surlignage `tag_add("error", ...)` colorierait le mauvais texte à l'écran.
_tokenize_words n'utilise pas `self` : on l'appelle avec self=None.
"""

import pytest


def tokenize(DictationApp, text):
    return DictationApp._tokenize_words(None, text)


def assert_spans_match_source(text, tokens):
    """Vérifie, pour CHAQUE token, que texte[start:end] == mot (le coeur du test)."""
    for word, (start, end) in tokens:
        assert text[start:end] == word, f"span ({start},{end}) ne pointe pas sur {word!r} dans {text!r}"


class TestTokenizeWords:
    def test_empty_string_returns_no_tokens(self, DictationApp):
        assert tokenize(DictationApp, "") == []

    def test_simple_sentence(self, DictationApp):
        text = "Le chat dort."
        tokens = tokenize(DictationApp, text)
        assert [w for w, _ in tokens] == ["Le", "chat", "dort"]
        assert_spans_match_source(text, tokens)

    def test_accented_words(self, DictationApp):
        text = "Où êtes-vous allés cet été ?"
        tokens = tokenize(DictationApp, text)
        # Le tiret dans "êtes-vous" n'est pas un caractère de mot : il coupe le token.
        assert [w for w, _ in tokens] == ["Où", "êtes", "vous", "allés", "cet", "été"]
        assert_spans_match_source(text, tokens)

    def test_apostrophe_splits_the_word(self, DictationApp):
        text = "j'aime les pommes"
        tokens = tokenize(DictationApp, text)
        assert [w for w, _ in tokens] == ["j", "aime", "les", "pommes"]
        assert_spans_match_source(text, tokens)

    def test_punctuation_glued_to_words_still_yields_correct_spans(self, DictationApp):
        text = "chat,chien.oiseau!souris"
        tokens = tokenize(DictationApp, text)
        assert [w for w, _ in tokens] == ["chat", "chien", "oiseau", "souris"]
        assert_spans_match_source(text, tokens)

    def test_multiple_spaces_between_words(self, DictationApp):
        text = "Le    chat     dort"
        tokens = tokenize(DictationApp, text)
        assert [w for w, _ in tokens] == ["Le", "chat", "dort"]
        assert_spans_match_source(text, tokens)

    def test_multiline_text_offsets_are_absolute(self, DictationApp):
        text = "Bonjour\nComment ça va"
        tokens = tokenize(DictationApp, text)
        assert [w for w, _ in tokens] == ["Bonjour", "Comment", "ça", "va"]
        assert_spans_match_source(text, tokens)
        # "Comment" doit démarrer après le \n, pas être décalé comme si tout tenait
        # sur une seule ligne.
        comment_span = tokens[1][1]
        assert text[comment_span[0]] == "C"

    def test_digits_are_tokenized(self, DictationApp):
        text = "Il y a 3 pommes et 12 poires"
        tokens = tokenize(DictationApp, text)
        assert [w for w, _ in tokens] == ["Il", "y", "a", "3", "pommes", "et", "12", "poires"]
        assert_spans_match_source(text, tokens)

    def test_case_is_preserved_in_returned_words(self, DictationApp):
        text = "Le CHAT Dort"
        tokens = tokenize(DictationApp, text)
        assert [w for w, _ in tokens] == ["Le", "CHAT", "Dort"]

    def test_only_punctuation_returns_no_tokens(self, DictationApp):
        assert tokenize(DictationApp, "... , ; ! ?") == []

    @pytest.mark.parametrize(
        "text",
        [
            "Les élèves étudient à l'école cet été.",
            "  espaces en début et fin  ",
            "Ligne1\nLigne2\r\nLigne3",
            "Mélange de CHIFFRES 42 et de MOTS-composés.",
            "",
        ],
    )
    def test_spans_always_match_source_text(self, DictationApp, text):
        tokens = tokenize(DictationApp, text)
        assert_spans_match_source(text, tokens)
