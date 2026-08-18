# tests/test_avatar_picker.py
"""Le Hub ne redéfinit plus le catalogue d'avatars : il le réexporte depuis
commun/avatars.py (testé dans commun/tests/test_avatars.py). Ce test verrouille
ce contrat — si un jour quelqu'un recopie ces fonctions dans le Hub, les deux
implémentations divergeront en silence."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import avatars  # noqa: E402
import avatar_picker  # noqa: E402

SHARED = ("avatar_label", "avatars_dir", "default_avatar", "list_avatars",
          "resolve_avatar", "thumbnail_path", "AVATAR_EXT", "THUMB_EXT")


class TestSharedCatalogue:
    def test_hub_reexports_the_shared_catalogue(self):
        for name in SHARED:
            assert getattr(avatar_picker, name) is getattr(avatars, name), name

    def test_picker_grid_stays_readable_when_avatars_are_added(self):
        """4 colonnes : 8 avatars tiennent en 2 rangées. À 2 colonnes, la boîte
        de dialogue deviendrait plus haute que l'écran."""
        assert avatar_picker.AvatarPicker.COLUMNS == 4
