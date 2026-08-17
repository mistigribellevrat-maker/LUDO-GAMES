# avatar_picker.py
"""Choix de l'avatar depuis le Hub.

L'avatar fait partie de l'identité GLOBALE du joueur : le serveur le stocke sur
le joueur, pas sur le jeu (`players.avatar_path`), et chaque jeu s'en sert à sa
façon — vidéo de démarrage en dictée, portrait dans la grille de maths. Il ne
pouvait pourtant se changer que depuis la dictée, alors que le Hub est
justement l'écran d'identité.

Les fonctions de résolution (`list_avatars`, `resolve_avatar`,
`thumbnail_path`) sont volontairement sans Tk : testables sans fenêtre.

Note sur les chemins : la convention existante (dictée, maths, serveur) stocke
un chemin ABSOLU vers le `.mp4`. Il n'est donc pas valable d'un PC à l'autre —
`resolve_avatar` retombe pour cette raison sur une comparaison par nom de
fichier, pour qu'un avatar choisi ailleurs reste reconnu ici.
"""

import logging
import os
import tkinter as tk

from theme import FONT_BODY, FONT_DISPLAY, PALETTE
from ui_widgets import NeonButton, RoundedFrame, SectionHeader

logger = logging.getLogger(__name__)

# Un avatar = une vidéo .mp4 (utilisée par la dictée) + une miniature .jpg de
# même nom de base (utilisée partout ailleurs).
AVATAR_EXT = ".mp4"
THUMB_EXT = ".jpg"


def avatars_dir(commun_dir: str) -> str:
    return os.path.join(commun_dir, "assets", "avatars")


def list_avatars(commun_dir: str) -> list:
    """Avatars disponibles (chemins absolus vers le .mp4), triés par nom.

    Découverte par le contenu du dossier plutôt que par une liste codée en dur :
    déposer un nouveau couple `X.mp4` + `X.jpg` suffit à l'ajouter au choix,
    sans toucher au code. Un .mp4 sans miniature est ignoré — il s'afficherait
    comme une case vide dans le sélecteur."""
    directory = avatars_dir(commun_dir or "")
    if not os.path.isdir(directory):
        return []
    found = []
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(AVATAR_EXT):
            continue
        path = os.path.join(directory, name)
        if os.path.exists(thumbnail_path(path)):
            found.append(path)
    return found


def thumbnail_path(avatar_path: str) -> str:
    """Miniature .jpg d'un avatar (même nom de base que la vidéo)."""
    base = os.path.splitext(avatar_path)[0]
    return base + THUMB_EXT


def avatar_label(avatar_path: str) -> str:
    """Libellé lisible : « Avatar 1 », « Avatar 1a »… plutôt que « 1a.mp4 »."""
    base = os.path.splitext(os.path.basename(avatar_path))[0]
    return f"Avatar {base}"


def resolve_avatar(avatar_path: str, options: list) -> str | None:
    """Ramène un chemin d'avatar (venant du serveur ou d'un profil local) vers
    l'option correspondante SUR CE PC.

    Trois cas, dans l'ordre : chemin exact connu ; même nom de fichier à un
    autre emplacement (avatar choisi sur un autre PC, ou dossier d'installation
    différent) ; sinon None, à l'appelant de choisir un repli."""
    if not avatar_path or not options:
        return None
    if avatar_path in options:
        return avatar_path
    wanted = os.path.basename(avatar_path).lower()
    for option in options:
        if os.path.basename(option).lower() == wanted:
            return option
    return None


class AvatarPicker(tk.Toplevel):
    """Grille d'avatars cliquables. `on_choose(avatar_path)` est appelé à la
    validation, jamais à l'annulation."""

    THUMB_SIZE = (96, 96)
    COLUMNS = 4

    def __init__(self, parent, commun_dir: str, current: str = None, on_choose=None) -> None:
        super().__init__(parent)
        self.title("CHOIX DE L'AVATAR")
        self.configure(bg=PALETTE["bg"])
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self._on_choose = on_choose
        self._options = list_avatars(commun_dir)
        self._selected = resolve_avatar(current, self._options) or (self._options[0] if self._options else None)
        self._thumbs = {}   # références gardées : Tk ne retient pas les PhotoImage
        self._cells = {}

        header = tk.Frame(self, bg=PALETTE["bg"])
        header.pack(fill=tk.X, padx=24, pady=(20, 4))
        SectionHeader(header, eyebrow="Identité du commandant",
                      title="Choisissez votre avatar", bg=PALETTE["bg"]).pack(anchor="w")
        tk.Label(header, text="Il vous suit dans tous les jeux et s'affiche dans le classement.",
                 bg=PALETTE["bg"], fg=PALETTE["muted"], font=(FONT_BODY, 9)).pack(anchor="w", pady=(4, 0))

        if not self._options:
            tk.Label(self, text="Aucun avatar trouvé dans commun/assets/avatars.",
                     bg=PALETTE["bg"], fg=PALETTE["danger"], font=(FONT_BODY, 10, "italic")
                     ).pack(padx=24, pady=24)
        else:
            grid = tk.Frame(self, bg=PALETTE["bg"])
            grid.pack(padx=20, pady=(14, 6))
            for index, option in enumerate(self._options):
                row, col = divmod(index, self.COLUMNS)
                self._build_cell(grid, option).grid(row=row, column=col, padx=8, pady=8)

        buttons = tk.Frame(self, bg=PALETTE["bg"])
        buttons.pack(fill=tk.X, padx=24, pady=(6, 18))
        NeonButton(buttons, text="Annuler", command=self.destroy, variant="ghost",
                   bg=PALETTE["bg"], height=34).pack(side=tk.RIGHT)
        self._validate_button = NeonButton(buttons, text="Choisir cet avatar", command=self._validate,
                                           variant="solid", bg=PALETTE["bg"], height=34)
        self._validate_button.pack(side=tk.RIGHT, padx=(0, 10))
        if not self._options:
            self._validate_button.set_state(tk.DISABLED)

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_reqheight()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    # --- Rendu ------------------------------------------------------------

    def _load_thumb(self, avatar_path: str):
        """Miniature Tk d'un avatar, ou None si Pillow ou le fichier manque —
        le sélecteur reste alors utilisable, avec le seul libellé."""
        if avatar_path in self._thumbs:
            return self._thumbs[avatar_path]
        try:
            from PIL import Image, ImageTk
            image = Image.open(thumbnail_path(avatar_path)).resize(
                self.THUMB_SIZE, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
        except Exception as e:  # noqa: BLE001 — Pillow absent, fichier illisible, format inattendu
            logger.warning("Miniature d'avatar illisible (%s): %s", avatar_path, e)
            photo = None
        self._thumbs[avatar_path] = photo
        return photo

    def _build_cell(self, parent, avatar_path: str) -> tk.Widget:
        card = RoundedFrame(parent, padding=10, bg=PALETTE["bg"])
        card.configure(width=self.THUMB_SIZE[0] + 40, height=self.THUMB_SIZE[1] + 62)
        inner = card.inner

        thumb = self._load_thumb(avatar_path)
        if thumb is not None:
            visual = tk.Label(inner, image=thumb, bg=PALETTE["panel2"], bd=0)
            visual.image = thumb
        else:
            visual = tk.Label(inner, text="?", bg=PALETTE["panel2"], fg=PALETTE["muted"],
                              font=(FONT_DISPLAY, 28, "bold"), width=4, height=2)
        visual.pack()

        label = tk.Label(inner, text=avatar_label(avatar_path), bg=PALETTE["panel2"],
                         fg=PALETTE["muted"], font=(FONT_BODY, 9))
        label.pack(pady=(6, 0))

        # Toute la carte est cliquable, pas seulement l'image : c'est la cible
        # la plus facile à viser pour un enfant.
        for widget in (card, inner, visual, label):
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", lambda _e, p=avatar_path: self._select(p))

        self._cells[avatar_path] = card
        self._paint_cell(avatar_path)
        return card

    def _paint_cell(self, avatar_path: str) -> None:
        """Anneau d'accent sur l'avatar sélectionné (dessiné sur le Canvas de la
        carte, au-dessus du liseré standard)."""
        card = self._cells.get(avatar_path)
        if card is None:
            return
        card.delete("selection")
        if avatar_path != self._selected:
            return
        try:
            width = int(card["width"])
            height = int(card["height"])
        except (tk.TclError, ValueError):
            return
        card.create_rectangle(2, 2, width - 2, height - 2, outline=PALETTE["accent"],
                              width=2, tags="selection")

    def _select(self, avatar_path: str) -> None:
        previous, self._selected = self._selected, avatar_path
        if previous:
            self._paint_cell(previous)
        self._paint_cell(avatar_path)

    def _validate(self) -> None:
        chosen = self._selected
        self.destroy()
        if chosen and self._on_choose:
            self._on_choose(chosen)
