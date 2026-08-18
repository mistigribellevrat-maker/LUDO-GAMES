# ui_components.py
import math
import random
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk

from theme import FONT_DISPLAY, FONT_BODY, PALETTE, alpha_over, mix

from problems import LEVELS, SEGMENTS
from ui_extras import IconBadge

PODIUM_COLORS = {0: "#ffd166", 1: "#c9d6e4", 2: "#cd7f32"}  # or / argent / bronze


@dataclass
class ShipSprite:
    """État d'un vaisseau côté affichage — distinct de `problems.ShipForm`
    (qui ne sait rien des pixels). Position mémorisée ici et testée par
    simple distance au clic : pas de hit-test via les items Canvas
    (`find_overlapping`), plus simple et fiable contre des cibles en
    mouvement (aucun précédent de ce type ailleurs dans le dépôt)."""

    index: int
    text: str
    is_correct: bool
    start: tuple[float, float]
    control: tuple[float, float]
    target: tuple[float, float]
    spawn_delay: float
    flight_time: float
    x: float = 0.0
    y: float = 0.0
    progress: float = 0.0
    alive: bool = True
    radius: float = 34.0
    wobble_phase: float = field(default_factory=lambda: random.uniform(0, 2 * math.pi))
    wobble_amp: float = field(default_factory=lambda: random.uniform(4, 9))

    def __post_init__(self) -> None:
        self.x, self.y = self.start


class TurretScene(tk.Canvas):
    """Zone de combat : des vaisseaux volent en courbe depuis le bord de
    l'écran vers un dôme central, chacun affichant une forme conjuguée. Le
    joueur vise à la souris (réticule qui suit le curseur, tourelle qui
    pivote) et clique pour tirer sur le vaisseau portant la bonne forme
    avant qu'un vaisseau n'atteigne le dôme.

    Boucle d'animation à la demande (même motif que
    client-maths/ui_components.py::ProtectionGrid) : ne tourne que tant que
    des vaisseaux sont en vol ou qu'une explosion est en cours. Garde-fou de
    cycle de vie identique (`_alive()`, `<Destroy>`, `after_cancel`)."""

    TICK_MS = 16
    SHIP_RADIUS = 34
    SPAWN_STAGGER_MS = 400
    RESULT_DELAY_MS = 350

    def __init__(self, master, on_result=None, flight_time: float = 8.0, bg=None, **kw):
        bg = bg or PALETTE["bg"]
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, cursor="none", **kw)
        self._on_result = on_result
        self._flight_time = flight_time
        self._ships: list[ShipSprite] = []
        self._particles: list[dict] = []
        self._aim = (0.0, 0.0)
        self._destroyed = False
        self._resolved = True  # aucune vague active tant que load_wave() n'a pas été appelée
        self._anim_after = None
        self._result_after_id = None
        self._wave_start = 0.0
        self._highlight_until = 0.0  # fin de l'effet "traqueur" (boutique), 0 = inactif

        self.bind("<Motion>", self._on_motion)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Destroy>", self._on_destroy, add="+")

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
        self._cancel_pending_after()

    def _cancel_pending_after(self) -> None:
        for attr in ("_anim_after", "_result_after_id"):
            after_id = getattr(self, attr)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attr, None)

    # --- API publique ----------------------------------------------------

    def set_flight_time(self, seconds: float) -> None:
        self._flight_time = seconds

    def highlight_correct(self, seconds: float = 3.0) -> None:
        """Traqueur (boutique) : le vaisseau correct est entouré d'un anneau
        pulsant pendant `seconds` à partir de maintenant."""
        self._highlight_until = time.monotonic() + seconds

    def slow_ships(self, extra_seconds: float = 2.0) -> None:
        """Propulsion ralentie (boutique) : rallonge le temps de vol des
        vaisseaux encore en vol dans la vague courante."""
        for ship in self._ships:
            if ship.alive:
                ship.flight_time += extra_seconds

    def load_wave(self, wave) -> None:
        """Démarre une nouvelle vague à partir d'un `problems.Wave`."""
        # Sur la toute première vague d'une mission, ce canvas vient d'être
        # empaqueté et Tk n'a pas encore calculé sa vraie taille (winfo_width/
        # height renverraient 1) : update_idletasks() force cette passe de
        # géométrie immédiatement, sans attendre un tour de boucle événements.
        # Sans ça, la cible visée est un point fantôme (5,5) au lieu du centre
        # réel du dôme — bug constaté en jeu.
        self.update_idletasks()
        w = max(self.winfo_width(), 10)
        h = max(self.winfo_height(), 10)
        cx, cy = w / 2, h / 2
        self._ships = [
            self._make_sprite(i, ship_form, (cx, cy), spawn)
            for i, (ship_form, spawn) in enumerate(zip(wave.ships, self._edge_points(w, h, len(wave.ships))))
        ]
        self._particles = []
        self._resolved = False
        self._wave_start = time.monotonic()
        # Le traqueur (boutique) ne s'applique qu'à la vague cliquée : un
        # effet qui subsisterait sur la vague suivante révélerait la bonne
        # réponse sans que le joueur l'ait acheté pour elle.
        self._highlight_until = 0.0
        self._ensure_animating()
        self._redraw()

    def stop(self) -> None:
        self._ships = []
        self._particles = []
        self._resolved = True
        self._cancel_pending_after()

    def _make_sprite(self, index, ship_form, target, start) -> ShipSprite:
        cx, cy = target
        sx, sy = start
        mx, my = (sx + cx) / 2, (sy + cy) / 2
        dx, dy = cx - sx, cy - sy
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        offset = random.uniform(-90, 90)
        control = (mx + nx * offset, my + ny * offset)
        return ShipSprite(
            index=index, text=ship_form.text, is_correct=ship_form.is_correct,
            start=start, control=control, target=target,
            spawn_delay=random.uniform(0, self.SPAWN_STAGGER_MS) / 1000.0,
            flight_time=self._flight_time, radius=self.SHIP_RADIUS,
        )

    @staticmethod
    def _edge_points(w: float, h: float, n: int) -> list[tuple[float, float]]:
        edges = ["top", "bottom", "left", "right"]
        random.shuffle(edges)
        points = []
        for i in range(n):
            edge = edges[i % 4]
            if edge == "top":
                p = (random.uniform(0.1, 0.9) * w, -40)
            elif edge == "bottom":
                p = (random.uniform(0.1, 0.9) * w, h + 40)
            elif edge == "left":
                p = (-40, random.uniform(0.1, 0.9) * h)
            else:
                p = (w + 40, random.uniform(0.1, 0.9) * h)
            points.append(p)
        return points

    # --- visée -------------------------------------------------------------

    def _on_motion(self, event) -> None:
        self._aim = (event.x, event.y)
        self._redraw()

    def _on_click(self, event) -> None:
        if self._resolved or not self._ships:
            return
        best, best_d = None, None
        for ship in self._ships:
            if not ship.alive:
                continue
            d = math.hypot(event.x - ship.x, event.y - ship.y)
            if d <= ship.radius and (best_d is None or d < best_d):
                best, best_d = ship, d
        if best is None:
            return  # tir dans le vide : pas de pénalité, la vague continue
        self._resolve_ship(best, hit_by_player=True)

    # --- boucle d'animation --------------------------------------------

    def _ensure_animating(self) -> None:
        if self._anim_after is None and self._alive():
            self._anim_after = self.after(self.TICK_MS, self._step)

    def _step(self) -> None:
        self._anim_after = None
        if not self._alive():
            return
        now = time.monotonic()
        moving = False
        for ship in self._ships:
            if not ship.alive:
                continue
            elapsed = now - self._wave_start - ship.spawn_delay
            if elapsed < 0:
                moving = True
                continue
            t = min(1.0, elapsed / ship.flight_time)
            ship.progress = t
            eased = t ** 1.6
            bx, by = self._bezier(ship.start, ship.control, ship.target, eased)
            dx, dy = ship.target[0] - ship.start[0], ship.target[1] - ship.start[1]
            length = math.hypot(dx, dy) or 1.0
            wobble = math.sin(t * 4 * math.pi + ship.wobble_phase) * ship.wobble_amp * (1 - t)
            ship.x = bx + (-dy / length) * wobble
            ship.y = by + (dx / length) * wobble
            moving = True
            if t >= 1.0:
                self._resolve_ship(ship, hit_by_player=False)
        for p in self._particles[:]:
            p["dy"] += 0.2
            p["x"] += p["dx"]
            p["y"] += p["dy"]
            p["life"] -= 1
            if p["life"] <= 0:
                self._particles.remove(p)
            else:
                moving = True
        self._redraw()
        if moving:
            self._anim_after = self.after(self.TICK_MS, self._step)

    @staticmethod
    def _bezier(p0, p1, p2, t: float) -> tuple[float, float]:
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        return x, y

    # --- résolution d'une vague ------------------------------------------

    def _resolve_ship(self, ship: ShipSprite, hit_by_player: bool) -> None:
        if self._resolved:
            return
        self._resolved = True
        ship.alive = False
        success = bool(hit_by_player and ship.is_correct)
        self._spawn_explosion(ship.x, ship.y, success)
        for other in self._ships:
            if other is not ship:
                other.alive = False
        if self._on_result:
            self._result_after_id = self.after(self.RESULT_DELAY_MS, lambda: self._fire_result(success))

    def _fire_result(self, success: bool) -> None:
        self._result_after_id = None
        if self._on_result:
            self._on_result(success)

    def _spawn_explosion(self, x: float, y: float, success: bool) -> None:
        palette = (PALETTE["accent2"], PALETTE["accent_hi"]) if success else (PALETTE["danger"], PALETTE["danger_hi"])
        for _ in range(28):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(2, 6)
            self._particles.append({
                "x": x, "y": y, "dx": speed * math.cos(angle), "dy": speed * math.sin(angle),
                "life": 24, "color": random.choice(palette), "size": random.randint(3, 6),
            })
        self._ensure_animating()

    # --- rendu -------------------------------------------------------------

    def _redraw(self) -> None:
        if not self._alive():
            return
        try:
            w, h = self.winfo_width(), self.winfo_height()
        except tk.TclError:
            return
        if w <= 2 or h <= 2:
            return
        self.delete("all")
        cx, cy = w / 2, h / 2
        self._draw_dome(cx, cy)
        for ship in self._ships:
            if ship.alive:
                self._draw_ship(ship)
        for p in self._particles:
            self.create_oval(p["x"] - p["size"], p["y"] - p["size"],
                              p["x"] + p["size"], p["y"] + p["size"], fill=p["color"], outline="")
        self._draw_turret(cx, cy)

    def _draw_dome(self, cx: float, cy: float) -> None:
        r = 46
        self.create_oval(cx - r, cy - r, cx + r, cy + r,
                          fill=alpha_over(PALETTE["accent"], PALETTE["bg"], 0.14),
                          outline=PALETTE["accent"], width=2)
        self.create_oval(cx - 10, cy - 10, cx + 10, cy + 10, fill=PALETTE["accent_hi"], outline="")

    def _draw_turret(self, cx: float, cy: float) -> None:
        ax, ay = self._aim
        angle = math.atan2(ay - cy, ax - cx)
        bx, by = cx + math.cos(angle) * 30, cy + math.sin(angle) * 30
        self.create_line(cx, cy, bx, by, fill=PALETTE["accent_hi"], width=4, capstyle=tk.ROUND)
        r = 16
        self.create_oval(ax - r, ay - r, ax + r, ay + r, outline=PALETTE["accent_hi"], width=2)
        for x0, y0, x1, y1 in (
            (ax - r - 6, ay, ax - r + 4, ay), (ax + r - 4, ay, ax + r + 6, ay),
            (ax, ay - r - 6, ax, ay - r + 4), (ax, ay + r - 4, ax, ay + r + 6),
        ):
            self.create_line(x0, y0, x1, y1, fill=PALETTE["accent_hi"], width=2)

    def _draw_ship(self, ship: ShipSprite) -> None:
        color = mix(PALETTE["accent"], PALETTE["danger"], ship.progress)
        fill = alpha_over(color, PALETTE["bg"], 0.85)
        dx, dy = ship.target[0] - ship.x, ship.target[1] - ship.y
        angle = math.atan2(dy, dx)
        size = 20
        p1 = (ship.x + math.cos(angle) * size, ship.y + math.sin(angle) * size)
        p2 = (ship.x + math.cos(angle + 2.5) * size * 0.7, ship.y + math.sin(angle + 2.5) * size * 0.7)
        p3 = (ship.x + math.cos(angle - 2.5) * size * 0.7, ship.y + math.sin(angle - 2.5) * size * 0.7)
        self.create_polygon(*p1, *p2, *p3, fill=fill, outline=color, width=2)
        self.create_text(ship.x, ship.y - size - 12, text=ship.text, fill=PALETTE["text_strong"],
                          font=(FONT_BODY, 11, "bold"))
        if ship.is_correct and time.monotonic() < self._highlight_until:
            pulse = (1 + math.sin(time.monotonic() * 6)) / 2
            ring_r = ship.radius + 6 + pulse * 4
            self.create_oval(ship.x - ring_r, ship.y - ring_r, ship.x + ring_r, ship.y + ring_r,
                             outline=PALETTE["accent2"], width=3)


class ConjugationHighScoreWindow(tk.Toplevel):
    """Classement des défenseurs du secteur — variante conjugaison de
    client-maths/ui_components.py::MathHighScoreWindow (même mécanique,
    libellés adaptés)."""

    def __init__(self, parent, score_service, colors, segments: int = SEGMENTS):
        super().__init__(parent)
        self.title("Défenseurs du Secteur")
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
        tk.Label(title_box, text="DÉFENSEURS DU SECTEUR", bg=colors['bg'],
                 fg=colors.get('text_strong', '#f4f9ff'),
                 font=(FONT_DISPLAY, 15, 'bold')).pack(anchor='w')
        tk.Label(title_box, text="Classement des meilleures défenses", bg=colors['bg'],
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
