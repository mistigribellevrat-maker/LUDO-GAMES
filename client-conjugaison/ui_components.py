# ui_components.py
import math
import random
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk

from theme import FONT_DISPLAY, FONT_BODY, PALETTE, alpha_over, hex_to_rgb, mix, rgb_to_hex

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
        self._beams: list[dict] = []
        self._stars: list[dict] = []
        self._bg_size: tuple[int, int] = (0, 0)
        self._aim = (0.0, 0.0)
        self._destroyed = False
        self._resolved = True  # aucune vague active tant que load_wave() n'a pas été appelée
        self._anim_after = None
        self._result_after_id = None
        self._wave_start = 0.0
        self._highlight_until = 0.0  # fin de l'effet "traqueur" (boutique), 0 = inactif
        self._recoil = 0.0      # recul de la tourelle après un tir (0..1)
        self._shake = 0.0       # amplitude de la secousse d'écran (pixels)
        self._dome_breach = 0.0  # flash rouge du dôme quand un vaisseau passe (0..1)
        self._fx: dict = {}
        self._init_fx()

        self.bind("<Motion>", self._on_motion)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Destroy>", self._on_destroy, add="+")

    # --- effets sonores (synthétisés, aucun asset requis) -----------------

    def _init_fx(self) -> None:
        """Génère les bruits du jeu (laser, explosion, brèche) en mémoire à
        partir du module standard `wave` : aucun fichier à livrer, et une
        absence de pygame/mixer ne fait jamais échouer le jeu (muet alors)."""
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._fx = {
                "laser": self._synth(0.16, 1500, 240, 0.30, decay=1.5),
                "boom": self._synth(0.45, 320, 55, 0.45, decay=2.2),
                "breach": self._synth(0.60, 200, 40, 0.55, decay=2.6),
            }
        except Exception:
            self._fx = {}

    @staticmethod
    def _synth(duration: float, f0: float, f1: float, volume: float, decay: float):
        """Sifflement balayé f0→f1 avec enveloppe décroissante, rendu WAV
        mono 22 kHz via le module standard `wave` — retourne un buffer
        lisible par pygame.mixer.Sound(file=...)."""
        import io
        import math as _math
        import struct
        import wave

        sample_rate = 22050
        n = int(sample_rate * duration)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            frames = bytearray()
            for i in range(n):
                t = i / sample_rate
                progress = t / duration
                freq = f0 + (f1 - f0) * progress
                envelope = (1 - progress) ** decay
                sample = int(32767 * volume * envelope * _math.sin(2 * _math.pi * freq * t))
                frames += struct.pack("<h", sample)
            w.writeframes(bytes(frames))
        buf.seek(0)
        import pygame
        return pygame.mixer.Sound(file=buf)

    def _play(self, name: str) -> None:
        snd = self._fx.get(name)
        if snd is not None:
            try:
                snd.play()
            except Exception:
                pass

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
        # Tir visuel : recul de la tourelle, rayon laser vers le point visé,
        # bruit — même sur un tir dans le vide (pas de pénalité, mais le jeu
        # doit répondre au clic, sinon on croit qu'il est mort).
        self._fire_fx(event.x, event.y)
        if best is None:
            return  # tir dans le vide : pas de pénalité, la vague continue
        self._resolve_ship(best, hit_by_player=True)

    def _fire_fx(self, x: float, y: float) -> None:
        """Effets d'un tir : recul, rayon laser depuis la bouche de la tourelle
        jusqu'au point visé, son."""
        try:
            w, h = self.winfo_width(), self.winfo_height()
        except tk.TclError:
            return
        cx, cy = w / 2, h / 2
        angle = math.atan2(y - cy, x - cx)
        bx, by = cx + math.cos(angle) * 34, cy + math.sin(angle) * 34
        self._beams.append({"x1": bx, "y1": by, "x2": x, "y2": y, "life": 8, "max": 8})
        self._recoil = 1.0
        self._play("laser")
        self._ensure_animating()

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
            # Traînée de réacteur : une étincelle pâle laissée derrière le vaisseau.
            if random.random() < 0.35:
                self._particles.append({
                    "kind": "trail", "x": ship.x - dx / length * 18, "y": ship.y - dy / length * 18,
                    "dx": random.uniform(-0.2, 0.2), "dy": random.uniform(-0.2, 0.2),
                    "life": 14, "max": 14, "color": PALETTE["warning"], "size": random.randint(1, 3),
                })
            moving = True
            if t >= 1.0:
                self._resolve_ship(ship, hit_by_player=False)
        for p in self._particles[:]:
            kind = p.get("kind", "spark")
            if kind in ("spark", "trail"):
                p["dy"] += 0.18 if kind == "spark" else 0.0
                p["x"] += p["dx"]
                p["y"] += p["dy"]
            elif kind == "smoke":
                p["x"] += p["dx"]
                p["y"] += p["dy"]
                p["size"] += 0.35  # la fumée gonfle en s'élevant
            p["life"] -= 1
            if p["life"] <= 0:
                self._particles.remove(p)
            else:
                moving = True
        for beam in self._beams[:]:
            beam["life"] -= 1
            if beam["life"] <= 0:
                self._beams.remove(beam)
            else:
                moving = True
        self._recoil *= 0.82
        if self._recoil < 0.02:
            self._recoil = 0.0
        else:
            moving = True
        self._shake *= 0.88
        if self._shake < 0.1:
            self._shake = 0.0
        else:
            moving = True
        if self._dome_breach > 0:
            self._dome_breach = max(0.0, self._dome_breach - 0.045)
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
        if hit_by_player:
            self._shake = max(self._shake, 2.5)
            self._play("boom")
        else:
            # Un vaisseau a atteint le dôme : flash rouge + secousse forte.
            self._shake = max(self._shake, 6.0)
            self._dome_breach = 1.0
            self._play("breach")
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
        # Onde de choc : anneau qui s'élargit.
        self._particles.append({
            "kind": "ring", "x": x, "y": y, "life": 16, "max": 16,
            "r0": 8, "r1": 62, "color": palette[0], "size": 4,
        })
        # Halo lumineux bref.
        self._particles.append({
            "kind": "glow", "x": x, "y": y, "life": 10, "max": 10,
            "size": 78, "color": palette[0],
        })
        # Étincelles.
        for _ in range(26):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(2, 6.5)
            self._particles.append({
                "kind": "spark", "x": x, "y": y, "dx": speed * math.cos(angle), "dy": speed * math.sin(angle),
                "life": 22, "max": 22, "color": random.choice(palette), "size": random.randint(3, 6),
            })
        # Fumée sombre.
        for _ in range(7):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(0.3, 1.2)
            self._particles.append({
                "kind": "smoke", "x": x, "y": y, "dx": speed * math.cos(angle), "dy": speed * math.sin(angle) - 0.3,
                "life": 24, "max": 24, "color": "#3a4a68", "size": random.randint(5, 9),
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
        now = time.monotonic()
        self.delete("all")
        self._draw_background(w, h, now)
        cx, cy = w / 2, h / 2
        # Secousse d'écran : tout le décor bouge, sauf le réticule (qui doit
        # rester collé à la souris).
        ox = random.uniform(-1, 1) * self._shake
        oy = random.uniform(-1, 1) * self._shake
        self._draw_dome(cx + ox, cy + oy, now)
        for ship in self._ships:
            if ship.alive:
                self._draw_ship(ship, now, ox, oy)
        self._draw_particles(now, ox, oy)
        self._draw_beams(ox, oy)
        self._draw_turret(cx, cy, now, ox, oy)
        self._draw_reticle()

    # --- décor spatial ------------------------------------------------

    def _draw_background(self, w: int, h: int, now: float) -> None:
        """Dégradé vertical + champ d'étoiles scintillantes (régénéré
        seulement quand la taille change)."""
        top, bottom = hex_to_rgb(PALETTE["bg_deep"]), hex_to_rgb(PALETTE["bg_alt"])
        steps = 24
        for i in range(steps):
            t = i / steps
            color = rgb_to_hex(tuple(int(top[c] + (bottom[c] - top[c]) * t) for c in range(3)))
            y0 = h * i / steps
            self.create_rectangle(0, y0, w, h * (i + 1) / steps + 1, fill=color, outline="")
        if self._bg_size != (w, h):
            self._bg_size = (w, h)
            self._stars = [
                {
                    "x": random.uniform(0, w), "y": random.uniform(0, h),
                    "r": random.choice([1, 1, 1, 2]), "phase": random.uniform(0, 2 * math.pi),
                    "speed": random.uniform(1.2, 3.0), "bright": random.choice(
                        ["#9ae8ff", "#eaf7ff", PALETTE["accent_hi"], "#ffffff"]),
                }
                for _ in range(90)
            ]
        for s in self._stars:
            twinkle = 0.5 + 0.5 * math.sin(now * s["speed"] + s["phase"])
            color = mix(PALETTE["faint"], s["bright"], twinkle)
            self.create_oval(s["x"] - s["r"], s["y"] - s["r"], s["x"] + s["r"], s["y"] + s["r"],
                             fill=color, outline="")

    # --- dôme ---------------------------------------------------------

    def _draw_dome(self, cx: float, cy: float, now: float) -> None:
        breach = self._dome_breach
        ring_color = mix(PALETTE["accent"], PALETTE["danger"], breach)
        pulse = 1 + 0.04 * math.sin(now * 2.2)
        r = 46 * pulse
        # Halo d'ambiance sous le dôme.
        self.create_oval(cx - r * 2.0, cy - r * 2.0, cx + r * 2.0, cy + r * 2.0,
                          fill=alpha_over(ring_color, PALETTE["bg"], 0.05), outline="")
        # Anneau principal (plus épais et rouge vif pendant une brèche).
        self.create_oval(cx - r, cy - r, cx + r, cy + r,
                          fill=alpha_over(ring_color, PALETTE["bg"], 0.12 + 0.30 * breach),
                          outline=ring_color, width=3 if breach > 0.05 else 2)
        # Arcs d'énergie qui tournent autour du dôme.
        for i in range(3):
            start = (now * 40 + i * 120) % 360
            self.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=46,
                            style=tk.ARC, outline=alpha_over(PALETTE["accent2"], PALETTE["bg"], 0.9),
                            width=2)
        # Noyau central pulsant.
        core_r = 11 + 2 * math.sin(now * 3)
        self.create_oval(cx - core_r - 5, cy - core_r - 5, cx + core_r + 5, cy + core_r + 5,
                          fill=alpha_over(PALETTE["accent_hi"], PALETTE["bg"], 0.25), outline="")
        self.create_oval(cx - core_r, cy - core_r, cx + core_r, cy + core_r,
                          fill=PALETTE["accent_hi"], outline="")

    # --- tourelle ------------------------------------------------------

    def _draw_turret(self, cx: float, cy: float, now: float, ox: float, oy: float) -> None:
        ax, ay = self._aim
        angle = math.atan2(ay - cy, ax - cx)
        # Socle.
        self.create_oval(cx + ox - 24, cy + oy - 24, cx + ox + 24, cy + oy + 24,
                          fill=alpha_over(PALETTE["panel3"], PALETTE["bg"], 0.9),
                          outline=PALETTE["accent"], width=2)
        self.create_oval(cx + ox - 13, cy + oy - 13, cx + ox + 13, cy + oy + 13,
                          fill=alpha_over(PALETTE["accent"], PALETTE["bg"], 0.35), outline="")
        # Canon : recule légèrement au tir (recoil), avec halo à la bouche.
        barrel_len = 34 - 10 * self._recoil
        bx = cx + ox + math.cos(angle) * barrel_len
        by = cy + oy + math.sin(angle) * barrel_len
        self.create_line(cx + ox, cy + oy, bx, by, fill=alpha_over(PALETTE["accent_hi"], PALETTE["bg"], 0.4),
                         width=8, capstyle=tk.ROUND)
        self.create_line(cx + ox, cy + oy, bx, by, fill=PALETTE["accent_hi"], width=3.5, capstyle=tk.ROUND)
        if self._recoil > 0.45:
            # Flash de bouche : étoile de traits + halo.
            for k in range(3):
                spark_angle = angle + (k - 1) * 0.55
                length = 12 + 6 * self._recoil
                sx = bx + math.cos(spark_angle) * length
                sy = by + math.sin(spark_angle) * length
                self.create_line(bx, by, sx, sy, fill=PALETTE["accent_hi"], width=2, capstyle=tk.ROUND)
            self.create_oval(bx - 9, by - 9, bx + 9, by + 9,
                             fill=alpha_over("#ffffff", PALETTE["bg"], 0.9), outline="")

    def _draw_reticle(self) -> None:
        """Réticule collé à la souris (jamais décalé par la secousse)."""
        ax, ay = self._aim
        r = 16
        self.create_oval(ax - r, ay - r, ax + r, ay + r, outline=PALETTE["accent_hi"], width=2)
        for x0, y0, x1, y1 in (
            (ax - r - 6, ay, ax - r + 4, ay), (ax + r - 4, ay, ax + r + 6, ay),
            (ax, ay - r - 6, ax, ay - r + 4), (ax, ay + r - 4, ax, ay + r + 6),
        ):
            self.create_line(x0, y0, x1, y1, fill=PALETTE["accent_hi"], width=2)

    # --- vaisseaux -----------------------------------------------------

    def _draw_ship(self, ship: ShipSprite, now: float, ox: float, oy: float) -> None:
        x, y = ship.x + ox, ship.y + oy
        color = mix(PALETTE["accent"], PALETTE["danger"], ship.progress)
        fill = alpha_over(color, PALETTE["bg"], 0.9)
        dx, dy = ship.target[0] - ship.x, ship.target[1] - ship.y
        angle = math.atan2(dy, dx)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        # Halo lumineux derrière la coque.
        halo = ship.radius * 1.45
        self.create_oval(x - halo, y - halo, x + halo, y + halo,
                          fill=alpha_over(color, PALETTE["bg"], 0.08), outline="")
        # Réacteur : flamme vacillante à l'arrière.
        flame_len = 11 + 6 * math.sin(now * 26 + ship.wobble_phase)
        rx, ry = x - cos_a * 15, y - sin_a * 15
        fx = rx - cos_a * flame_len
        fy = ry - sin_a * flame_len
        f1 = (rx - cos_a * 2 - sin_a * 6, ry - sin_a * 2 + cos_a * 6)
        f2 = (rx - cos_a * 2 + sin_a * 6, ry - sin_a * 2 - cos_a * 6)
        self.create_polygon(*f1, (fx, fy), *f2, fill=PALETTE["warning"], outline="")
        self.create_polygon(*f1, (rx - cos_a * flame_len * 0.5, ry - sin_a * flame_len * 0.5), *f2,
                            fill="#ffd166", outline="")
        # Coque : cerf-volant profilé (nez, ailes, arrière).
        nose = (x + cos_a * 22, y + sin_a * 22)
        rear = (x - cos_a * 15, y - sin_a * 15)
        wing1 = (x + cos_a * 12 - sin_a * 15, y + sin_a * 12 + cos_a * 15)
        wing2 = (x + cos_a * 12 + sin_a * 15, y + sin_a * 12 - cos_a * 15)
        self.create_polygon(*nose, *wing1, *rear, *wing2, fill=fill, outline=color, width=2)
        # Cabine.
        cockpit = (x + cos_a * 8, y + sin_a * 8)
        self.create_oval(cockpit[0] - 4.5, cockpit[1] - 4.5, cockpit[0] + 4.5, cockpit[1] + 4.5,
                         fill=PALETTE["accent_hi"], outline=alpha_over(color, PALETTE["bg"], 0.6))
        # Plaque du libellé (forme conjuguée) au-dessus du vaisseau.
        label_y = y - ship.radius - 26
        plate_color = mix(PALETTE["bg"], color, 0.30)
        self.create_rectangle(x - 48, label_y - 10, x + 48, label_y + 10,
                              fill=alpha_over(plate_color, PALETTE["bg"], 0.9),
                              outline=alpha_over(color, PALETTE["bg"], 0.45), width=1)
        self.create_text(x, label_y, text=ship.text, fill=PALETTE["text_strong"],
                          font=(FONT_BODY, 11, "bold"))
        # Traqueur (boutique) : anneau pulsant sur le vaisseau correct.
        if ship.is_correct and now < self._highlight_until:
            pulse = (1 + math.sin(now * 6)) / 2
            ring_r = ship.radius + 6 + pulse * 4
            self.create_oval(x - ring_r, y - ring_r, x + ring_r, y + ring_r,
                             outline=PALETTE["accent2"], width=3)

    # --- particules -----------------------------------------------------

    def _draw_particles(self, now: float, ox: float, oy: float) -> None:
        for p in self._particles:
            kind = p.get("kind", "spark")
            x, y = p["x"] + ox, p["y"] + oy
            life_ratio = max(0.0, p["life"] / p["max"]) if p.get("max") else 1.0
            if kind in ("spark", "trail"):
                size = p["size"] * (0.5 + 0.5 * life_ratio)
                self.create_oval(x - size, y - size, x + size, y + size,
                                 fill=p["color"], outline="")
            elif kind == "smoke":
                fade = mix(p["color"], PALETTE["bg"], 1 - life_ratio)
                size = p["size"]
                self.create_oval(x - size, y - size, x + size, y + size,
                                 fill=alpha_over(fade, PALETTE["bg"], 0.55 * life_ratio), outline="")
            elif kind == "ring":
                r = p["r0"] + (p["r1"] - p["r0"]) * (1 - life_ratio)
                self.create_oval(x - r, y - r, x + r, y + r,
                                 outline=alpha_over(p["color"], PALETTE["bg"], life_ratio), width=3)
            elif kind == "glow":
                r = p["size"] * (0.6 + 0.4 * life_ratio)
                self.create_oval(x - r, y - r, x + r, y + r,
                                 fill=alpha_over(p["color"], PALETTE["bg"], 0.18 * life_ratio), outline="")

    def _draw_beams(self, ox: float, oy: float) -> None:
        for beam in self._beams:
            life_ratio = max(0.0, beam["life"] / beam["max"])
            self.create_line(beam["x1"] + ox, beam["y1"] + oy, beam["x2"] + ox, beam["y2"] + oy,
                             fill=alpha_over(PALETTE["accent2"], PALETTE["bg"], 0.5 * life_ratio),
                             width=6, capstyle=tk.ROUND)
            self.create_line(beam["x1"] + ox, beam["y1"] + oy, beam["x2"] + ox, beam["y2"] + oy,
                             fill="#ffffff", width=2, capstyle=tk.ROUND)


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
