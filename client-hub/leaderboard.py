# leaderboard.py
"""Classement GÉNÉRAL du Hub — « qui est le meilleur commandant, toutes
missions confondues ».

C'est la vue qui manquait : le Panthéon existe par jeu ET par niveau (2 jeux ×
5 niveaux aujourd'hui, et ça grandit à chaque ajout), donc aucun écran ne
répondait à la première question que se posent quatre frères et sœurs.

Trié par XP, pas par crédits : les crédits se dépensent en boutique, donc le
solde dit autant « ce que j'ai économisé » que « ce que je vaux ». L'XP, elle,
ne fait que croître et est pondérée par la difficulté (commun/scoring.py).

Aucune dépendance ttk stylée (le Hub ne configure pas de style Treeview) : tout
est dessiné avec les widgets partagés de commun/ui_widgets.py.
"""

import threading
import tkinter as tk

from avatar_picker import resolve_avatar, thumbnail_path
from badges import badge_name
from scoring import grade_info
from theme import FONT_BODY, FONT_DISPLAY, PALETTE, RADIUS_SM
from ui_widgets import NeonButton, RoundedFrame, SectionHeader, rounded_rect

# Podium : anneau or / argent / bronze autour du numéro de rang. Pas d'emoji
# médaille — Tk les rend en monochrome sous Windows, on ne distinguait plus le
# 1er du 2e, alors que c'est justement l'information qu'on vient chercher.
PODIUM_COLORS = {1: "#ffd166", 2: "#c9d6e4", 3: "#cd7f32"}


class LeaderboardWindow(tk.Toplevel):
    """Fenêtre modale du classement global. `game_labels` traduit l'identifiant
    technique d'un jeu ("dictee") en nom affiché ("Dictée") ; `current_player`
    met en évidence la ligne du joueur identifié sur ce PC."""

    def __init__(self, parent, score_service, game_labels: dict = None,
                 current_player: str = None, avatar_options: list = None) -> None:
        super().__init__(parent)
        self.title("CLASSEMENT GÉNÉRAL // TOUTES MISSIONS")
        self.geometry("760x560")
        self.minsize(640, 420)
        self.configure(bg=PALETTE["bg"])
        self.transient(parent)
        self.grab_set()

        self.score_service = score_service
        self.game_labels = game_labels or {}
        self.current_player = (current_player or "").strip().lower()
        # Avatars disponibles sur CE PC : le serveur renvoie des chemins absolus
        # qui peuvent venir d'une autre machine (voir avatar_picker.resolve_avatar).
        self._avatar_options = avatar_options or []
        self._thumbs = {}  # références gardées : Tk ne retient pas les PhotoImage
        self._closed = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        header = tk.Frame(self, bg=PALETTE["bg"])
        header.pack(fill=tk.X, padx=24, pady=(20, 6))
        SectionHeader(header, eyebrow="Classement général",
                      title="Toutes missions confondues", bg=PALETTE["bg"]).pack(anchor="w")
        tk.Label(header, text="Classés par XP — une mission difficile rapporte plus qu'une facile.",
                 bg=PALETTE["bg"], fg=PALETTE["muted"], font=(FONT_BODY, 9)).pack(anchor="w", pady=(4, 0))

        # Zone défilante : 4 joueurs aujourd'hui, mais le serveur en renvoie
        # jusqu'à 50 (voir MAX_LEADERBOARD) et la fratrie peut s'agrandir.
        body = tk.Frame(self, bg=PALETTE["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(10, 6))
        self._canvas = tk.Canvas(body, bg=PALETTE["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(body, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._rows = tk.Frame(self._canvas, bg=PALETTE["bg"])
        self._rows_window = self._canvas.create_window((0, 0), window=self._rows, anchor="nw")
        self._rows.bind("<Configure>",
                        lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfigure(self._rows_window, width=e.width))

        NeonButton(self, text="Fermer", command=self._on_close, variant="ghost",
                   bg=PALETTE["bg"], height=34).pack(padx=24, pady=(2, 18), anchor="e")

        self._show_message("Chargement du classement…")
        self._load()

    # --- Cycle de vie -----------------------------------------------------

    def _on_close(self) -> None:
        # Empêche une réponse réseau tardive de toucher des widgets détruits.
        self._closed = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def _clear_rows(self) -> None:
        for child in self._rows.winfo_children():
            child.destroy()

    def _show_message(self, text: str, color: str = None) -> None:
        self._clear_rows()
        tk.Label(self._rows, text=text, bg=PALETTE["bg"], fg=color or PALETTE["muted"],
                 font=(FONT_BODY, 11, "italic")).pack(anchor="w", padx=8, pady=20)

    # --- Chargement (réseau hors thread UI) --------------------------------

    def _load(self) -> None:
        def worker() -> None:
            entries, error = None, None
            try:
                entries = self.score_service.get_leaderboard()
            except Exception as exc:  # noqa: BLE001 — toute erreur réseau/JSON est relayée à l'UI
                error = exc
            if self._closed:
                return
            try:
                self.after(0, lambda: self._apply(entries, error))
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _apply(self, entries, error) -> None:
        if self._closed:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        if error is not None:
            self._show_message(f"Classement indisponible : {error}", PALETTE["danger"])
            return
        if not entries:
            self._show_message("Aucun commandant enregistré pour l'instant.")
            return

        self._clear_rows()
        for entry in entries:
            self._build_row(entry)

    # --- Rendu d'une ligne -------------------------------------------------

    def _game_recap(self, entry: dict) -> str:
        parts = []
        for game in entry.get("games") or []:
            label = self.game_labels.get(game.get("game"), str(game.get("game", "")).capitalize())
            plays = game.get("plays", 0)
            best = game.get("best_score")
            mission = "mission" if plays == 1 else "missions"
            parts.append(f"{label} : {plays} {mission} (record {best})" if best is not None
                         else f"{label} : {plays} {mission}")
        return "   •   ".join(parts) if parts else "Aucune mission jouée pour l'instant."

    def _avatar_thumb(self, avatar_path: str):
        """Miniature de l'avatar d'un joueur, ou None (Pillow absent, avatar non
        choisi, ou fichier inconnu sur ce PC) — le classement reste lisible
        sans, seul le portrait manque."""
        resolved = resolve_avatar(avatar_path, self._avatar_options)
        if not resolved:
            return None
        if resolved in self._thumbs:
            return self._thumbs[resolved]
        try:
            from PIL import Image, ImageTk
            image = Image.open(thumbnail_path(resolved)).resize((44, 44), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
        except Exception:  # noqa: BLE001 — Pillow absent, fichier illisible
            photo = None
        self._thumbs[resolved] = photo
        return photo

    def _build_row(self, entry: dict) -> None:
        rank = entry.get("rank", 0)
        name = entry.get("name", "?")
        xp = int(entry.get("xp", 0) or 0)
        grade, next_grade, xp_in, xp_needed = grade_info(xp)
        badges = entry.get("badges") or []
        is_me = name.strip().lower() == self.current_player

        card = RoundedFrame(self._rows, padding=14, bg=PALETTE["bg"])
        card.pack(fill=tk.X, padx=6, pady=5)
        row = card.inner

        # Rang : anneau coloré pour le podium, anneau neutre ensuite.
        podium = PODIUM_COLORS.get(rank)
        rank_canvas = tk.Canvas(row, width=46, height=46, bg=PALETTE["panel2"], highlightthickness=0)
        rank_canvas.pack(side=tk.LEFT, padx=(0, 12))
        rank_canvas.create_oval(2, 2, 44, 44, fill=PALETTE["accent_glow"],
                                outline=podium or (PALETTE["accent"] if is_me else PALETTE["border_hi"]),
                                width=3 if podium else 1.5)
        rank_canvas.create_text(23, 23, text=str(rank), fill=podium or PALETTE["text_strong"],
                                font=(FONT_DISPLAY, 16, "bold"))

        # Portrait du joueur : c'est la récompense visible d'avoir choisi un
        # avatar dans le Hub — les autres le voient dans le classement.
        thumb = self._avatar_thumb(entry.get("avatar_path"))
        if thumb is not None:
            portrait = tk.Label(row, image=thumb, bg=PALETTE["panel2"], bd=0)
            portrait.image = thumb
            portrait.pack(side=tk.LEFT, padx=(0, 12))

        info = tk.Frame(row, bg=PALETTE["panel2"])
        info.pack(side=tk.LEFT, fill=tk.X, expand=True)

        name_row = tk.Frame(info, bg=PALETTE["panel2"])
        name_row.pack(anchor="w", fill=tk.X)
        tk.Label(name_row, text=name, bg=PALETTE["panel2"],
                 fg=PALETTE["accent_hi"] if is_me else PALETTE["text_strong"],
                 font=(FONT_DISPLAY, 14, "bold")).pack(side=tk.LEFT)
        if is_me:
            tk.Label(name_row, text="C'EST VOUS", bg=PALETTE["panel2"], fg=PALETTE["accent"],
                     font=(FONT_DISPLAY, 8, "bold")).pack(side=tk.LEFT, padx=(8, 0))

        grade_line = f"{grade} — {xp} XP"
        if next_grade:
            grade_line += f"   (encore {xp_needed - xp_in} XP avant {next_grade})"
        tk.Label(info, text=grade_line, bg=PALETTE["panel2"], fg=PALETTE["accent2"],
                 font=(FONT_BODY, 10)).pack(anchor="w", pady=(2, 0))

        tk.Label(info, text=self._game_recap(entry), bg=PALETTE["panel2"], fg=PALETTE["muted"],
                 font=(FONT_BODY, 9), justify=tk.LEFT, wraplength=420).pack(anchor="w", pady=(4, 0))

        if badges:
            names = ", ".join(badge_name(b) for b in badges)
            tk.Label(info, text=f"Succès : {names}", bg=PALETTE["panel2"], fg=PALETTE["faint"],
                     font=(FONT_BODY, 8), justify=tk.LEFT, wraplength=420).pack(anchor="w", pady=(3, 0))

        stats = tk.Frame(row, bg=PALETTE["panel2"])
        stats.pack(side=tk.RIGHT, padx=(10, 0))
        self._stat_chip(stats, "XP", xp).pack(pady=2)
        self._stat_chip(stats, "SUCCÈS", len(badges)).pack(pady=2)

        # Sans ça, la carte prend la hauteur par défaut d'un Canvas Tk (~265 px)
        # et un seul joueur tient à l'écran.
        card.fit_height()

    @staticmethod
    def _stat_chip(parent, label: str, value, width: int = 112, height: int = 32) -> tk.Canvas:
        canvas = tk.Canvas(parent, width=width, height=height, bg=PALETTE["panel2"], highlightthickness=0)
        rounded_rect(canvas, 1, 1, width - 1, height - 1, RADIUS_SM, fill=PALETTE["panel"],
                     outline=PALETTE["border"], width=1)
        canvas.create_text(11, height / 2, anchor="w", text=label, fill=PALETTE["muted"],
                           font=(FONT_BODY, 8, "bold"))
        canvas.create_text(width - 11, height / 2, anchor="e", text=str(value), fill=PALETTE["accent_hi"],
                           font=(FONT_DISPLAY, 12, "bold"))
        return canvas
