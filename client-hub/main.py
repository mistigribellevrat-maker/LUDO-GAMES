# main.py
"""Écran d'accueil des jeux — identifie le joueur (charge sa progression
globale depuis le serveur), puis lance chaque jeu comme aujourd'hui
(sous-processus autonome, sa propre fenêtre Tk), et enchaîne la liste en Mode
Campagne (voir campaign.py). Le pseudo identifié ici est propagé au jeu
lancé (via son user_profile.json local) pour qu'il n'ait pas besoin de le
redemander. Chaque jeu doit avoir déjà été lancé au moins une fois via son
propre LANCER.bat pour que son venv/ait ses paquets installés."""

import json
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

_HERE = os.path.dirname(os.path.abspath(__file__))
COMMUN_DIR = None
for _commun_candidate in (os.path.join(_HERE, "commun"), os.path.join(_HERE, "..", "commun")):
    if os.path.isdir(_commun_candidate):
        COMMUN_DIR = _commun_candidate
        if _commun_candidate not in sys.path:
            sys.path.insert(0, _commun_candidate)
        break

from theme import PALETTE, FONT_DISPLAY, FONT_BODY, RADIUS_SM, RADIUS_MD
from ui_widgets import NeonButton, RoundedFrame, SectionHeader, rounded_rect
from server_client import HighScoreService
from scoring import grade_info

from campaign import CampaignRunner
from leaderboard import LeaderboardWindow
from avatar_picker import AvatarPicker, list_avatars, resolve_avatar, thumbnail_path
from video import play_intro
from logs import log_tk_exceptions, setup_file_logging

logger = logging.getLogger(__name__)

GAMES = [
    {"id": "dictee", "label": "Dictée", "eyebrow": "Orthographe", "dir": "../client-dictee",
     "icon": "🎧", "tagline": "Écoutez, écrivez, corrigez."},
    {"id": "maths", "label": "Grille de Protection", "eyebrow": "Mathématiques", "dir": "../client-maths",
     "icon": "🛡", "tagline": "Calcul mental sous pression."},
    {"id": "conjugaison", "label": "Tourelle de Défense", "eyebrow": "Conjugaison", "dir": "../client-conjugaison",
     "icon": "🎯", "tagline": "Visez juste, conjuguez vite."},
]


def build_launch_command(game: dict, campaign: bool = False) -> list:
    """Commande de lancement d'un jeu en sous-processus.

    Le hub tourne avec le python systeme, mais chaque jeu a ses paquets
    installes dans son propre venv/ : il faut donc son propre interpreteur.
    pythonw.exe (variante sans console) est prefere a python.exe — sinon
    chaque jeu lance depuis le Hub ouvrait une fenetre noire a cote de lui.

    `campaign=True` ajoute `--campagne` : le jeu se refermera tout seul après
    sa mission (voir les mains.py des jeux) pour enchaîner sur le suivant.
    Fonction pure (aucun Popen) : testable sans sous-processus."""
    game_dir = os.path.normpath(os.path.join(_HERE, game["dir"]))
    scripts_dir = os.path.join(game_dir, "venv", "Scripts")
    python_exe = next(
        (os.path.join(scripts_dir, exe) for exe in ("pythonw.exe", "python.exe")
         if os.path.isfile(os.path.join(scripts_dir, exe))),
        sys.executable,
    )
    command = [python_exe, "main.py"]
    if campaign:
        command.append("--campagne")
    return command

PLAYERS_PATH = os.path.join(_HERE, "players.json")
DEFAULT_PLAYERS = ["Arthur", "Oscar", "Cloclo", "Greg"]


class HubApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BASE DE COMMANDEMENT // CHOIX DE LA MISSION")
        # Largeur dimensionnée pour la rangée de cartes de jeu (GAMES) : chaque
        # carte a besoin d'environ 260-300 px pour rester lisible (titre,
        # tagline). pack(side=LEFT, expand=True) ne réduit jamais une carte
        # sous sa largeur naturelle — avec une fenêtre trop étroite, les
        # cartes en trop débordent hors champ au lieu de rétrécir. 1300 px
        # loge confortablement 3 cartes ; minsize suit la même logique.
        self.root.geometry("1300x880")
        self.root.minsize(1200, 820)
        self.root.configure(bg=PALETTE["bg"])

        self.campaign: CampaignRunner | None = None
        self._single_watch_job = None
        self._campaign_watch_job = None
        self._campaign_snapshot_before: dict = {}

        self.username: str | None = None
        self.player_credits = 0
        self.player_xp = 0
        self.player_badges: list = []
        # Avatar : identité globale du joueur, partagée entre tous les jeux
        # (voir avatar_picker.py et players.avatar_path côté serveur).
        self.avatar_path: str | None = None
        self._avatar_options = list_avatars(COMMUN_DIR or "")
        self._avatar_photo = None  # référence gardée : Tk ne retient pas les PhotoImage
        self._players = self._load_players()
        self.high_score_service = None
        self.high_scores_enabled = False
        self._reinit_high_score_service()

        self._build_ui()
        self._ensure_identified()

    # --- Identification --------------------------------------------------

    def _reinit_high_score_service(self) -> None:
        try:
            self.high_score_service = HighScoreService(game="hub")
            self.high_scores_enabled = True
        except Exception as e:
            self.high_score_service = None
            self.high_scores_enabled = False
            logger.warning("Service de scores indisponible pour le hub: %s", e)

    @staticmethod
    def _load_players() -> list:
        """Liste des joueurs inscrits sur ce PC, éditable sans toucher au code
        (voir players.json à côté de ce fichier)."""
        if os.path.exists(PLAYERS_PATH):
            try:
                with open(PLAYERS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    names = [n.strip() for n in data if isinstance(n, str) and n.strip()]
                    if names:
                        return names
            except (OSError, json.JSONDecodeError):
                pass
        return list(DEFAULT_PLAYERS)

    def _pick_player(self) -> str | None:
        """Écran « Qui joue ? » : un bouton par joueur inscrit, + une entrée
        libre pour un invité non inscrit dans players.json."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Qui joue ?")
        dialog.configure(bg=PALETTE["bg"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        tk.Label(dialog, text="Qui joue ?", bg=PALETTE["bg"], fg=PALETTE["accent"],
                 font=(FONT_DISPLAY, 14, "bold")).pack(padx=24, pady=(20, 14))

        result = {"name": None}

        def choose(name: str) -> None:
            result["name"] = name
            dialog.destroy()

        buttons_frame = tk.Frame(dialog, bg=PALETTE["bg"])
        buttons_frame.pack(padx=24, pady=(0, 10), fill=tk.X)
        for name in self._players:
            NeonButton(buttons_frame, text=name, command=lambda n=name: choose(n),
                       variant="solid", bg=PALETTE["bg"], height=40).pack(fill=tk.X, pady=4)

        other_var = tk.StringVar(value="")
        other_row = tk.Frame(dialog, bg=PALETTE["bg"])
        other_row.pack(padx=24, pady=(6, 20), fill=tk.X)
        ttk.Entry(other_row, textvariable=other_var, width=18).pack(side=tk.LEFT, fill=tk.X, expand=True)
        NeonButton(other_row, text="Autre joueur", command=lambda: choose(other_var.get().strip()),
                   variant="ghost", bg=PALETTE["bg"], height=32).pack(side=tk.LEFT, padx=(8, 0))
        other_row.bind("<Return>", lambda e: choose(other_var.get().strip()))

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.wait_window()
        return result["name"] or None

    def _ensure_identified(self) -> None:
        self.username = self._pick_player() or self._players[0]
        self._update_profile_header()
        self._identify_with_server()

    def _change_username(self) -> None:
        name = self._pick_player()
        if not name:
            return
        self.username = name
        # L'avatar appartient au joueur : on efface celui du précédent en
        # attendant la réponse du serveur, plutôt que de l'afficher à tort.
        self.avatar_path = None
        self._update_profile_header()
        self._identify_with_server()

    def _update_profile_header(self) -> None:
        self.name_var.set(f"Commandant {self.username}")
        self._redraw_avatar()
        self._redraw_stat_chip(self._credits_chip, "CRÉDITS", self.player_credits)
        self._redraw_stat_chip(self._xp_chip, "XP", self.player_xp)
        # Grade + prochain palier : la même XP donne le même titre dans tous les
        # jeux (calcul partagé, commun/scoring.py).
        grade, next_grade, xp_in, xp_needed = grade_info(self.player_xp)
        if next_grade:
            self.grade_var.set(f"{grade} — encore {xp_needed - xp_in} XP avant {next_grade}")
        else:
            self.grade_var.set(f"{grade} — grade maximum atteint")

    def _identify_with_server(self) -> None:
        """Charge la progression globale (crédits/XP/badges, partagée entre tous
        les jeux) depuis le serveur. Réseau hors thread UI ; ne bloque jamais
        l'écran d'accueil si le serveur est injoignable (le pseudo local reste
        utilisable, chaque jeu retentera sa propre identification à son
        lancement)."""
        if not self.high_scores_enabled or not self.username:
            return

        def _worker() -> None:
            info = None
            error = None
            try:
                info = self.high_score_service.identify(self.username)
            except Exception as e:
                error = e

            def _apply() -> None:
                if info is not None and info.get("player_id"):
                    self.player_credits = int(info.get("credits", 0) or 0)
                    self.player_xp = int(info.get("xp", 0) or 0)
                    badges = info.get("badges")
                    self.player_badges = badges if isinstance(badges, list) else []
                    # L'avatar enregistré côté serveur peut porter le chemin
                    # d'un AUTRE PC (chemins absolus, convention existante) :
                    # resolve_avatar le ramène sur le fichier équivalent ici.
                    self.avatar_path = resolve_avatar(info.get("avatar_path"), self._avatar_options)
                    self._update_profile_header()
                if error is not None:
                    logger.warning("Identification du hub auprès du serveur échouée: %s", error)

            try:
                self.root.after(0, _apply)
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _open_leaderboard(self) -> None:
        """Classement global (voir leaderboard.py). Le Hub est le seul endroit
        d'où on voit tous les jeux à la fois — c'est donc ici que vit la
        comparaison entre commandants, pas dans un jeu en particulier."""
        if not self.high_scores_enabled or self.high_score_service is None:
            messagebox.showerror(
                "Classement indisponible",
                "Le serveur de scores n'est pas joignable.\n"
                "Vérifiez qu'il tourne (serveur/LANCER_SERVEUR.bat) et l'adresse "
                "dans server_config.json.",
            )
            return
        LeaderboardWindow(
            self.root, self.high_score_service,
            game_labels={g["id"]: g["label"] for g in GAMES},
            current_player=self.username,
            avatar_options=self._avatar_options,
        )

    def _open_avatar_picker(self) -> None:
        """Choix de l'avatar (voir avatar_picker.py). Ne demande rien au réseau
        pour s'ouvrir : la liste vient du dossier commun/assets/avatars, donc
        l'écran reste utilisable serveur éteint."""
        if not self._avatar_options:
            messagebox.showerror(
                "Aucun avatar disponible",
                "Aucun avatar n'a été trouvé dans commun/assets/avatars.\n"
                "Chaque avatar est un couple de fichiers de même nom : X.mp4 et X.jpg.",
            )
            return
        AvatarPicker(self.root, COMMUN_DIR, current=self.avatar_path, on_choose=self._apply_avatar)

    def _apply_avatar(self, avatar_path: str) -> None:
        """Applique le choix : affichage immédiat, puis persistance sur le
        serveur (identité globale) et dans le profil local de chaque jeu.

        Les deux sont nécessaires : le serveur porte l'avatar entre les PC,
        mais chaque jeu renvoie SON avatar local au démarrage
        (`identify(..., avatar_path=...)`) — sans mise à jour locale, le
        prochain lancement d'un jeu réécraserait le choix fait ici."""
        if avatar_path == self.avatar_path:
            return
        self.avatar_path = avatar_path
        self._redraw_avatar()
        for game in GAMES:
            self._sync_identity_to_game(
                os.path.normpath(os.path.join(_HERE, game["dir"])), self.username, avatar_path)
        self._push_avatar_to_server(avatar_path)

    def _push_avatar_to_server(self, avatar_path: str) -> None:
        if not self.high_scores_enabled or not self.username:
            return

        def _worker() -> None:
            try:
                # identify() met à jour players.avatar_path quand le champ est
                # fourni (voir serveur/server.py::_get_or_create_player).
                self.high_score_service.identify(self.username, avatar_path=avatar_path)
            except Exception as e:
                logger.warning("Avatar non enregistré sur le serveur: %s", e)

        threading.Thread(target=_worker, daemon=True).start()

    # --- Petits composants visuels ---------------------------------------

    @staticmethod
    def _icon_badge(parent, icon: str, diameter: int = 52) -> tk.Canvas:
        """Pastille circulaire (glow accent + pictogramme) pour les cartes de
        jeu et la bannière Campagne."""
        canvas = tk.Canvas(parent, width=diameter, height=diameter, bg=PALETTE["panel2"],
                            highlightthickness=0)
        canvas.create_oval(2, 2, diameter - 2, diameter - 2, fill=PALETTE["accent_glow"],
                            outline=PALETTE["accent"], width=1.5)
        canvas.create_text(diameter / 2, diameter / 2, text=icon,
                            font=(FONT_DISPLAY, int(diameter * 0.42)))
        return canvas

    @staticmethod
    def _make_stat_chip(parent, width: int = 118, height: int = 34) -> tk.Canvas:
        return tk.Canvas(parent, width=width, height=height, bg=PALETTE["panel2"], highlightthickness=0)

    @staticmethod
    def _redraw_stat_chip(canvas: tk.Canvas, label: str, value) -> None:
        if not canvas.winfo_exists():
            return
        canvas.delete("all")
        w, h = int(canvas["width"]), int(canvas["height"])
        rounded_rect(canvas, 1, 1, w - 1, h - 1, RADIUS_SM, fill=PALETTE["panel"],
                     outline=PALETTE["border"], width=1)
        canvas.create_text(12, h / 2, anchor="w", text=label, fill=PALETTE["muted"],
                            font=(FONT_BODY, 8, "bold"))
        canvas.create_text(w - 12, h / 2, anchor="e", text=str(value), fill=PALETTE["accent_hi"],
                            font=(FONT_DISPLAY, 13, "bold"))

    def _load_avatar_photo(self, size: int):
        """Miniature de l'avatar courant, ou None si Pillow manque, si aucun
        avatar n'est choisi ou si le fichier est illisible — l'en-tête retombe
        alors sur l'initiale du pseudo, comme avant."""
        if not self.avatar_path:
            return None
        try:
            from PIL import Image, ImageTk
            image = Image.open(thumbnail_path(self.avatar_path)).resize(
                (size, size), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(image)
        except Exception as e:  # noqa: BLE001 — Pillow absent, fichier manquant/corrompu
            logger.warning("Miniature d'avatar illisible (%s): %s", self.avatar_path, e)
            return None

    def _redraw_avatar(self) -> None:
        c = self._avatar_canvas
        if not c.winfo_exists():
            return
        c.delete("all")
        d = int(c["width"])
        # La photo doit rester référencée par l'instance : un PhotoImage local
        # serait ramassé par le GC et la case s'afficherait vide.
        self._avatar_photo = self._load_avatar_photo(d - 6)
        if self._avatar_photo is not None:
            c.create_image(d / 2, d / 2, image=self._avatar_photo)
        else:
            initial = (self.username or "?")[0].upper()
            c.create_oval(2, 2, d - 2, d - 2, fill=PALETTE["accent_glow"],
                          outline=PALETTE["accent"], width=1.5)
            c.create_text(d / 2, d / 2, text=initial, fill=PALETTE["accent_hi"],
                          font=(FONT_DISPLAY, 16, "bold"))
        c.create_oval(2, 2, d - 2, d - 2, fill="", outline=PALETTE["accent"], width=1.5)

    # --- UI ------------------------------------------------------------

    # Vidéo d'accueil 16/9, jouée en pop-up (comme la dictée et les maths, voir
    # commun/video.py::play_intro) une fois au démarrage, avec son. Déposer le
    # fichier à cet emplacement suffit à l'activer.
    BANNER_VIDEO_PATH = os.path.join("assets", "videos", "hub.mp4")

    def _build_ui(self) -> None:
        banner_video_path = os.path.join(_HERE, self.BANNER_VIDEO_PATH)
        if os.path.exists(banner_video_path):
            play_intro(self.root, banner_video_path, bg=PALETTE["bg_deep"],
                       hint_fg=PALETTE["faint"], font=(FONT_BODY, 9, "italic"))

        header = tk.Frame(self.root, bg=PALETTE["bg"])
        header.pack(fill=tk.X, padx=28, pady=(18, 8))
        SectionHeader(header, eyebrow="Base de commandement",
                      title="Choisissez votre mission", bg=PALETTE["bg"]).pack(anchor="w")

        # --- Carte profil : avatar, crédits/XP, changement de commandant ---
        profile_card = RoundedFrame(self.root, padding=12, bg=PALETTE["bg"])
        profile_card.pack(fill=tk.X, padx=28, pady=(4, 10))
        profile_bar = profile_card.inner

        # Deux lignes : identité (portrait, pseudo, grade) et stats en haut,
        # actions en bas. Tout mettre sur une ligne tronquait « Vétéran —
        # encore 2800 XP avant Grand Stratège », or c'est précisément l'info
        # qui donne envie de relancer une mission.
        top_row = tk.Frame(profile_bar, bg=PALETTE["panel2"])
        top_row.pack(fill=tk.X)

        self._avatar_canvas = tk.Canvas(top_row, width=44, height=44, bg=PALETTE["panel2"],
                                         highlightthickness=0, cursor="hand2")
        self._avatar_canvas.pack(side=tk.LEFT, padx=(0, 12))
        # Cliquer le portrait ouvre le choix d'avatar — le raccourci que les
        # enfants tentent en premier ; le bouton « Mon avatar » reste là pour
        # que ce soit découvrable sans avoir à deviner.
        self._avatar_canvas.bind("<Button-1>", lambda _e: self._open_avatar_picker())

        # Les chips (largeur fixe) sont packées avant le nom : pack sert les
        # widgets dans l'ordre de déclaration, donc un pseudo long se fait
        # tronquer plutôt que d'écraser les valeurs chiffrées.
        self._xp_chip = self._make_stat_chip(top_row)
        self._xp_chip.pack(side=tk.RIGHT, padx=(8, 0))
        self._credits_chip = self._make_stat_chip(top_row)
        self._credits_chip.pack(side=tk.RIGHT)

        name_col = tk.Frame(top_row, bg=PALETTE["panel2"])
        name_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.name_var = tk.StringVar(value="")
        tk.Label(name_col, textvariable=self.name_var, bg=PALETTE["panel2"], fg=PALETTE["text_strong"],
                 font=(FONT_DISPLAY, 13, "bold")).pack(anchor="w")
        self.grade_var = tk.StringVar(value="")
        tk.Label(name_col, textvariable=self.grade_var, bg=PALETTE["panel2"],
                 fg=PALETTE["accent2"], font=(FONT_BODY, 10)).pack(anchor="w", pady=(2, 0))

        # Ligne d'actions : les trois boutons ont leur place garantie, sans
        # concurrence avec du texte de longueur variable.
        bottom_row = tk.Frame(profile_bar, bg=PALETTE["panel2"])
        bottom_row.pack(fill=tk.X, pady=(10, 0))
        NeonButton(bottom_row, text="Changer de commandant", command=self._change_username,
                   variant="ghost", bg=PALETTE["panel2"], height=30).pack(side=tk.RIGHT)
        NeonButton(bottom_row, text="Classement", command=self._open_leaderboard,
                   variant="solid", bg=PALETTE["panel2"], height=30).pack(side=tk.RIGHT, padx=(0, 10))
        NeonButton(bottom_row, text="Mon avatar", command=self._open_avatar_picker,
                   variant="ghost", bg=PALETTE["panel2"], height=30).pack(side=tk.RIGHT, padx=(0, 10))

        profile_card.fit_height()  # sinon la carte garde la hauteur par défaut d'un Canvas Tk

        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(self.root, textvariable=self.status_var, bg=PALETTE["bg"],
                                      fg=PALETTE["accent"], font=(FONT_BODY, 10, "italic"))
        self.status_label.pack(anchor="w", padx=28)

        # --- Cartes de jeu ---------------------------------------------------
        cards_row = tk.Frame(self.root, bg=PALETTE["bg"])
        cards_row.pack(fill=tk.X, padx=28, pady=(10, 16))

        self._game_buttons = []
        for game in GAMES:
            card = RoundedFrame(cards_row, padding=18, bg=PALETTE["bg"])
            card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
            self._icon_badge(card.inner, game["icon"]).pack(anchor="w", pady=(0, 10))
            tk.Label(card.inner, text=game["eyebrow"].upper(), bg=PALETTE["panel2"], fg=PALETTE["accent"],
                     font=(FONT_DISPLAY, 9, "bold")).pack(anchor="w")
            tk.Label(card.inner, text=game["label"], bg=PALETTE["panel2"], fg=PALETTE["text_strong"],
                     font=(FONT_DISPLAY, 16, "bold")).pack(anchor="w", pady=(2, 4))
            tk.Label(card.inner, text=game["tagline"], bg=PALETTE["panel2"], fg=PALETTE["muted"],
                     font=(FONT_BODY, 9), wraplength=220, justify=tk.LEFT).pack(anchor="w", pady=(0, 16))
            btn = NeonButton(card.inner, text="Jouer", command=lambda g=game: self.play_single(g),
                              variant="solid", bg=PALETTE["panel2"], height=36)
            btn.pack(anchor="w")
            self._game_buttons.append(btn)
            # Après avoir rempli la carte, jamais avant : fit_height mesure le
            # contenu de `inner`. Appelée sur une carte vide, elle la fige à la
            # hauteur des seules marges et tout le contenu (dont « Jouer »)
            # reste invisible.
            card.fit_height()

        # --- Bannière Mode Campagne -------------------------------------------
        campaign_card = RoundedFrame(self.root, padding=14, bg=PALETTE["bg"])
        campaign_card.pack(fill=tk.X, padx=28, pady=(0, 24))
        campaign_bar = campaign_card.inner

        self._icon_badge(campaign_bar, "🎖", diameter=44).pack(side=tk.LEFT, padx=(0, 14))

        campaign_text = tk.Frame(campaign_bar, bg=PALETTE["panel2"])
        campaign_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(campaign_text, text="MODE CAMPAGNE", bg=PALETTE["panel2"], fg=PALETTE["accent"],
                 font=(FONT_DISPLAY, 9, "bold")).pack(anchor="w")
        tk.Label(campaign_text, text="Enchaînez toutes les missions à la suite, sans repasser par cet écran.",
                 bg=PALETTE["panel2"], fg=PALETTE["muted"], font=(FONT_BODY, 9), wraplength=420,
                 justify=tk.LEFT).pack(anchor="w")

        self.campaign_button = NeonButton(campaign_bar, text="Lancer la Campagne",
                                           command=self.start_campaign, variant="solid",
                                           bg=PALETTE["panel2"], height=38)
        self.campaign_button.pack(side=tk.RIGHT)
        campaign_card.fit_height()

    def _set_busy(self, text: str) -> None:
        self.status_var.set(text)
        for btn in self._game_buttons:
            btn.set_state(tk.DISABLED)
        self.campaign_button.set_state(tk.DISABLED)

    def _set_idle(self) -> None:
        self.status_var.set("")
        for btn in self._game_buttons:
            btn.set_state(tk.NORMAL)
        self.campaign_button.set_state(tk.NORMAL)

    # --- Lancement d'un jeu ------------------------------------------------

    @staticmethod
    def _sync_identity_to_game(game_dir: str, username: str, avatar_path: str = None) -> None:
        """Écrit l'identité choisie au Hub (pseudo, et avatar s'il est fourni)
        dans le user_profile.json local du jeu ciblé, pour qu'il démarre déjà
        identifié (pas de redemande de pseudo) et récupère lui-même la
        progression globale au lancement.

        Ne touche qu'aux champs concernés : le reste du profil (meilleurs
        scores, inventaire d'armes...) appartient au jeu et n'est jamais
        écrasé."""
        profile_path = os.path.join(game_dir, "user_profile.json")
        data = {}
        if os.path.exists(profile_path):
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                data = {}
        changes = {"username": username}
        if avatar_path:
            changes["avatar_path"] = avatar_path
        if all(data.get(key) == value for key, value in changes.items()):
            return
        data.update(changes)
        try:
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except OSError as e:
            logger.warning("Impossible de propager l'identité vers %s: %s", profile_path, e)

    def _launch_game_process(self, game: dict, campaign: bool = False) -> subprocess.Popen:
        game_dir = os.path.normpath(os.path.join(_HERE, game["dir"]))
        if self.username:
            self._sync_identity_to_game(game_dir, self.username, self.avatar_path)
        # Le hub tourne avec le python systeme, mais chaque jeu a ses paquets
        # installes dans son propre venv/. Utiliser sys.executable ici
        # lancerait le jeu sans pygame/PIL/etc.
        command = build_launch_command(game, campaign)
        # Filet supplementaire quand on retombe sur sys.executable (python.exe) :
        # CREATE_NO_WINDOW empeche la console d'apparaitre. Le drapeau n'existe
        # que sous Windows.
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(command, cwd=game_dir, creationflags=creation_flags)

    def play_single(self, game: dict) -> None:
        self._set_busy(f"{game['label']} en cours — revenez ici à la fermeture du jeu.")
        try:
            proc = self._launch_game_process(game)
        except OSError as e:
            messagebox.showerror("Erreur de lancement", f"Impossible de lancer {game['label']} :\n{e}")
            self._set_idle()
            return
        self._watch_single(proc)

    def _watch_single(self, proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            self._single_watch_job = self.root.after(300, lambda: self._watch_single(proc))
        else:
            self._single_watch_job = None
            self._set_idle()
            # Le jeu vient de pousser sa progression au serveur : on la relit
            # pour que crédits, XP et grade soient à jour dès le retour à la
            # base, sans avoir à relancer le Hub.
            self._identify_with_server()

    # --- Mode Campagne ---------------------------------------------------

    @staticmethod
    def _read_progress_snapshot(game_dir: str) -> dict:
        """Lit credits/xp/badges dans le cache local (user_profile.json) d'un
        jeu. Comme cette progression est globale (partagée entre tous les
        jeux, voir serveur/server.py), n'importe quel jeu donne un instantané
        fidèle — à condition qu'il ait déjà synchronisé avec le serveur au
        moins une fois (ce qui arrive dès son lancement). Ne lance aucun
        appel réseau lui-même : lecture locale uniquement, jamais bloquante."""
        path = os.path.join(_HERE, game_dir, "user_profile.json")
        if not os.path.exists(path):
            return {"credits": 0, "xp": 0, "badges": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {"credits": 0, "xp": 0, "badges": []}
        if not isinstance(data, dict):
            return {"credits": 0, "xp": 0, "badges": []}
        badges = data.get("badges")
        return {
            "credits": int(data.get("credits", 0) or 0),
            "xp": int(data.get("xp", 0) or 0),
            "badges": badges if isinstance(badges, list) else [],
        }

    def start_campaign(self) -> None:
        if not GAMES:
            return
        self._campaign_snapshot_before = self._read_progress_snapshot(GAMES[0]["dir"])
        self._set_busy(f"Mode Campagne — {GAMES[0]['label']} en cours...")
        # campaign=True : les jeux reçoivent --campagne et se referment tout
        # seuls après leur mission (voir les mains.py des jeux), ce qui fait
        # avancer CampaignRunner vers le jeu suivant.
        self.campaign = CampaignRunner(
            GAMES, lambda game: self._launch_game_process(game, campaign=True),
            on_finished=self._campaign_finished,
        )
        self.campaign.start()
        self._poll_campaign()

    def _poll_campaign(self) -> None:
        if self.campaign is None:
            return
        if self.campaign.poll():
            current = self.campaign.current_game
            if current is not None:
                self.status_var.set(f"Mode Campagne — {current['label']} en cours...")
            self._campaign_watch_job = self.root.after(300, self._poll_campaign)

    def _campaign_finished(self) -> None:
        self._campaign_watch_job = None
        self._set_idle()
        self._identify_with_server()  # rafraîchit crédits/XP/grade de l'en-tête
        after = self._read_progress_snapshot(GAMES[-1]["dir"])
        self._show_campaign_recap(self._campaign_snapshot_before, after)

    def _show_campaign_recap(self, before: dict, after: dict) -> None:
        credit_gain = max(0, after.get("credits", 0) - before.get("credits", 0))
        xp_gain = max(0, after.get("xp", 0) - before.get("xp", 0))
        new_badges = [b for b in after.get("badges", []) if b not in before.get("badges", [])]

        dialog = tk.Toplevel(self.root)
        dialog.title("Campagne terminée")
        dialog.configure(bg=PALETTE["bg"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        SectionHeader(dialog, eyebrow="Campagne terminée", title="Bravo, Commandant !",
                      bg=PALETTE["bg"]).pack(padx=20, pady=(18, 10), anchor="w")

        panel = RoundedFrame(dialog, padding=16, bg=PALETTE["bg"])
        panel.pack(fill=tk.X, padx=20, pady=(0, 10))
        played = ", ".join(g["label"] for g in GAMES)
        tk.Label(panel.inner, text=f"Missions jouées : {played}", bg=PALETTE["panel2"],
                 fg=PALETTE["text"], font=(FONT_BODY, 10), wraplength=360, justify=tk.LEFT).pack(anchor="w")
        tk.Label(panel.inner, text=f"+ {credit_gain} crédits   —   + {xp_gain} XP", bg=PALETTE["panel2"],
                 fg=PALETTE["accent"], font=(FONT_DISPLAY, 12, "bold")).pack(anchor="w", pady=(10, 0))
        if new_badges:
            names = ", ".join(b.replace("_", " ").capitalize() for b in new_badges)
            tk.Label(panel.inner, text=f"Nouveau(x) succès : {names}", bg=PALETTE["panel2"],
                     fg=PALETTE["accent2"], font=(FONT_BODY, 10, "italic"), wraplength=360,
                     justify=tk.LEFT).pack(anchor="w", pady=(8, 0))

        NeonButton(dialog, text="Retour à la base", command=dialog.destroy, variant="solid",
                   bg=PALETTE["bg"], height=36).pack(padx=20, pady=(4, 18), anchor="e")
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"+{x}+{y}")


def main() -> None:
    # Sans console (pythonw, voir LANCER.bat), le journal fichier est la seule
    # trace en cas d'erreur.
    setup_file_logging(_HERE)
    root = tk.Tk()
    log_tk_exceptions(root)
    HubApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
