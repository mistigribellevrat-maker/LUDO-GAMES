# ui_extras.py
"""Petits éléments visuels propres à client-conjugaison (badges, puces de
stats, fond animé), pour donner à l'écran un aspect « jeu » plutôt que
« formulaire ».

Reprend des motifs déjà éprouvés ailleurs dans le dépôt (badges/puces du Hub,
étoiles de client-dictee::CityManager, et cette même classe déjà dupliquée
dans client-maths/ui_extras.py) mais réimplémentés localement : ce fichier
n'importe rien de client-hub/client-dictee/client-maths, seulement les
primitives partagées de commun/theme.py et commun/ui_widgets.py.
"""

import random
import tkinter as tk

from theme import PALETTE, FONT_DISPLAY, FONT_BODY, RADIUS_SM, hex_to_rgb, rgb_to_hex
from ui_widgets import rounded_rect

LEVEL_ICONS = {
    "CE1": "📖",
    "CE2": "🔤",
    "CM1": "🕰",
    "CM2": "🚀",
    "Collège": "🎓",
}


class IconBadge(tk.Canvas):
    """Pastille circulaire (glow + pictogramme), motif repris du Hub
    (`client-hub/main.py::_icon_badge`). `.set_icon()` permet de la mettre à
    jour en place (ex. changement de niveau) sans reconstruire le widget."""

    def __init__(self, master, icon: str, diameter: int = 52, ring_color: str = None, **kw):
        super().__init__(master, width=diameter, height=diameter, bg=PALETTE["panel2"],
                          highlightthickness=0, **kw)
        self._diameter = diameter
        self.set_icon(icon, ring_color)

    def set_icon(self, icon: str, ring_color: str = None) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        d = self._diameter
        ring_color = ring_color or PALETTE["accent"]
        self.create_oval(2, 2, d - 2, d - 2, fill=PALETTE["accent_glow"],
                          outline=ring_color, width=1.5)
        self.create_text(d / 2, d / 2, text=icon, font=(FONT_DISPLAY, int(d * 0.42)))


class StatChip(tk.Canvas):
    """Puce arrondie « LABEL / valeur », motif repris du Hub
    (`_make_stat_chip`/`_redraw_stat_chip`), pour remplacer une ligne de texte
    plate par quelque chose qui ressemble à un HUD. `.update(value)` redessine
    en place."""

    def __init__(self, master, label: str, value, width: int = 132, height: int = 34, **kw):
        super().__init__(master, width=width, height=height, bg=PALETTE["panel2"],
                          highlightthickness=0, **kw)
        self._label = label
        self.update(value)

    def update(self, value) -> None:
        if not self.winfo_exists():
            return
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        rounded_rect(self, 1, 1, w - 1, h - 1, RADIUS_SM, fill=PALETTE["panel"],
                     outline=PALETTE["border"], width=1)
        self.create_text(12, h / 2, anchor="w", text=self._label, fill=PALETTE["muted"],
                          font=(FONT_BODY, 8, "bold"))
        self.create_text(w - 12, h / 2, anchor="e", text=str(value), fill=PALETTE["accent_hi"],
                          font=(FONT_DISPLAY, 13, "bold"))


class CommandBackdrop(tk.Canvas):
    """Fond animé (dégradé + étoiles scintillantes) utilisé comme conteneur
    racine des écrans à la place d'un tk.Frame uni — un Canvas peut être
    master de `pack()` exactement comme un Frame, donc les écrans continuent
    d'empaqueter leurs enfants sans rien changer. Version très allégée de la
    technique de `client-dictee/ui_components.py::CityManager` (juste
    l'ambiance : ni ville, ni vaisseau, ni particules), avec le même garde-fou
    de cycle de vie (`winfo_exists()` + `<Destroy>` + `after_cancel`) que
    `ProtectionGrid` et `CityManager` utilisent déjà dans ce dépôt."""

    STAR_COUNT = 90
    TWINKLE_MS = 220

    def __init__(self, master, bg: str = None, **kw):
        bg = bg or PALETTE["bg"]
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, **kw)
        self._stars: list[dict] = []
        self._destroyed = False
        self._resize_after_id: str | None = None
        self._twinkle_after_id: str | None = None
        self.bind("<Configure>", self._on_resize)
        self.bind("<Destroy>", self._on_destroy, add="+")
        # Premier dessin différé : à la construction, winfo_width()/height() ne
        # reflètent pas encore la taille réelle du widget.
        self.after(10, self._rebuild)

    def _alive(self) -> bool:
        if self._destroyed:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _on_destroy(self, event) -> None:
        if event.widget is not self:
            return
        self._destroyed = True
        for after_id in (self._resize_after_id, self._twinkle_after_id):
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
        self._resize_after_id = None
        self._twinkle_after_id = None

    def _on_resize(self, _event) -> None:
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        self._resize_after_id = self.after(120, self._rebuild)

    def _rebuild(self) -> None:
        self._resize_after_id = None
        if not self._alive():
            return
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        self.delete("all")
        self._draw_gradient(w, h)
        self._stars = [self._make_star(w, h) for _ in range(self.STAR_COUNT)]
        if self._twinkle_after_id is None:
            self._twinkle()

    def _draw_gradient(self, w: int, h: int) -> None:
        top, bottom = hex_to_rgb(PALETTE["bg_deep"]), hex_to_rgb(PALETTE["bg_alt"])
        steps = 40
        for i in range(steps):
            t = i / steps
            color = rgb_to_hex(tuple(int(top[c] + (bottom[c] - top[c]) * t) for c in range(3)))
            y0 = h * i / steps
            y1 = h * (i + 1) / steps + 1
            self.create_rectangle(0, y0, w, y1, fill=color, outline="")

    def _make_star(self, w: int, h: int) -> dict:
        x, y = random.uniform(0, w), random.uniform(0, h)
        size = random.choice([1, 1, 2])
        dim = PALETTE["faint"]
        bright = random.choice(["#9ae8ff", "#eaf7ff", PALETTE["accent_hi"]])
        star_id = self.create_oval(x, y, x + size, y + size, fill=dim, outline="")
        return {"id": star_id, "dim": dim, "bright": bright, "lit": False}

    def _twinkle(self) -> None:
        if not self._alive():
            self._twinkle_after_id = None
            return
        sample_size = max(1, len(self._stars) // 8)
        for star in random.sample(self._stars, k=sample_size) if self._stars else []:
            star["lit"] = not star["lit"]
            try:
                self.itemconfig(star["id"], fill=star["bright"] if star["lit"] else star["dim"])
            except tk.TclError:
                pass
        try:
            self._twinkle_after_id = self.after(self.TWINKLE_MS, self._twinkle)
        except tk.TclError:
            self._twinkle_after_id = None
