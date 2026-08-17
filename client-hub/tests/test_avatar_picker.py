# tests/test_avatar_picker.py
"""Résolution des avatars (avatar_picker.py) — les fonctions sans Tk, donc
testables sans fenêtre ni fichier réel du projet.

Enjeu : la convention existante stocke des chemins ABSOLUS (serveur et profils
de jeux). Un avatar choisi sur le PC d'un enfant arrive donc chez un autre avec
un chemin qui n'existe pas — c'est ce que `resolve_avatar` rattrape."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from avatar_picker import (  # noqa: E402
    avatar_label, avatars_dir, list_avatars, resolve_avatar, thumbnail_path,
)


@pytest.fixture
def fake_commun(tmp_path):
    """Faux dossier commun/ avec 3 avatars complets et 2 pièges : un .mp4 sans
    miniature, et une miniature sans vidéo."""
    directory = tmp_path / "assets" / "avatars"
    directory.mkdir(parents=True)
    for base in ("1", "1a", "1b"):
        (directory / f"{base}.mp4").write_bytes(b"")
        (directory / f"{base}.jpg").write_bytes(b"")
    (directory / "orphelin.mp4").write_bytes(b"")   # pas de miniature
    (directory / "solo.jpg").write_bytes(b"")       # pas de vidéo
    return str(tmp_path)


class TestListAvatars:
    def test_lists_only_complete_pairs_sorted(self, fake_commun):
        found = [Path(p).name for p in list_avatars(fake_commun)]
        assert found == ["1.mp4", "1a.mp4", "1b.mp4"]

    def test_video_without_thumbnail_is_ignored(self, fake_commun):
        """Sans miniature, l'avatar s'afficherait comme une case vide."""
        assert not any("orphelin" in p for p in list_avatars(fake_commun))

    def test_missing_directory_returns_empty(self, tmp_path):
        assert list_avatars(str(tmp_path / "inexistant")) == []

    def test_no_commun_dir_returns_empty(self):
        assert list_avatars("") == []
        assert list_avatars(None) == []

    def test_avatars_dir_points_into_commun(self, fake_commun):
        assert avatars_dir(fake_commun).endswith(str(Path("assets") / "avatars"))


class TestThumbnailPath:
    def test_swaps_extension(self):
        assert thumbnail_path("/x/y/1a.mp4") == "/x/y/1a.jpg"

    def test_keeps_directory_with_dots(self):
        assert thumbnail_path("/x.y/1.mp4") == "/x.y/1.jpg"


class TestResolveAvatar:
    def test_exact_path_wins(self, fake_commun):
        options = list_avatars(fake_commun)
        assert resolve_avatar(options[1], options) == options[1]

    def test_path_from_another_pc_is_matched_by_filename(self, fake_commun):
        """Cas réel : l'avatar a été choisi sur le PC d'un autre joueur, le
        serveur renvoie SON chemin absolu. On doit retrouver le fichier ici."""
        options = list_avatars(fake_commun)
        foreign = r"C:\Jeux\LUDO\commun\assets\avatars\1b.mp4"
        assert resolve_avatar(foreign, options) == [o for o in options if o.endswith("1b.mp4")][0]

    def test_filename_match_is_case_insensitive(self, fake_commun):
        options = list_avatars(fake_commun)
        assert resolve_avatar(r"D:\ailleurs\1A.MP4", options) is not None

    def test_unknown_avatar_returns_none(self, fake_commun):
        assert resolve_avatar(r"D:\ailleurs\99.mp4", list_avatars(fake_commun)) is None

    def test_empty_inputs_return_none(self, fake_commun):
        assert resolve_avatar(None, list_avatars(fake_commun)) is None
        assert resolve_avatar("1.mp4", []) is None


class TestAvatarLabel:
    def test_reads_better_than_a_filename(self):
        assert avatar_label("/x/y/1a.mp4") == "Avatar 1a"
