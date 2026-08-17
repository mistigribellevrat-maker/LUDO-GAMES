# ui_components.py

# NOUVEAU : Imports Tkinter requis pour les widgets
import tkinter as tk
from tkinter import ttk

import random
import math
import threading
from datetime import datetime

from theme import FONT_DISPLAY, FONT_BODY

class CityManager:
    def __init__(self, canvas, num_buildings=20):
        self.canvas = canvas
        self.num_buildings = num_buildings
        self.buildings = []
        self.particles = []
        self.canvas_width = self.canvas.winfo_width()
        self.canvas_height = self.canvas.winfo_height()
        self.ground_level = self.canvas_height - 20
        self.stars = []
        self._resize_after_id = None
        self._destroyed = False
        self._create_scene()
        self._animate_scene()
        # Rendre la scène responsive aux changements de taille
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Destroy>", self._on_canvas_destroy, add="+")

    def _canvas_alive(self):
        """True si le canvas existe encore et peut être manipulé sans risque."""
        if self._destroyed:
            return False
        try:
            return bool(self.canvas.winfo_exists())
        except tk.TclError:
            return False

    def _on_canvas_destroy(self, event):
        if event.widget is not self.canvas:
            return
        self._destroyed = True
        if self._resize_after_id is not None:
            try:
                self.canvas.after_cancel(self._resize_after_id)
            except Exception:
                pass
            self._resize_after_id = None

    def _create_scene(self):
        self._draw_sky_gradient()
        self._create_stars()
        self.canvas.create_rectangle(0, self.ground_level, self.canvas_width, self.canvas_height, fill="#0b0f18", outline="")
        # Ligne d'horizon : fin filet cyan suggérant la lueur de la ville.
        self.canvas.create_rectangle(0, self.ground_level - 1, self.canvas_width, self.ground_level, fill="#123047", outline="")
        for i in range(self.num_buildings): self._create_building(i)
        self._create_spaceship()
        self.beam_id = self.canvas.create_polygon(0,0, 0,0, 0,0, fill="#ff3b5e", smooth=True, state='hidden')
        self.beam_core_id = self.canvas.create_line(0,0, 0,0, fill="#FFFFFF", width=2, state='hidden')

    def _rebuild_scene(self):
        self._resize_after_id = None
        if not self._canvas_alive():
            return
        # Se souvenir des immeubles déjà détruits pour ne pas les "ressusciter"
        destroyed_indices = {i for i, b in enumerate(self.buildings) if b['state'] == 'destroyed'}
        # Effacer et reconstruire en fonction de la nouvelle taille
        self.canvas.delete("all")
        self.buildings.clear()
        self.particles.clear()
        self.stars.clear()
        self.canvas_width = self.canvas.winfo_width()
        self.canvas_height = self.canvas.winfo_height()
        self.ground_level = self.canvas_height - 20
        self._create_scene()
        for index in destroyed_indices:
            if 0 <= index < len(self.buildings):
                self._mark_building_destroyed(index)

    def _mark_building_destroyed(self, index):
        """Réapplique l'état visuel 'détruit' (couleur + flammes) sans rejouer
        l'animation du vaisseau/rayon. Utilisé pour préserver la jauge de vie
        après un redimensionnement (_rebuild_scene)."""
        building = self.buildings[index]
        building['state'] = 'destroyed'
        self.canvas.itemconfig(building['id'], fill="#2a0a12")
        for win_id in building['windows']:
            self.canvas.itemconfig(win_id, fill="#0a0608")
        self._ignite_building(building)

    def _on_resize(self, event):
        # Déclenche un rebuild avec anti-rebond (debounce) : chaque nouvel
        # événement <Configure> annule et reporte le rebuild précédent, pour
        # ne reconstruire la scène qu'une fois le redimensionnement stabilisé.
        if event.width == self.canvas_width and event.height == self.canvas_height:
            return
        self.canvas_width = event.width
        self.canvas_height = event.height
        self.ground_level = self.canvas_height - 20
        if not self._canvas_alive():
            return
        if self._resize_after_id is not None:
            try:
                self.canvas.after_cancel(self._resize_after_id)
            except Exception:
                pass
        try:
            self._resize_after_id = self.canvas.after(120, self._rebuild_scene)
        except Exception:
            self._resize_after_id = None
            self._rebuild_scene()

    def _draw_sky_gradient(self):
        c1, c2 = (4, 6, 11), (12, 26, 50)
        steps = 100
        for i in range(steps):
            r, g, b = [int(c1[j] + (c2[j] - c1[j]) * i / steps) for j in range(3)]
            color = f'#{r:02x}{g:02x}{b:02x}'
            y = self.ground_level * (i / steps)
            self.canvas.create_rectangle(0, y, self.canvas_width, y + (self.ground_level / steps) + 2, fill=color, outline="")

    def _create_stars(self):
        for _ in range(120):
            x = random.uniform(0, self.canvas_width)
            y = random.uniform(0, self.ground_level - 5)
            size = random.choice([1, 1, 2])
            color = random.choice(["#7fc4ff", "#9ae8ff", "#eaf7ff"])
            speed = random.uniform(0.1, 0.6)
            sid = self.canvas.create_oval(x, y, x+size, y+size, fill=color, outline="")
            self.stars.append({'id': sid, 'speed': speed})

    def _create_building(self, index):
        if self.canvas_width < 1: return
        building_width = self.canvas_width / (self.num_buildings + 1)
        x0 = (index + 0.5) * building_width
        max_height = self.ground_level - 40
        height = random.randint(int(max_height * 0.4), int(max_height * 0.9))
        y0 = self.ground_level - height
        x1 = x0 + building_width * 0.8
        color = random.choice(["#0e1a30", "#101d36", "#13223d"])
        rect_id = self.canvas.create_rectangle(x0, y0, x1, self.ground_level, fill=color, outline="#0a101c")
        windows = []
        win_size = 4
        for r in range(int(height / (win_size * 2.5))):
            for c in range(int((x1 - x0) / (win_size * 2.5))):
                if random.random() > 0.3:
                    win_x, win_y = x0 + (c + 0.5) * (win_size * 2), y0 + (r + 0.5) * (win_size * 2)
                    rnd = random.random()
                    if rnd > 0.88:
                        win_color = "#7fe7ff"   # fenêtre cyan (rare)
                    elif rnd > 0.15:
                        win_color = "#ffd977"   # fenêtre ambre
                    else:
                        win_color = "#1a2438"   # éteinte
                    win_id = self.canvas.create_rectangle(win_x, win_y, win_x + win_size, win_y + win_size, fill=win_color, outline="")
                    windows.append(win_id)
        self.buildings.append({'id': rect_id, 'windows': windows, 'flames': [], 'state': 'intact'})

    def _create_spaceship(self):
        self.ship_body_id = self.canvas.create_polygon(0,0, 0,0, 0,0, 0,0, 0,0, fill="#d8e9ff", outline="#00d9ff", width=2, state='hidden')
        self.ship_cockpit_id = self.canvas.create_oval(0,0, 0,0, fill="#00d9ff", outline="#7fe7ff", state='hidden')

    def reset(self):
        for building in self.buildings:
            building['state'] = 'intact'
            self.canvas.itemconfig(building['id'], fill=random.choice(["#0e1a30", "#101d36", "#13223d"]))
            for win_id in building['windows']:
                rnd = random.random()
                self.canvas.itemconfig(win_id, fill="#7fe7ff" if rnd > 0.88 else ("#ffd977" if rnd > 0.15 else "#1a2438"))
            for flame_id in building['flames']: self.canvas.delete(flame_id)
            building['flames'].clear()
        self.canvas.itemconfig(self.ship_body_id, state='hidden')
        self.canvas.itemconfig(self.ship_cockpit_id, state='hidden')

    def destroy_building(self, index):
        if not self._canvas_alive(): return
        if not (0 <= index < len(self.buildings)): return
        building = self.buildings[index]
        if building['state'] == 'destroyed': return
        building['state'] = 'destroyed'
        b_coords = self.canvas.coords(building['id'])
        target_x, target_y = (b_coords[0] + b_coords[2]) / 2, b_coords[1]
        ship_x, ship_y = target_x, 50
        body_coords = [ship_x-30, ship_y, ship_x+30, ship_y, ship_x+15, ship_y-15, ship_x-15, ship_y-15]
        cockpit_coords = [ship_x-10, ship_y-22, ship_x+10, ship_y-10]
        self.canvas.coords(self.ship_body_id, *body_coords)
        self.canvas.coords(self.ship_cockpit_id, *cockpit_coords)
        self.canvas.itemconfig(self.ship_body_id, state='normal')
        self.canvas.itemconfig(self.ship_cockpit_id, state='normal')
        self.canvas.after(400, self._fire_beam, ship_x, ship_y, target_x, target_y, building)

    def _fire_beam(self, ship_x, ship_y, target_x, target_y, building):
        if not self._canvas_alive(): return
        beam_coords = [ship_x, ship_y, target_x-10, target_y, target_x+10, target_y]
        self.canvas.coords(self.beam_id, *beam_coords)
        self.canvas.coords(self.beam_core_id, ship_x, ship_y, target_x, target_y)
        self.canvas.itemconfig(self.beam_id, state='normal', fill="#ff3b5e")
        self.canvas.itemconfig(self.beam_core_id, state='normal')
        self.canvas.after(150, self._create_explosion, target_x, target_y, building)

    def _create_explosion(self, x, y, building):
        if not self._canvas_alive(): return
        self.canvas.itemconfig(self.beam_id, state='hidden')
        self.canvas.itemconfig(self.beam_core_id, state='hidden')
        self.canvas.itemconfig(building['id'], fill="#2a0a12")
        for win_id in building['windows']: self.canvas.itemconfig(win_id, fill="#0a0608")
        for _ in range(30):
            angle, speed = random.uniform(0, 2 * math.pi), random.uniform(2, 6)
            dx, dy = speed * math.cos(angle), speed * math.sin(angle)
            size, color = random.randint(3, 6), random.choice(["#FFD700", "#FFA500", "#FF4500", "#FF6347"])
            p_id = self.canvas.create_oval(x-size, y-size, x+size, y+size, fill=color, outline="")
            self.particles.append({'id': p_id, 'dx': dx, 'dy': dy, 'life': 25})
        self.canvas.after(300, self._ignite_building, building)
        self.canvas.after(500, self._hide_ship)

    def _hide_ship(self):
        if not self._canvas_alive(): return
        self.canvas.itemconfig(self.ship_body_id, state='hidden')
        self.canvas.itemconfig(self.ship_cockpit_id, state='hidden')

    def _ignite_building(self, building):
        if not self._canvas_alive(): return
        coords = self.canvas.coords(building['id'])
        x_center, y_top = (coords[0] + coords[2]) / 2, coords[1]
        width = coords[2] - coords[0]
        for i in range(5):
            base_x = x_center + random.uniform(-width/3, width/3)
            base_y = y_top
            flame_height = random.uniform(10, 20)
            flame_width = random.uniform(5, 10)
            points = [base_x - flame_width/2, base_y, base_x + flame_width/2, base_y, base_x, base_y - flame_height]
            color = random.choice(["#FF4500", "#FFA500"])
            flame_id = self.canvas.create_polygon(points, fill=color, outline="", smooth=True)
            building['flames'].append(flame_id)

    def _animate_scene(self):
        if not self._canvas_alive():
            return
        for s in self.stars:
            self.canvas.move(s['id'], 0, s['speed'])
            coords = self.canvas.coords(s['id'])
            if coords and coords[1] > self.ground_level:
                dy = -(self.ground_level - 2)
                self.canvas.move(s['id'], random.uniform(-3, 3), dy)
        for p in self.particles[:]:
            p['dy'] += 0.2
            self.canvas.move(p['id'], p['dx'], p['dy'])
            p['life'] -= 1
            if p['life'] <= 0:
                self.canvas.delete(p['id'])
                self.particles.remove(p)
        for building in self.buildings:
            if building['state'] == 'destroyed':
                for flame_id in building['flames']:
                    coords = self.canvas.coords(flame_id)
                    if len(coords) == 6:
                        coords[4] += random.uniform(-1, 1)
                        coords[5] += random.uniform(-1.5, 0.5)
                        self.canvas.coords(flame_id, *coords)
        if self._canvas_alive():
            try:
                self.canvas.after(50, self._animate_scene)
            except tk.TclError:
                pass

class HighScoreWindow(tk.Toplevel):
    DIFFICULTY_RANKS = {
        "CE1": "Recrue", "CE2": "Soldat", "CM1": "Caporal",
        "CM2": "Vétéran", "Collège": "Grand Stratège"
    }
    RANKS = [
        "Maître de la Flotte Étoilée",
        "Général de la Force Expéditionnaire",
        "Navigateur Suprême",
        "Amiral de la Bordure Extérieure",
        "Colonel Stellaire",
        "Commandant de Bataillon Orbital",
        "Capitaine Corsaire",
        "Lieutenant Astral",
        "Ranger Galactique",
        "Soldat d'Élite"
    ]

    def __init__(self, parent, score_service, colors):
        super().__init__(parent)
        self.title("Panthéon des Héros")
        self.geometry("800x400")
        self.configure(bg=colors['bg'])
        self.transient(parent)
        self.grab_set()
        
        self.score_service = score_service
        self._closed = False
        # Jeton de séquence : incrémenté à chaque nouvelle requête pour ignorer
        # les réponses obsolètes (ex : changement de difficulté pendant un chargement).
        self._request_seq = 0
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        header = tk.Frame(self, bg=colors['bg'])
        header.pack(fill=tk.X, padx=16, pady=(14, 4))
        tk.Label(header, text="PANTHÉON DES HÉROS", bg=colors['bg'], fg=colors.get('text_strong', '#f4f9ff'),
                 font=(FONT_DISPLAY, 15, 'bold')).pack(anchor='w')
        tk.Label(header, text="Théâtre d'opérations — classement des commandants", bg=colors['bg'],
                 fg=colors.get('muted', '#86a3c8'), font=(FONT_BODY, 10, 'italic')).pack(anchor='w')

        row = tk.Frame(self, bg=colors['bg'])
        row.pack(fill=tk.X, padx=16, pady=(6, 8))
        tk.Label(row, text="Difficulté :", bg=colors['bg'], fg=colors.get('accent', '#00d9ff'),
                 font=(FONT_DISPLAY, 10, 'bold')).pack(side=tk.LEFT, padx=(0, 8))
        self.difficulty_var = tk.StringVar(value=list(self.DIFFICULTY_RANKS.keys())[0])
        self.difficulty_menu = ttk.Combobox(row, textvariable=self.difficulty_var,
                                            values=list(self.DIFFICULTY_RANKS.keys()), state="readonly", style='Neon.TCombobox')
        self.difficulty_menu.pack(side=tk.LEFT)
        self.difficulty_menu.bind("<<ComboboxSelected>>", self._update_display)

        cols = ("Rang", "Titre", "Commandant", "Score", "Temps", "Date")
        self.tree = ttk.Treeview(self, columns=cols, show='headings', style='Neon.Treeview')
        for col in cols:
            self.tree.heading(col, text=col)
        self.tree.column("Rang", width=50, anchor=tk.CENTER)
        self.tree.column("Titre", width=150, anchor=tk.CENTER)
        self.tree.column("Commandant", width=150, anchor=tk.W)
        self.tree.column("Score", width=80, anchor=tk.CENTER)
        self.tree.column("Temps", width=80, anchor=tk.CENTER)
        self.tree.column("Date", width=100, anchor=tk.CENTER)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._update_display()

    def _on_close(self):
        # Empêche toute réponse tardive du thread réseau de toucher des
        # widgets détruits (plus d'erreur "invalid command name").
        self._closed = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def _update_display(self, event=None):
        # Nouvelle requête : les réponses des requêtes précédentes (encore en
        # vol) seront ignorées grâce à ce jeton de séquence.
        self._request_seq += 1
        seq = self._request_seq
        difficulty = self.difficulty_var.get()

        for i in self.tree.get_children():
            self.tree.delete(i)
        self.tree.insert("", "end", values=("", "Chargement…", "", "", "", ""))

        def worker():
            # Ne touche à AUCUN widget Tk ici : uniquement l'appel réseau bloquant.
            try:
                scores = self.score_service.get_scores(difficulty)
                error = None
            except Exception as exc:  # noqa: BLE001 - on relaie toute erreur réseau/FTP/JSON à l'UI
                scores = None
                error = exc
            if self._closed:
                return
            try:
                self.after(0, lambda: self._apply_scores(seq, difficulty, scores, error))
            except (RuntimeError, tk.TclError):
                # La fenêtre (ou l'application) a été fermée entre-temps.
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _apply_scores(self, seq, difficulty, scores, error):
        # Exécuté sur le thread principal (via after). On revérifie ici que la
        # fenêtre est toujours vivante et que cette réponse est bien la plus
        # récente demandée (sinon une réponse lente pourrait écraser l'affichage
        # d'une requête plus récente).
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
            self.tree.insert("", "end", values=("", "Erreur de chargement des scores", "", "", "", ""))
            return

        for i, entry in enumerate(scores):
            rank = i + 1
            title = self.RANKS[i] if i < len(self.RANKS) else "Vétéran"

            if difficulty == "Collège" and rank == 1:
                title = "COMMANDANT UNIVERSEL"

            duration = entry.get("duration")
            if duration is not None:
                minutes, seconds = divmod(int(duration), 60)
                time_str = f"{minutes:02d}:{seconds:02d}"
            else:
                time_str = "--:--"

            self.tree.insert("", "end", values=(f"#{rank}", title, entry["name"], f"{entry['score']}/20", time_str, entry.get("date", "N/A")))