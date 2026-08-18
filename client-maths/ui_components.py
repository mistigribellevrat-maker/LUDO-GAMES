# ui_components.py
import threading
import tkinter as tk
from tkinter import ttk

from theme import FONT_DISPLAY, FONT_BODY, PALETTE, alpha_over, mix

from problems import LEVELS, SEGMENTS
from ui_extras import IconBadge

PODIUM_COLORS = {0: "#ffd166", 1: "#c9d6e4", 2: "#cd7f32"}  # or / argent / bronze


class ProtectionGrid(tk.Canvas):
    """Grille de protection circulaire à `segments` cases (façon diaphragme /
    porte blindée). Chaque bonne réponse ferme une case (transition animée
    rouge -> cyan/émeraude, même technique d'interpolation que ShieldMeter
    dans commun/ui_widgets.py). Une mauvaise réponse déclenche un flash rouge ;
    la défaite (3e erreur) fait clignoter les cases encore ouvertes en rouge
    vif ("les aliens franchissent la grille").
    """

    GAP_DEGREES = 3

    def __init__(self, master, segments: int = SEGMENTS, bg=None, **kw):
        bg = bg or PALETTE["bg"]
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, **kw)
        self.segments = segments
        self._closed = 0
        self._states = [0.0] * segments  # 0 = ouverte (rouge), 1 = fermée (cyan/émeraude)
        self._targets = [0.0] * segments
        self._flash = 0.0
        self._breach = False
        self._anim_after = None
        self._destroyed = False
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._redraw()

    def _alive(self) -> bool:
        if self._destroyed:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        self._destroyed = True
        if self._anim_after is not None:
            try:
                self.after_cancel(self._anim_after)
            except Exception:
                pass
            self._anim_after = None

    # --- API publique ------------------------------------------------------

    def close_next_segment(self) -> None:
        """Anime la fermeture de la prochaine case ouverte (une bonne réponse)."""
        if self._closed >= self.segments:
            return
        self._targets[self._closed] = 1.0
        self._closed += 1
        self._ensure_animating()

    def flash_wrong(self) -> None:
        """Flash rouge bref (une mauvaise réponse, sans conséquence sur la grille)."""
        self._flash = 1.0
        self._ensure_animating()

    def trigger_breach(self) -> None:
        """Défaite : les cases encore ouvertes se mettent à clignoter en rouge vif."""
        self._breach = True
        self._flash = 1.0
        self._ensure_animating()

    def reset(self) -> None:
        self._closed = 0
        self._breach = False
        self._states = [0.0] * self.segments
        self._targets = [0.0] * self.segments
        self._flash = 0.0
        self._redraw()

    # --- animation -----------------------------------------------------

    def _ensure_animating(self) -> None:
        if self._anim_after is None and self._alive():
            self._anim_after = self.after(16, self._step)

    def _step(self) -> None:
        self._anim_after = None
        if not self._alive():
            return
        moving = False
        for i in range(self.segments):
            delta = self._targets[i] - self._states[i]
            if abs(delta) > 0.01:
                self._states[i] += delta * 0.25
                moving = True
            else:
                self._states[i] = self._targets[i]
        if self._flash > 0:
            self._flash = max(0.0, self._flash - (0.03 if self._breach else 0.08))
            moving = True
            if self._breach and self._flash <= 0:
                self._flash = 1.0  # clignotement continu tant que la défaite est affichée
        self._redraw()
        if moving:
            self._anim_after = self.after(16, self._step)

    def _redraw(self) -> None:
        if not self._alive():
            return
        self.delete("all")
        try:
            w, h = self.winfo_width(), self.winfo_height()
        except tk.TclError:
            return
        if w <= 2 or h <= 2:
            return
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - 10
        if radius <= 2:
            return
        bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
        step_deg = 360 / self.segments
        for i in range(self.segments):
            start = i * step_deg + self.GAP_DEGREES / 2
            extent = step_deg - self.GAP_DEGREES
            t = self._states[i]
            if self._breach and t < 1.0:
                color = mix(PALETTE["danger"], "#ff9aa8", self._flash)
                alpha = 0.35 + 0.4 * self._flash
            else:
                color = mix(PALETTE["danger"], PALETTE["accent2"], t)
                alpha = 0.25 + 0.55 * t
            fill = alpha_over(color, PALETTE["bg"], alpha)
            self.create_arc(bbox, start=start, extent=extent, style=tk.PIESLICE,
                             fill=fill, outline=color, width=2)
        # Le cœur grossit légèrement à l'approche de la victoire : montée en
        # tension visuelle qui accompagne la montée en intensité numérique
        # (voir MathMission._intensity côté problems.py).
        progress = (self._closed / self.segments) if self.segments else 0.0
        core_r = radius * (0.26 + 0.10 * progress)
        core_color = PALETTE["accent2"] if self._closed >= self.segments else PALETTE["accent"]
        core_fill = alpha_over(core_color, PALETTE["bg"], 0.85)
        self.create_oval(cx - core_r, cy - core_r, cx + core_r, cy + core_r,
                          fill=core_fill, outline=core_color, width=2)
        if self._flash > 0.05 and not self._breach:
            self.create_rectangle(0, 0, w, h, fill=PALETTE["danger"], outline="", stipple="gray25")


class MathHighScoreWindow(tk.Toplevel):
    """Classement des ingénieurs de la grille — variante maths de
    client-dictee/ui_components.py::HighScoreWindow (échelle /SEGMENTS, pas
    /20, et niveaux maths plutôt que rangs "dictée")."""

    def __init__(self, parent, score_service, colors, segments: int = SEGMENTS):
        super().__init__(parent)
        self.title("Ingénieurs de la Grille")
        self.geometry("700x400")
        self.configure(bg=colors['bg'])
        self.transient(parent)
        self.grab_set()

        self.score_service = score_service
        self.segments = segments
        self._closed = False
        self._request_seq = 0
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        header = tk.Frame(self, bg=colors['bg'])
        header.pack(fill=tk.X, padx=16, pady=(14, 4))
        IconBadge(header, "🏆", diameter=40).pack(side=tk.LEFT, padx=(0, 10))
        title_box = tk.Frame(header, bg=colors['bg'])
        title_box.pack(side=tk.LEFT, anchor='w')
        tk.Label(title_box, text="INGÉNIEURS DE LA GRILLE", bg=colors['bg'],
                 fg=colors.get('text_strong', '#f4f9ff'),
                 font=(FONT_DISPLAY, 15, 'bold')).pack(anchor='w')
        tk.Label(title_box, text="Classement des meilleures fermetures de grille", bg=colors['bg'],
                 fg=colors.get('muted', '#86a3c8'), font=(FONT_BODY, 10, 'italic')).pack(anchor='w')

        row = tk.Frame(self, bg=colors['bg'])
        row.pack(fill=tk.X, padx=16, pady=(6, 8))
        tk.Label(row, text="Niveau :", bg=colors['bg'], fg=colors.get('accent', '#00d9ff'),
                 font=(FONT_DISPLAY, 10, 'bold')).pack(side=tk.LEFT, padx=(0, 8))
        self.level_var = tk.StringVar(value=LEVELS[0])
        self.level_menu = ttk.Combobox(row, textvariable=self.level_var,
                                        values=LEVELS, state="readonly")
        self.level_menu.pack(side=tk.LEFT)
        self.level_menu.bind("<<ComboboxSelected>>", self._update_display)

        cols = ("Rang", "Commandant", "Score", "Temps", "Date")
        self.tree = ttk.Treeview(self, columns=cols, show='headings')
        for col in cols:
            self.tree.heading(col, text=col)
        self.tree.column("Rang", width=50, anchor=tk.CENTER)
        self.tree.column("Commandant", width=200, anchor=tk.W)
        self.tree.column("Score", width=80, anchor=tk.CENTER)
        self.tree.column("Temps", width=80, anchor=tk.CENTER)
        self.tree.column("Date", width=100, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._update_display()

    def _on_close(self):
        self._closed = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def _update_display(self, event=None):
        self._request_seq += 1
        seq = self._request_seq
        level = self.level_var.get()

        for i in self.tree.get_children():
            self.tree.delete(i)
        self.tree.insert("", "end", values=("", "Chargement…", "", "", ""))

        def worker():
            try:
                scores = self.score_service.get_scores(level)
                error = None
            except Exception as exc:
                scores = None
                error = exc
            if self._closed:
                return
            try:
                self.after(0, lambda: self._apply_scores(seq, scores, error))
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _apply_scores(self, seq, scores, error):
        if self._closed or seq != self._request_seq:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        for i in self.tree.get_children():
            self.tree.delete(i)

        if error is not None:
            self.tree.insert("", "end", values=("", "Erreur de chargement des scores", "", "", ""))
            return

        for rank, color in PODIUM_COLORS.items():
            self.tree.tag_configure(f"podium{rank}", foreground=color)

        for i, entry in enumerate(scores):
            duration = entry.get("duration")
            if duration is not None:
                minutes, seconds = divmod(int(duration), 60)
                time_str = f"{minutes:02d}:{seconds:02d}"
            else:
                time_str = "--:--"
            tags = (f"podium{i}",) if i in PODIUM_COLORS else ()
            self.tree.insert("", "end", values=(
                f"#{i + 1}", entry["name"], f"{entry['score']}/{self.segments}",
                time_str, entry.get("date", "N/A"),
            ), tags=tags)
