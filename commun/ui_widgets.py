# ui_widgets.py
#
# Composants « chrome personnalisé » : ils remplacent les widgets Tk/ttk par défaut
# (rectangles plats, reliefs système) par des surfaces dessinées sur Canvas — coins
# arrondis, architecture « double-bezel », survols interpolés, états pressés.
#
# Contenu :
#   - rounded_rect()      -> utilitaire de tracé de rectangle arrondi
#   - NeonButton          -> bouton pilule (variantes primary / solid / ghost / danger / help)
#   - RoundedFrame        -> carte double-bezel hébergeant des widgets enfants
#   - SectionHeader       -> en-tête de section (eyebrow + titre)
#   - SegmentedControl    -> sélecteur segmenté (niveau de menace)
#   - ShieldMeter         -> jauge de bouclier animée à segments arrondis
#
# Tous les composants se protègent contre la destruction du Canvas (winfo_exists +
# try/except TclError) afin qu'aucun callback différé ne touche un widget détruit.

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, Optional

from theme import (
    PALETTE, FONT_DISPLAY,
    RADIUS_LG, RADIUS_MD, RADIUS_SM,
    alpha_over,
)


# ---------------------------------------------------------------------------
# Tracé
# ---------------------------------------------------------------------------

def rounded_rect(canvas: tk.Canvas, x0, y0, x1, y1, r, **kw) -> int:
    """Dessine un rectangle aux coins arrondis (technique polygon lissé).

    Retourne l'identifiant de l'item Canvas créé.
    """
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ---------------------------------------------------------------------------
# Bouton pilule
# ---------------------------------------------------------------------------

class NeonButton(tk.Canvas):
    """Bouton arrondi dessiné sur Canvas, avec états normal / survol / pressé /
    désactivé. Le survol est interpolé (pas un basculement brutal).

    Usage compatible avec ttk.Button pour les appels existants :
        btn = NeonButton(parent, text="LANCER", command=cb, variant="primary")
        btn.pack(...)
        btn.config(state=tk.DISABLED)   # intercepté
        btn.config(command=cb2)         # intercepté
    """

    VARIANTS = {
        #        fill_alpha   border         text            hover_border  hover_text
        "primary": dict(a=0.12, border="accent",     text="accent_hi", hover_border="accent_hi", hover_text="text_strong"),
        "solid":   dict(a=0.90, border="accent_hi",  text="bg",        hover_border="accent_hi", hover_text="bg"),
        "ghost":   dict(a=0.00, border="border_hi",  text="muted",     hover_border="accent",     hover_text="text_strong"),
        "danger":  dict(a=0.10, border="danger",     text="danger_hi", hover_border="danger_hi",  hover_text="text_strong"),
        "help":    dict(a=0.00, border="border_hi",  text="muted",     hover_border="accent",     hover_text="accent_hi"),
    }

    def __init__(
        self,
        master,
        text: str = "",
        command: Optional[Callable] = None,
        variant: str = "primary",
        height: int = 40,
        font=None,
        padx: int = 24,
        bg: Optional[str] = None,
        min_width: int = 0,
        **kw,
    ):
        self._text = text
        self._command = command
        self._variant = variant if variant in self.VARIANTS else "ghost"
        self._state = tk.NORMAL
        self._hover = 0.0
        self._hover_target = 0.0
        self._pressed = False
        self._padx = padx
        self._bg = bg or PALETTE["bg"]
        self._font = font or (FONT_DISPLAY, 11, "bold")
        self._hover_after_id: Optional[str] = None

        mf = tkfont.Font(font=self._font)
        width = max(min_width, mf.measure(text) + 2 * padx)
        super().__init__(
            master, width=width, height=height, bg=self._bg,
            highlightthickness=0, bd=0, cursor="hand2", **kw,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    # --- états & couleurs ------------------------------------------------

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _resolve(self):
        spec = self.VARIANTS[self._variant]
        disabled = self._state == tk.DISABLED

        a = spec["a"]
        if disabled:
            a = 0.0
        elif self._pressed:
            a = max(0.0, a - 0.07)
        else:
            a = min(1.0, a + 0.10 * self._hover)

        if disabled:
            fill = self._bg
            border = PALETTE["border"]
            text = PALETTE["faint"]
        else:
            fill = alpha_over(PALETTE["accent"], self._bg, a) if a > 0 else self._bg
            if self._pressed:
                border = PALETTE[spec.get("hover_border", "accent")]
                text = PALETTE[spec["hover_text"]]
            elif self._hover > 0.5:
                border = PALETTE[spec.get("hover_border", "accent")]
                text = PALETTE[spec["hover_text"]]
            else:
                border = PALETTE[spec["border"]]
                text = PALETTE[spec["text"]]
        return fill, border, text

    def _redraw(self):
        if not self._alive():
            return
        self.delete("all")
        try:
            w = self.winfo_width()
            h = self.winfo_height()
        except tk.TclError:
            return
        if w <= 2 or h <= 2:
            return
        fill, border, text = self._resolve()
        r = min(RADIUS_MD, h // 2 - 2)
        rounded_rect(self, 1, 1, w - 1, h - 1, r, fill=fill, outline=border, width=1)
        if self._state != tk.DISABLED and self._variant != "solid":
            hi = alpha_over("#ffffff", fill, 0.06)
            self.create_line(3, 3, w - 3, 3, fill=hi)
        self.create_text(w / 2, h / 2, text=self._text, fill=text, font=self._font)

    # --- interactions -----------------------------------------------------

    def _on_enter(self, _=None):
        if self._state == tk.DISABLED:
            return
        self._animate_hover(1.0)

    def _on_leave(self, _=None):
        self._pressed = False
        self._animate_hover(0.0)

    def _on_press(self, _=None):
        if self._state == tk.DISABLED:
            return
        self._pressed = True
        self._redraw()

    def _on_release(self, _=None):
        was_pressed = self._pressed
        self._pressed = False
        self._redraw()
        if was_pressed and self._state == tk.DISABLED:
            return
        if was_pressed and self._command is not None:
            self._command()

    def _animate_hover(self, target: float):
        if not self._alive():
            return
        self._hover_target = target
        if self._hover_after_id is not None:
            try:
                self.after_cancel(self._hover_after_id)
            except Exception:
                pass
            self._hover_after_id = None

        def step():
            if not self._alive():
                return
            delta = self._hover_target - self._hover
            self._hover += delta * 0.4
            if abs(self._hover - self._hover_target) < 0.02:
                self._hover = self._hover_target
                self._redraw()
                self._hover_after_id = None
                return
            self._redraw()
            try:
                self._hover_after_id = self.after(16, step)
            except tk.TclError:
                pass

        try:
            self._hover_after_id = self.after(16, step)
        except tk.TclError:
            pass

    # --- API compatible ttk ----------------------------------------------

    def config(self, **kw):
        for k, v in kw.items():
            if k == "state":
                self._state = v
            elif k == "text":
                self._text = v
                mf = tkfont.Font(font=self._font)
                self.configure(width=max(1, mf.measure(v) + 2 * self._padx))
            elif k == "command":
                self._command = v
            else:
                super().config(**{k: v})
        self._redraw()
        return None

    configure = config

    def set_state(self, state):
        self._state = state
        self._redraw()

    def set_text(self, text):
        self.config(text=text)


# ---------------------------------------------------------------------------
# Carte « double-bezel »
# ---------------------------------------------------------------------------

class RoundedFrame(tk.Canvas):
    """Carte à coins arrondis structurée en deux couches (coque externe `panel`
    + cœur interne `panel2`), donnant un relief « matériel usiné » aux panneaux.

    Les widgets enfants se placent dans `.inner` (un tk.Frame), pas dans le Canvas.
    """

    def __init__(self, master, padding: int = 16, radius: int = RADIUS_LG, bg=None, inner_bg=None, **kw):
        self._padding = padding
        self._radius = radius
        bg = bg or PALETTE["bg"]
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, **kw)
        self.inner = tk.Frame(self, bg=(inner_bg or PALETTE["panel2"]))
        self._win = self.create_window(padding, padding, anchor="nw", window=self.inner)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        w, h = event.width, event.height
        if w <= 2 or h <= 2:
            return
        try:
            self.delete("bezel")
            rounded_rect(self, 1, 1, w - 1, h - 1, self._radius,
                         fill=PALETTE["panel"], outline=PALETTE["border"], width=1, tags="bezel")
            hi = alpha_over("#ffffff", PALETTE["panel"], 0.05)
            rounded_rect(self, 2, 2, w - 2, 3 + self._radius, max(2, self._radius - 2),
                         fill=hi, outline="", tags="bezel")
            inner_w = max(1, w - 2 * self._padding)
            inner_h = max(1, h - 2 * self._padding)
            self.itemconfig(self._win, width=inner_w, height=inner_h)
        except tk.TclError:
            pass

    def fit_height(self, extra: int = 0):
        """Ajuste la hauteur du Canvas au contenu de `.inner` (utile pour les
        cartes dont la hauteur est pilotée par leur contenu, pas par l'expansion)."""
        try:
            self.update_idletasks()
            req = self.inner.winfo_reqheight()
            self.configure(height=max(req, 1) + 2 * self._padding + extra)
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# En-tête de section
# ---------------------------------------------------------------------------

class SectionHeader(tk.Frame):
    """En-tête composé d'un « eyebrow » (micro libellé accentué, majuscules espacées)
    et d'un titre, posé sur le fond du panneau (`panel2`)."""

    def __init__(self, master, eyebrow: str, title: str, bg=None, **kw):
        bg = bg or PALETTE["panel2"]
        super().__init__(master, bg=bg, **kw)
        self._eyebrow = tk.Label(
            self, text=eyebrow.upper(), bg=bg, fg=PALETTE["accent"],
            font=(FONT_DISPLAY, 9, "bold"),
        )
        self._eyebrow.pack(anchor="w")
        self._title = tk.Label(
            self, text=title, bg=bg, fg=PALETTE["text_strong"],
            font=(FONT_DISPLAY, 13, "bold"),
        )
        self._title.pack(anchor="w", pady=(1, 0))

    def set_title(self, text):
        self._title.config(text=text)


# ---------------------------------------------------------------------------
# Sélecteur segmenté (niveau de menace)
# ---------------------------------------------------------------------------

class SegmentedControl(tk.Canvas):
    """Rangée de segments arrondis : un seul segment actif à la fois. Écrit la valeur
    choisie dans un tk.StringVar (compatible avec l'existant `level_var.get()`)."""

    def __init__(self, master, options, variable, bg=None, height=34, font=None, **kw):
        bg = bg or PALETTE["bg"]
        self._seg_options = list(options)
        self._variable = variable
        self._height = height
        self._font = font or (FONT_DISPLAY, 10, "bold")
        self._padx = 16
        self._gap = 6

        mf = tkfont.Font(font=self._font)
        seg_widths = [mf.measure(o) + 2 * self._padx for o in self._seg_options]
        total = sum(seg_widths) + self._gap * (len(seg_widths) - 1)
        super().__init__(master, width=total, height=height, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2", **kw)
        self._seg_widths = seg_widths
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _segment_rect(self, i):
        x0 = sum(self._seg_widths[:i]) + self._gap * i
        x1 = x0 + self._seg_widths[i]
        return x0, 1, x1, self._height - 1

    def _redraw(self):
        if not self._alive():
            return
        self.delete("all")
        active = self._variable.get()
        for i, opt in enumerate(self._seg_options):
            x0, y0, x1, y1 = self._segment_rect(i)
            r = min(RADIUS_SM, (y1 - y0) / 2)
            if opt == active:
                fill = alpha_over(PALETTE["accent"], PALETTE["bg"], 0.16)
                border = PALETTE["accent"]
                text = PALETTE["accent_hi"]
            else:
                fill = PALETTE["panel2"]
                border = PALETTE["border"]
                text = PALETTE["muted"]
            rounded_rect(self, x0, y0, x1, y1, r, fill=fill, outline=border, width=1)
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=opt, fill=text, font=self._font)

    def _on_click(self, event):
        x = event.x
        acc = 0
        for i, w in enumerate(self._seg_widths):
            if acc <= x <= acc + w:
                self._variable.set(self._seg_options[i])
                self._redraw()
                return
            acc += w + self._gap

    def set(self, value):
        if value in self._seg_options:
            self._variable.set(value)
            self._redraw()


# ---------------------------------------------------------------------------
# Jauge de bouclier
# ---------------------------------------------------------------------------

class ShieldMeter(tk.Canvas):
    """Jauge segmentée à segments arrondis, avec remplissage animé et halo sur les
    segments pleins. La couleur évolue (émeraude -> ambre -> rouge) avec le niveau."""

    SEGMENTS = 14
    GAP = 4

    def __init__(self, master, height=26, bg=None, **kw):
        bg = bg or PALETTE["panel2"]
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0, **kw)
        self._percent = 100
        self._shown = 100
        self._anim_after_id = None
        self.bind("<Configure>", lambda e: self._redraw())

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _color_for(self, percent: int) -> str:
        if percent > 60:
            return PALETTE["accent2"]
        if percent > 25:
            return PALETTE["warning"]
        return PALETTE["danger"]

    def set_value(self, percent: int):
        self._percent = max(0, min(100, int(percent)))
        if not self._alive():
            return
        if self._anim_after_id is not None:
            try:
                self.after_cancel(self._anim_after_id)
            except Exception:
                pass
            self._anim_after_id = None

        def step():
            if not self._alive():
                return
            delta = self._percent - self._shown
            self._shown += delta * 0.35
            if abs(self._percent - self._shown) < 0.6:
                self._shown = self._percent
                self._redraw()
                self._anim_after_id = None
                return
            self._redraw()
            try:
                self._anim_after_id = self.after(16, step)
            except tk.TclError:
                pass

        try:
            self._anim_after_id = self.after(16, step)
        except tk.TclError:
            pass

    def _redraw(self):
        if not self._alive():
            return
        self.delete("all")
        try:
            w = self.winfo_width()
            h = self.winfo_height()
        except tk.TclError:
            return
        if w <= 2 or h <= 2:
            return
        n = self.SEGMENTS
        seg_w = (w - (n + 1) * self.GAP) / n
        filled = int(n * self._shown / 100)
        color = self._color_for(self._shown)
        for i in range(n):
            x0 = self.GAP + i * (seg_w + self.GAP)
            x1 = x0 + seg_w
            y0, y1 = 3, h - 3
            r = min(RADIUS_SM, (y1 - y0) / 2)
            if i < filled:
                rounded_rect(self, x0, y0, x1, y1, r, fill=color, outline="")
            else:
                rounded_rect(self, x0, y0, x1, y1, r, fill=PALETTE["panel"], outline="")
