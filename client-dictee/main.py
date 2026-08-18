# main.py

import os
import json
import sys
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import difflib
import re
import string
import math
import threading
import time
import logging
from datetime import date, timedelta
from typing import Optional
from dotenv import load_dotenv
from PIL import Image, ImageTk
import pygame

# --- commun/ : code + assets partagés entre tous les jeux (thème, widgets Tk,
# client HTTP du serveur de scores, avatars). Distribué (sous-dossier "commun")
# ou dossier frère en dev. ---
_HERE = os.path.dirname(os.path.abspath(__file__))
COMMUN_DIR = None
for _commun_candidate in (os.path.join(_HERE, "commun"), os.path.join(_HERE, "..", "commun")):
    if os.path.isdir(_commun_candidate):
        COMMUN_DIR = _commun_candidate
        if _commun_candidate not in sys.path:
            sys.path.insert(0, _commun_candidate)
        break

# --- Imports depuis nos modules locaux ---
from services import (
    GeminiService, TTSService, AntiCheatService, MusicService,
    VideoService, VideoState
)
from server_client import HighScoreService, load_server_config, save_server_config_override
from scoring import (
    GRADES as SHARED_GRADES, LEVEL_MULTIPLIERS as SHARED_LEVEL_MULTIPLIERS,
    clamp_ratio, compute_rewards, grade_info,
)
from badges import BADGES as SHARED_BADGES, badge_name
from avatars import avatars_dir, list_avatars
from video import play_intro
from logs import log_tk_exceptions, setup_file_logging
from ui_components import CityManager, HighScoreWindow
from theme import PALETTE, FONT_DISPLAY, FONT_BODY, FONT_MONO
from ui_widgets import NeonButton, RoundedFrame, SectionHeader, SegmentedControl, ShieldMeter

logger = logging.getLogger(__name__)

# --- Application Principale ---

class DictationApp:
    DIFFICULTY_LEVELS = ["CE1", "CE2", "CM1", "CM2", "Collège"]
    # Multiplicateurs de récompense par niveau, partagés avec tous les jeux
    # (commun/scoring.py) : crédits ET XP sont une progression globale, un même
    # niveau de difficulté doit rapporter pareil partout.
    LEVEL_MULTIPLIERS = SHARED_LEVEL_MULTIPLIERS
    MAX_SCORE = 20      # bouclier plein : échelle interne de ce jeu
    GAME_WEIGHT = 1.0   # poids de la dictée dans l'XP commune (voir scoring.py)
    # Catalogue d'armes: prix et aides gratuites octroyées
    SHOP_ITEMS = [
        {"key": "couteau_laser", "name": "Couteau laser", "price": 120, "helps": 1},
        {"key": "pistolet_plasma", "name": "Pistolet plasma", "price": 250, "helps": 2},
        {"key": "fusil_ionique", "name": "Fusil ionique", "price": 400, "helps": 4},
        {"key": "canon_particules", "name": "Canon à particules", "price": 650, "helps": 7},
        {"key": "sabre_quantique", "name": "Sabre quantique", "price": 900, "helps": 10},
    ]
    # Grades militaires (progression XP visible), partagés avec tous les jeux.
    GRADES = SHARED_GRADES
    ECLAIR_MAX_SECONDS = 180   # seuil du succès "Éclair"
    RICH_CREDITS_THRESHOLD = 300  # seuil du succès "Crésus"
    DAILY_BONUS_BASE = 15      # bonus de l'objectif quotidien (1 dictée/jour)
    DAILY_BONUS_PER_STREAK = 5 # +X crédits par jour de série
    DAILY_BONUS_CAP = 50       # plafond du bonus quotidien
    # Catalogue des succès, partagé avec tous les jeux (commun/badges.py) :
    # les badges sont une progression globale, ils doivent porter le même nom
    # partout (ce Panthéon, le jeu de maths, le classement du Hub).
    BADGES = SHARED_BADGES
    _LEVEL_SLUGS = {"CE1": "ce1", "CE2": "ce2", "CM1": "cm1", "CM2": "cm2", "Collège": "college"}
    STREAK_MILESTONES = (7, 30, 100)

    def __init__(self, root, gemini_service, tts_service, anticheat_service, music_service):
        self.root = root
        self.gemini_service = gemini_service
        self.tts_service = tts_service
        self.anticheat_service = anticheat_service
        self.music_service = music_service
        self.avatar_video_service = None
        self.event_video_service = None
        
        self.dictation_sentences = []
        self.current_sentence_index = 0
        self.score = 20
        self.game_over = False
        self.start_time = None
        # Drapeau mis à True dès le début de la fermeture de la fenêtre pour
        # empêcher tout callback différé (after/thread) de toucher des widgets détruits.
        self._closing = False
        # Profil utilisateur
        self.profile_path = os.path.join(os.getcwd(), "user_profile.json")
        self.username = None
        self.player_id = None
        self.avatar_path = None
        # Système de crédits et aides
        self.credits = 0
        self.help_tokens = 0  # Aides à la correction gratuites disponibles
        self.owned_weapons = {}  # {weapon_key: count}
        self.weapon_help_pool = {}  # {weapon_key: helps}
        # Progression & récompenses
        self.best_scores = {}        # {niveau: meilleur score}
        self.badges = []             # ids des succès débloqués
        self.levels_played = []      # niveaux déjà joués
        self.last_play_date = ""     # date ISO du dernier objectif quotidien validé
        self.streak = 0              # jours consécutifs d'objectif validé
        self.xp = 0                  # points d'expérience (progression de grade)
        self._sentence_penalized = False  # friction fix : une seule pénalité par phrase
        # Précision (indépendante du score/crédits, jamais punitive) : nombre de
        # phrases ayant nécessité une correction et d'aides utilisées sur la
        # dictée en cours. Sert uniquement à calculer les étoiles de fin de
        # mission (voir _compute_precision_stars), remis à zéro à chaque
        # nouvelle dictée (start_new_dictation).
        self._sentences_needing_correction = 0
        self._helps_used_this_dictation = 0
        # Avatars : identité de joueur partagée entre tous les jeux (voir
        # commun/avatars.py et le champ avatar_path global côté serveur).
        # Liste découverte dans le dossier, plus codée en dur : déposer un couple
        # X.mp4 + X.jpg dans commun/assets/avatars/ suffit à ajouter un avatar,
        # ici comme dans le Hub.
        _avatars_dir = avatars_dir(COMMUN_DIR) if COMMUN_DIR else os.path.join("assets", "videos")
        self.avatar_options = list_avatars(COMMUN_DIR) if COMMUN_DIR else []
        # Dossier des miniatures d'avatars (mêmes noms de base, extension .jpg)
        self.avatar_image_dir = _avatars_dir
        # Cache pour éviter que les images ne soient collectées
        self._avatar_thumbs_cache = {}
        self.weapon_image_cache = {}

        self.root.title("DICTATION WAR // SYSTÈME DE DÉFENSE v2.5")
        self.root.geometry("1450x850")
        self.root.minsize(1450, 850)
        
        self._setup_theme()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        self.high_score_service = None
        self.high_scores_enabled = True
        self._reinit_high_score_service(warn_on_failure=True)

        self._setup_widgets()
        # Charger (ou demander) le profil et définir l'avatar vidéo de démarrage
        self._initialize_profile()
        # Identifier (ou reconnecter) le joueur auprès du serveur de scores.
        self._identify_with_server()
        # Mettre à jour l'affichage des crédits après chargement du profil
        self._update_credits_label()
        self._update_helps_label()
        self._refresh_inventory_ui()
        self._update_xp_display()
        self.avatar_video_service.set_startup_video(self.avatar_path if self.avatar_path and os.path.exists(self.avatar_path) else None)
        self.music_service.play_background()
        self.avatar_video_service.set_video(VideoState.STARTUP)
        self.event_video_service.set_video(VideoState.IDLE)

        # Intro vidéo 16/9 en pop-up, puis message d'accueil. Le message est
        # décalé après l'intro : les deux en même temps se parleraient dessus.
        # Sans fichier vidéo, play_intro appelle directement la suite — le jeu
        # démarre donc normalement tant qu'aucune intro n'a été déposée.
        self._play_intro_video()

    # Intro jouée au démarrage : déposer le fichier à cet emplacement suffit à
    # l'activer, aucun réglage à faire (voir commun/video.py::play_intro).
    INTRO_VIDEO_PATH = os.path.join("assets", "videos", "intro.mp4")

    def _play_intro_video(self) -> None:
        def _after_intro() -> None:
            if self._closing:
                return
            self.tts_service.speak(
                "Systèmes en ligne. Boucliers du dôme à 100%. "
                "En attente de vos ordres, Commandant."
            )

        play_intro(
            self.root,
            os.path.join(_HERE, self.INTRO_VIDEO_PATH),
            on_close=_after_intro,
            bg=self.colors['bg'],
            hint_fg=self.colors['muted'],
            font=(FONT_BODY, 9, 'italic'),
        )

    def _setup_theme(self):
        # Palette centralisée (theme.py) : `self.colors` reste un dict plat pour
        # la compatibilité avec les méthodes existantes et les tests.
        self.colors = dict(PALETTE)
        c = self.colors
        self.root.configure(bg=c['bg'])

        style = ttk.Style(self.root)
        style.theme_use('clam')

        # --- base ---------------------------------------------------------
        style.configure('.', background=c['bg'], foreground=c['text'], font=(FONT_BODY, 10))
        style.configure('TFrame', background=c['bg'])
        style.configure('HUD.TFrame', background=c['panel'])
        style.configure('HUD.Section.TFrame', background=c['panel2'])

        # --- labels -------------------------------------------------------
        style.configure('TLabel', background=c['bg'], foreground=c['text'], font=(FONT_BODY, 11))
        style.configure('HUD.TLabel', background=c['panel2'], foreground=c['text'], font=(FONT_BODY, 11))
        style.configure('HUD.Title.TLabel', background=c['panel'], foreground=c['accent'], font=(FONT_DISPLAY, 12, 'bold'))
        style.configure('Status.TLabel', background=c['bg'], foreground=c['muted'], font=(FONT_BODY, 10, 'italic'))

        # --- cadres de vidéo (ttk.LabelFrame, fins) ----------------------
        style.configure('Video.TLabelframe', background=c['bg'], bordercolor=c['border'], relief='flat', borderwidth=1)
        style.configure('Video.TLabelframe.Label', background=c['bg'], foreground=c['accent'], font=(FONT_DISPLAY, 9, 'bold'))

        # --- champs de saisie --------------------------------------------
        style.configure('TEntry', fieldbackground=c['panel2'], foreground=c['text_strong'],
                        bordercolor=c['border'], insertcolor=c['accent'], relief='flat', padding=6)
        style.map('TEntry', bordercolor=[('focus', c['accent'])])

        # --- combobox (listes déroulantes) -------------------------------
        self.root.option_add('*TCombobox*Listbox*Background', c['panel2'])
        self.root.option_add('*TCombobox*Listbox*Foreground', c['text'])
        self.root.option_add('*TCombobox*Listbox*selectBackground', c['panel3'])
        self.root.option_add('*TCombobox*Listbox*selectForeground', c['accent_hi'])
        style.configure('TCombobox', fieldbackground=c['panel2'], background=c['panel2'],
                        foreground=c['text'], arrowcolor=c['accent'], bordercolor=c['border'], relief='flat', padding=6)
        style.map('TCombobox', fieldbackground=[('readonly', c['panel2'])],
                  bordercolor=[('focus', c['accent'])])

        # --- tableau du Panthéon -----------------------------------------
        style.configure('Neon.Treeview', background=c['panel2'], fieldbackground=c['panel2'],
                        foreground=c['text'], bordercolor=c['border'], rowheight=26)
        style.configure('Neon.Treeview.Heading', background=c['panel'], foreground=c['accent'],
                        font=(FONT_DISPLAY, 10, 'bold'), relief='flat')
        style.map('Neon.Treeview', background=[('selected', c['panel3'])],
                  foreground=[('selected', c['accent_hi'])])
        style.map('Neon.Treeview.Heading', background=[('active', c['panel3'])])

        # --- barre de défilement (console) -------------------------------
        style.configure('Vertical.TScrollbar', background=c['panel'], troughcolor=c['panel2'],
                        bordercolor=c['border'], arrowcolor=c['muted'])
        style.map('Vertical.TScrollbar', background=[('active', c['panel3'])])

    # L'écran d'intro (assets/images/intro.png affiché 5 secondes au démarrage)
    # a été retiré : il retardait l'accès au jeu à chaque lancement. Le fichier
    # reste dans assets/images/ si on veut le remettre un jour.

    def _setup_widgets(self):
        c = self.colors
        top_container = ttk.Frame(self.root)
        top_container.pack(fill=tk.BOTH, expand=True)

        # --- Barre de commandement (carte double-bezel) ------------------
        cmd_frame = RoundedFrame(top_container, padding=12, bg=c['bg'])
        cmd_frame.pack(fill=tk.X, padx=14, pady=(12, 8))
        bar = cmd_frame.inner
        bar.configure(bg=c['panel2'])

        # Rangée 1 : niveau de menace (gauche) + ressources (droite)
        row1 = tk.Frame(bar, bg=c['panel2'])
        row1.pack(fill=tk.X, padx=10, pady=(10, 4))
        tk.Label(row1, text="NIVEAU DE MENACE", bg=c['panel2'], fg=c['accent'],
                 font=(FONT_DISPLAY, 9, 'bold')).pack(side=tk.LEFT, padx=(0, 10))
        self.level_var = tk.StringVar(value=self.DIFFICULTY_LEVELS[2])
        self.level_segment = SegmentedControl(row1, self.DIFFICULTY_LEVELS, self.level_var, bg=c['panel2'])
        self.level_segment.pack(side=tk.LEFT)
        self.helps_var = tk.StringVar(value="Aides : 0")
        self.helps_label = tk.Label(row1, textvariable=self.helps_var, bg=c['panel2'], fg=c['accent2'],
                                    font=(FONT_DISPLAY, 10, 'bold'))
        self.helps_label.pack(side=tk.RIGHT, padx=(12, 0))
        self.credits_var = tk.StringVar(value="Crédits : 0")
        self.credits_label = tk.Label(row1, textvariable=self.credits_var, bg=c['panel2'], fg=c['accent2'],
                                      font=(FONT_DISPLAY, 10, 'bold'))
        self.credits_label.pack(side=tk.RIGHT, padx=(12, 0))

        # Rangée grade + XP (progression visible en permanence)
        row_xp = tk.Frame(bar, bg=c['panel2'])
        row_xp.pack(fill=tk.X, padx=10, pady=(0, 2))
        tk.Label(row_xp, text="GRADE", bg=c['panel2'], fg=c['accent'],
                 font=(FONT_DISPLAY, 9, 'bold')).pack(side=tk.LEFT, padx=(0, 8))
        self.grade_label = tk.Label(row_xp, text="Recrue", bg=c['panel2'], fg=c['text'],
                                    font=(FONT_DISPLAY, 10, 'bold'))
        self.grade_label.pack(side=tk.LEFT, padx=(0, 10))
        self.xp_bar = ttk.Progressbar(row_xp, orient='horizontal', mode='determinate')
        self.xp_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.xp_text = tk.Label(row_xp, text="0 / 100 XP", bg=c['panel2'], fg=c['muted'],
                                font=(FONT_MONO, 9))
        self.xp_text.pack(side=tk.LEFT)

        # Rangée 2 : secteur d'origine (gauche) + actions (droite)
        row2 = tk.Frame(bar, bg=c['panel2'])
        row2.pack(fill=tk.X, padx=10, pady=(4, 10))
        tk.Label(row2, text="SECTEUR D'ORIGINE", bg=c['panel2'], fg=c['accent'],
                 font=(FONT_DISPLAY, 9, 'bold')).pack(side=tk.LEFT, padx=(0, 10))
        self.theme_var = tk.StringVar(value="L'invasion extraterrestre")
        self.theme_entry = ttk.Entry(row2, textvariable=self.theme_var, width=28, font=(FONT_MONO, 10))
        self.theme_entry.pack(side=tk.LEFT, ipady=5)

        self.scores_button = NeonButton(row2, text="PANTHÉON", command=self._show_high_scores, variant="ghost", bg=c['panel2'], height=34)
        self.scores_button.pack(side=tk.RIGHT, padx=5)
        self.badges_button = NeonButton(row2, text="SUCCÈS", command=self._show_badges, variant="ghost", bg=c['panel2'], height=34)
        self.badges_button.pack(side=tk.RIGHT, padx=5)
        self.settings_button = NeonButton(row2, text="PARAMÈTRES", command=self._open_settings, variant="ghost", bg=c['panel2'], height=34)
        self.settings_button.pack(side=tk.RIGHT, padx=5)
        self.shop_button = NeonButton(row2, text="BOUTIQUE", command=self._open_shop, variant="ghost", bg=c['panel2'], height=34)
        self.shop_button.pack(side=tk.RIGHT, padx=5)
        self.start_button = NeonButton(row2, text="LANCER MISSION", command=self.start_new_dictation, variant="solid", bg=c['panel2'], height=34)
        self.start_button.pack(side=tk.RIGHT, padx=(5, 0))
        if not self.high_scores_enabled:
            self.scores_button.config(state=tk.DISABLED)
        cmd_frame.fit_height()

        main_content_frame = ttk.Frame(top_container)
        main_content_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 8))

        # --- Colonne droite : vidéos + bouclier + armement ---------------
        right_column = ttk.Frame(main_content_frame, width=380)
        right_column.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right_column.pack_propagate(False)

        video_container = ttk.Frame(right_column)
        video_container.pack(fill=tk.X, pady=(0, 8))

        video_width, video_height = 180, 320  # 9:16 aspect ratio

        avatar_video_frame = ttk.LabelFrame(video_container, text="AVATAR", width=video_width, height=video_height, style='Video.TLabelframe')
        avatar_video_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        avatar_video_frame.pack_propagate(False)
        self.avatar_video_service = VideoService(avatar_video_frame, video_width, video_height)

        event_video_frame = ttk.LabelFrame(video_container, text="ÉVÉNEMENT", width=video_width, height=video_height, style='Video.TLabelframe')
        event_video_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        event_video_frame.pack_propagate(False)
        self.event_video_service = VideoService(event_video_frame, video_width, video_height)

        shield_panel = RoundedFrame(right_column, padding=14, bg=c['bg'])
        shield_panel.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
        SectionHeader(shield_panel.inner, eyebrow="Défense", title="Intégrité du dôme").pack(anchor='w', padx=6, pady=(6, 2))
        self.score_label = ttk.Label(shield_panel.inner, text="", font=(FONT_DISPLAY, 34, 'bold'), anchor='center', background=c['panel2'])
        self.score_label.pack(pady=(8, 0), fill=tk.X)
        self.shield_meter = ShieldMeter(shield_panel.inner, height=26, bg=c['panel2'])
        self.shield_meter.pack(pady=6, fill=tk.X, padx=8)
        self.update_score_display()
        self.precision_label = ttk.Label(shield_panel.inner, text="☆ ☆ ☆", font=(FONT_DISPLAY, 16, 'bold'),
                                          anchor='center', background=c['panel2'], foreground=c['muted'])
        self.precision_label.pack(pady=(2, 6), fill=tk.X)

        # Inventaire armement
        self.inventory_panel = RoundedFrame(right_column, padding=12, bg=c['bg'])
        self.inventory_panel.pack(fill=tk.X, pady=(8, 0))
        SectionHeader(self.inventory_panel.inner, eyebrow="Équipement", title="Armement").pack(anchor='w', padx=6, pady=(6, 2))
        self.inventory_content = tk.Frame(self.inventory_panel.inner, bg=c['panel2'])
        self.inventory_content.pack(fill=tk.X, padx=6, pady=(0, 8))
        self._refresh_inventory_ui()

        # --- Colonne gauche : console + analyse des anomalies ------------
        left_column = ttk.Frame(main_content_frame)
        left_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_column.columnconfigure(0, weight=1)
        left_column.rowconfigure(1, weight=1)

        self.status_label = ttk.Label(left_column, text="Prêt à commencer.", style='Status.TLabel', anchor='center')
        self.status_label.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 5))

        terminal_frame = RoundedFrame(left_column, padding=12, bg=c['bg'])
        terminal_frame.grid(row=1, column=0, sticky='nsew', padx=(0, 6))
        SectionHeader(terminal_frame.inner, eyebrow="Transmission", title="Console de décodage").pack(anchor='w', padx=6, pady=(6, 2))
        self.user_text = scrolledtext.ScrolledText(terminal_frame.inner, height=10, font=(FONT_MONO, 13), wrap=tk.WORD)
        self.user_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self.user_text.configure(bg=c['bg'], fg=c['text'], insertbackground=c['accent'],
                                 selectbackground=c['panel3'], relief='flat', bd=0, highlightthickness=0)
        try:
            self.user_text.vbar.configure(bg=c['panel'], troughcolor=c['panel2'],
                                          activebackground=c['panel3'], relief='flat', bd=0)
        except Exception:
            pass
        self.user_text.tag_config("error", background=c['danger'], foreground='#ffffff')
        self.user_text.config(state=tk.DISABLED)

        btn_row = tk.Frame(terminal_frame.inner, bg=c['panel2'])
        btn_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.repeat_button = NeonButton(btn_row, text="RÉPÉTER", command=self.repeat_sentence, variant="ghost", bg=c['panel2'], height=34)
        self.repeat_button.pack(side=tk.LEFT, padx=(0, 5))
        self.validate_button = NeonButton(btn_row, text="VALIDER", command=self.validate_sentence, variant="solid", bg=c['panel2'], height=34)
        self.validate_button.pack(side=tk.LEFT)
        self.repeat_button.config(state=tk.DISABLED)
        self.validate_button.config(state=tk.DISABLED)

        self.errors_frame = RoundedFrame(left_column, padding=12, bg=c['bg'])
        self.errors_frame.grid(row=1, column=1, sticky='nsew', padx=(6, 0))
        SectionHeader(self.errors_frame.inner, eyebrow="Diagnostic", title="Analyse des anomalies").pack(anchor='w', padx=6, pady=(6, 2))
        # La liste des anomalies vit dans son propre conteneur : _clear_errors_frame
        # vide ce conteneur, et non tout le panneau — sinon il emportait aussi le
        # titre ci-dessus, dès le premier affichage.
        self.errors_list = tk.Frame(self.errors_frame.inner, bg=c['panel2'])
        self.errors_list.pack(fill=tk.BOTH, expand=True)
        self._clear_errors_frame()

        # --- Ville / HUD inférieur ---------------------------------------
        self.city_canvas = tk.Canvas(self.root, height=170, highlightthickness=0, bg=c['bg'])
        self.city_canvas.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        self.root.update_idletasks()
        self.city_manager = CityManager(self.city_canvas, 20)

    def _initialize_profile(self):
        # Charger le profil si présent, sinon demander
        try:
            if os.path.exists(self.profile_path):
                with open(self.profile_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.username = data.get('username') or "Commandant"
                    self.player_id = data.get('player_id')
                    self.avatar_path = data.get('avatar_path')
                    self.credits = int(data.get('credits', 0))
                    self.help_tokens = int(data.get('help_tokens', 0))
                    self.owned_weapons = data.get('owned_weapons', {}) or {}
                    self.best_scores = data.get('best_scores', {}) or {}
                    self.badges = data.get('badges', []) or []
                    self.levels_played = data.get('levels_played', []) or []
                    self.last_play_date = data.get('last_play_date', "") or ""
                    self.streak = int(data.get('streak', 0) or 0)
                    self.xp = int(data.get('xp', 0) or 0)
                    # Charger le pool d'aides lié aux armes si présent (pour décrémenter la possession)
                    self.weapon_help_pool = data.get('weapon_help_pool', None)
                    if not isinstance(self.weapon_help_pool, dict):
                        # Reconstruire un pool initial en répartissant les aides restantes (help_tokens)
                        # dans la capacité totale des armes possédées.
                        self.weapon_help_pool = {}
                        # Capacités par arme
                        capacities = {}
                        total_capacity = 0
                        for item in self.SHOP_ITEMS:
                            key = item['key']
                            units = int(self.owned_weapons.get(key, 0))
                            cap = units * int(item['helps'])
                            if cap > 0:
                                capacities[key] = cap
                                total_capacity += cap
                        # Répartir au plus min(help_tokens, total_capacity)
                        remaining = min(self.help_tokens, total_capacity)
                        if remaining > 0 and capacities:
                            # Répartition simple par clé dans l'ordre du catalogue
                            while remaining > 0:
                                progressed = False
                                for item in self.SHOP_ITEMS:
                                    key = item['key']
                                    cap = capacities.get(key, 0)
                                    current = int(self.weapon_help_pool.get(key, 0))
                                    if current < cap and remaining > 0:
                                        self.weapon_help_pool[key] = current + 1
                                        remaining -= 1
                                        progressed = True
                                        if remaining == 0:
                                            break
                                if not progressed:
                                    break
                        # Si aucune capacité, laisser vide (les aides resteront non liées)
                        # Recalcule conservateur des armes possédées à partir du pool
                        for item in self.SHOP_ITEMS:
                            key = item['key']
                            helps_per = int(item['helps'])
                            pool = int(self.weapon_help_pool.get(key, 0))
                            if helps_per > 0:
                                new_units = int(math.ceil(pool / helps_per)) if pool > 0 else 0
                                if new_units < int(self.owned_weapons.get(key, 0)):
                                    self.owned_weapons[key] = new_units
                    # Synchroniser le total des aides avec le pool (somme des aides par arme)
                    try:
                        self.help_tokens = sum(int(v) for v in self.weapon_help_pool.values())
                    except Exception:
                        pass
            else:
                self._show_profile_dialog(initial=True)
        except Exception as e:
            # Fichier de profil absent, corrompu ou illisible : on repart sur des valeurs
            # sûres plutôt que de planter le démarrage.
            logger.warning("Erreur de chargement du profil (%s) : réinitialisation.", e)
            self.username = "Commandant"
            self.avatar_path = self.avatar_options[0] if os.path.exists(self.avatar_options[0]) else None
            self.credits = 0
            self.help_tokens = 0
            self.owned_weapons = {}
            self.weapon_help_pool = {}
            self.best_scores = {}
            self.badges = []
            self.levels_played = []
            self.last_play_date = ""
            self.streak = 0
            self.xp = 0

        # Valeurs par défaut si nécessaires
        if not self.username:
            self.username = "Commandant"
        if not self.avatar_path or not os.path.exists(self.avatar_path):
            # choisir la première option existante
            for opt in self.avatar_options:
                if os.path.exists(opt):
                    self.avatar_path = opt
                    break
            else:
                self.avatar_path = None

    def _save_profile(self) -> None:
        """Écrit le profil sur disque de façon atomique (fichier temporaire + remplacement)
        afin qu'une écriture interrompue (crash, coupure) ne puisse jamais laisser un
        user_profile.json à moitié écrit / corrompu."""
        data = {
            "username": self.username,
            "player_id": self.player_id,
            "avatar_path": self.avatar_path,
            "credits": self.credits,
            "help_tokens": self.help_tokens,
            "owned_weapons": self.owned_weapons,
            "weapon_help_pool": self.weapon_help_pool,
            "best_scores": self.best_scores,
            "badges": self.badges,
            "levels_played": self.levels_played,
            "last_play_date": self.last_play_date,
            "streak": self.streak,
            "xp": self.xp,
        }
        tmp_path = f"{self.profile_path}.tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.profile_path)
        except OSError as e:
            logger.warning("Impossible d'enregistrer le profil: %s", e)
            messagebox.showwarning("Sauvegarde profil", f"Impossible d'enregistrer le profil:\n{e}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

        # Synchronise aussi vers le serveur (progression partagée entre postes).
        self._sync_profile_to_server()

    def _profile_payload(self) -> dict:
        """L'état propre à CE jeu (dictée) : inventaire d'armes/aides, meilleurs
        scores, niveaux joués. Les crédits/XP/badges/série sont désormais une
        progression GLOBALE partagée entre tous les jeux (voir `_global_progress_payload`
        et `_identify_with_server`), plus embarqués ici."""
        return {
            "help_tokens": self.help_tokens,
            "owned_weapons": self.owned_weapons,
            "weapon_help_pool": self.weapon_help_pool,
            "best_scores": self.best_scores,
            "levels_played": self.levels_played,
        }

    def _global_progress_payload(self) -> dict:
        """Progression globale (partagée entre tous les jeux) à pousser vers le
        serveur en même temps que le profil de ce jeu."""
        return {
            "credits": self.credits,
            "xp": self.xp,
            "badges": self.badges,
            "streak": self.streak,
            "last_play_date": self.last_play_date,
        }

    def _apply_server_profile(self, profile: dict) -> None:
        """Adopte la progression stockée sur le serveur pour CE jeu (armes, aides,
        meilleurs scores, niveaux joués). Les crédits/XP/badges/série globaux sont
        appliqués séparément dans `_identify_with_server` (identité partagée entre
        tous les jeux, pas propre à la dictée)."""
        if not isinstance(profile, dict):
            return
        owned = profile.get("owned_weapons")
        self.owned_weapons = owned if isinstance(owned, dict) else {}
        pool = profile.get("weapon_help_pool")
        self.weapon_help_pool = pool if isinstance(pool, dict) else {}
        # Comme au chargement local : les aides sont resynchronisées sur la somme du pool.
        if isinstance(self.weapon_help_pool, dict):
            self.help_tokens = sum(int(v) for v in self.weapon_help_pool.values())
        else:
            self.help_tokens = 0
        best = profile.get("best_scores")
        self.best_scores = best if isinstance(best, dict) else {}
        played = profile.get("levels_played")
        self.levels_played = played if isinstance(played, list) else []

    def _sync_profile_to_server(self) -> None:
        """Pousse l'état local (profil de ce jeu + progression globale) vers le
        serveur, hors thread UI (réseau bloquant)."""
        if not getattr(self, "high_scores_enabled", False):
            return
        service = getattr(self, "high_score_service", None)
        name = getattr(self, "username", None)
        if service is None or not name:
            return
        payload = self._profile_payload()
        global_progress = self._global_progress_payload()

        def _worker() -> None:
            try:
                service.save_profile(name, payload, **global_progress)
            except Exception as e:
                logger.warning("Synchronisation du profil vers le serveur échouée: %s", e)

        threading.Thread(target=_worker, daemon=True).start()

    def _reinit_high_score_service(self, warn_on_failure: bool = False) -> None:
        """(Re)crée le client du serveur de scores à partir de la config effective
        (server_config.local.json > server_config.json > .env). Appelé au démarrage
        et après modification de l'adresse serveur dans Paramètres."""
        try:
            self.high_score_service = HighScoreService()
            self.high_scores_enabled = True
        except Exception as e:
            self.high_score_service = None
            self.high_scores_enabled = False
            if warn_on_failure:
                messagebox.showwarning(
                    "Scores désactivés",
                    f"Impossible d'initialiser le service des scores.\n{e}\nLe Panthéon des Héros ne sera pas disponible."
                )

    def _identify_with_server(self) -> None:
        """Enregistre (ou reconnecte) le joueur auprès du serveur de scores au démarrage.

        Le réseau est bloquant : appel hors thread UI, retour via root.after(0, ...).
        En cas d'échec, on ne bloque jamais la partie (les scores ne seront simplement
        pas transmis tant que le serveur reste injoignable)."""
        if not self.high_scores_enabled or not self.username:
            return

        def _worker() -> None:
            info = None
            error = None
            try:
                info = self.high_score_service.identify(self.username, avatar_path=self.avatar_path)
            except Exception as e:
                error = e

            def _apply() -> None:
                if self._closing:
                    return
                if info is not None and info.get("player_id"):
                    self.player_id = info.get("player_id")
                    self._apply_server_profile(info.get("profile"))
                    # Identité + progression globales (partagées entre tous les jeux) :
                    # remplacent toujours la valeur locale, le serveur fait foi.
                    global_avatar = info.get("avatar_path")
                    if global_avatar and os.path.exists(global_avatar):
                        self.avatar_path = global_avatar
                    self.credits = int(info.get("credits", 0) or 0)
                    self.xp = int(info.get("xp", 0) or 0)
                    badges = info.get("badges")
                    self.badges = badges if isinstance(badges, list) else []
                    self.streak = int(info.get("streak", 0) or 0)
                    self.last_play_date = info.get("last_play_date") or ""
                    self._save_profile()
                    self._update_credits_label()
                    self._update_helps_label()
                    self._refresh_inventory_ui()
                    self._update_xp_display()
                if error is not None:
                    logger.warning("Identification auprès du serveur échouée: %s", error)

            try:
                self.root.after(0, _apply)
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _open_settings(self):
        self._show_profile_dialog(initial=False)

    def _show_profile_dialog(self, initial=False):
        c = self.colors
        dialog = tk.Toplevel(self.root)
        dialog.title("Paramètres du Commandant")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=c['bg'])
        tk.Label(dialog, text="Identifiant du Commandant (pseudo)", bg=c['bg'], fg=c['accent'],
                 font=(FONT_DISPLAY, 11, 'bold')).pack(padx=16, pady=(14, 6), anchor='w')
        name_var = tk.StringVar(value=self.username or "")
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=30)
        name_entry.pack(padx=16, pady=(0, 10), fill=tk.X)
        tk.Label(dialog, text="Serveur de scores (adresse du PC serveur)", bg=c['bg'], fg=c['accent'],
                 font=(FONT_DISPLAY, 11, 'bold')).pack(padx=16, pady=(0, 2), anchor='w')
        tk.Label(dialog, text="Ne pas modifier sauf indication de l'enseignant. Ex: http://192.168.1.20:8000",
                 bg=c['bg'], fg=c['muted'], font=(FONT_BODY, 8)).pack(padx=16, pady=(0, 4), anchor='w')
        server_var = tk.StringVar(value=load_server_config().get("server_url", ""))
        server_entry = ttk.Entry(dialog, textvariable=server_var, width=30)
        server_entry.pack(padx=16, pady=(0, 10), fill=tk.X)
        tk.Label(dialog, text="Choisissez votre avatar (aperçu)", bg=c['bg'], fg=c['accent'],
                 font=(FONT_DISPLAY, 11, 'bold')).pack(padx=16, pady=(10, 6), anchor='w')
        avatar_var = tk.StringVar(value=(self.avatar_path if self.avatar_path in self.avatar_options else None))
        # Liste des options avec miniatures si disponibles
        opts_frame = tk.Frame(dialog, bg=c['panel2'])
        opts_frame.pack(fill=tk.X, padx=16, pady=(0, 10))

        grid = tk.Frame(opts_frame, bg=c['panel2'])
        grid.pack(fill=tk.X, padx=8, pady=8)

        def get_thumb_for(video_path):
            # Convertit assets/videos/X.mp4 -> assets/images/X.jpg
            try:
                base = os.path.splitext(os.path.basename(video_path))[0]
                img_path = os.path.join(self.avatar_image_dir, f"{base}.jpg")
                if not os.path.exists(img_path):
                    return None
                if img_path in self._avatar_thumbs_cache:
                    return self._avatar_thumbs_cache[img_path]
                im = Image.open(img_path)
                im = im.resize((72, 72), Image.Resampling.LANCZOS)
                ph = ImageTk.PhotoImage(im)
                self._avatar_thumbs_cache[img_path] = ph
                return ph
            except Exception:
                return None

        # Grille de choix (miniature + libellé). 4 colonnes : avec 8 avatars, une
        # grille à 2 colonnes ferait 4 rangées et une boîte de dialogue plus haute
        # que l'écran. Le nombre d'avatars n'est pas figé (voir commun/avatars.py).
        cols = 4
        for idx, opt in enumerate(self.avatar_options):
            exists = os.path.exists(opt)
            r, cc = divmod(idx, cols)
            cell = tk.Frame(grid, bg=c['panel2'], padx=4, pady=4)
            cell.grid(row=r, column=cc, padx=6, pady=6, sticky='w')

            thumb = get_thumb_for(opt)
            # Utiliser Radiobutton Tk classique pour gérer l'image aisément
            rb = tk.Radiobutton(
                cell,
                variable=avatar_var,
                value=opt,
                text=(os.path.basename(opt) + (" (introuvable)" if not exists else "")),
                image=thumb,
                compound='left',
                indicatoron=True,
                state=(tk.NORMAL if exists else tk.DISABLED),
                bg=c['panel2'],
                fg=c['text'],
                activebackground=c['panel2'],
                activeforeground=c['accent'],
                selectcolor=c['panel']
            )
            rb.pack(anchor='w')
            # Conserver une référence pour éviter le GC
            if thumb is not None:
                rb.image = thumb
        grade_var = None
        if initial:
            # Premier lancement uniquement : évite de laisser un enfant de CE1
            # démarrer par défaut sur le niveau médian CM1 (main.py: DIFFICULTY_LEVELS[2]).
            # Rien d'irréversible : le niveau reste modifiable à tout moment sur
            # l'écran principal, ceci ne fixe que la première partie.
            tk.Label(dialog, text="Tu es en quelle classe ?", bg=c['bg'], fg=c['accent'],
                     font=(FONT_DISPLAY, 11, 'bold')).pack(padx=16, pady=(10, 2), anchor='w')
            tk.Label(dialog, text="Choisit juste le niveau de départ des dictées — modifiable à tout moment.",
                     bg=c['bg'], fg=c['muted'], font=(FONT_BODY, 8)).pack(padx=16, pady=(0, 6), anchor='w')
            grade_var = tk.StringVar(value=self.DIFFICULTY_LEVELS[0])
            grade_row = tk.Frame(dialog, bg=c['bg'])
            grade_row.pack(padx=16, pady=(0, 10), anchor='w')
            SegmentedControl(grade_row, self.DIFFICULTY_LEVELS, grade_var, bg=c['bg']).pack()

        btns = tk.Frame(dialog, bg=c['bg'])
        btns.pack(fill=tk.X, padx=16, pady=12)
        # Infos crédits + accès boutique
        credits_row = tk.Frame(dialog, bg=c['bg'])
        credits_row.pack(fill=tk.X, padx=16, pady=(6, 0))
        tk.Label(credits_row, text=f"Crédits disponibles : {self.credits}", bg=c['bg'],
                 fg=c['accent2'], font=(FONT_DISPLAY, 10, 'bold')).pack(side=tk.LEFT)
        NeonButton(credits_row, text="Ouvrir la Boutique", command=lambda: (dialog.destroy(), self._open_shop()),
                   variant="ghost", bg=c['bg'], height=30).pack(side=tk.RIGHT)
        def on_ok():
            new_server_url = server_var.get().strip()
            if new_server_url != load_server_config().get("server_url", ""):
                save_server_config_override(new_server_url)
                self._reinit_high_score_service(warn_on_failure=True)
                self.player_id = None  # nouveau serveur -> ré-identification nécessaire
            name = name_var.get().strip() or "Commandant"
            choice = avatar_var.get() if avatar_var.get() else None
            if name != self.username:
                # Nouveau pseudo -> nouvelle identité côté serveur.
                self.player_id = None
            self.username = name
            self.avatar_path = choice if (choice and os.path.exists(choice)) else self.avatar_path
            # Si aucune sélection valide, fallback première option existante
            if not self.avatar_path or not os.path.exists(self.avatar_path):
                for opt in self.avatar_options:
                    if os.path.exists(opt):
                        self.avatar_path = opt
                        break
                else:
                    self.avatar_path = None
            if grade_var is not None:
                self.level_segment.set(grade_var.get())
            self._save_profile()
            # (Ré)identifier le joueur auprès du serveur de scores.
            self._identify_with_server()
            # Appliquer l'avatar immédiatement pour la vidéo de démarrage
            self.avatar_video_service.set_startup_video(self.avatar_path if self.avatar_path and os.path.exists(self.avatar_path) else None)
            # Rafraîchir l'affichage vidéo immédiatement
            self.avatar_video_service.set_video(VideoState.STARTUP)
            dialog.destroy()
        def on_cancel():
            if grade_var is not None:
                self.level_segment.set(grade_var.get())
            if initial and not (self.username and self.avatar_path):
                # En premier démarrage, imposer une valeur par défaut
                self.username = self.username or "Commandant"
                if not (self.avatar_path and os.path.exists(self.avatar_path)):
                    for opt in self.avatar_options:
                        if os.path.exists(opt):
                            self.avatar_path = opt
                            break
                    else:
                        self.avatar_path = None
                self._save_profile()
                self.avatar_video_service.set_startup_video(self.avatar_path if self.avatar_path and os.path.exists(self.avatar_path) else None)
                # Rafraîchir l'affichage vidéo immédiatement
                self.avatar_video_service.set_video(VideoState.STARTUP)
            dialog.destroy()
        ok_btn = NeonButton(btns, text=("Démarrer" if initial else "Enregistrer"), command=on_ok, variant="solid", bg=c['bg'], height=34)
        ok_btn.pack(side=tk.RIGHT, padx=6)
        cancel_btn = NeonButton(btns, text=("Annuler" if not initial else "Par défaut"), command=on_cancel, variant="ghost", bg=c['bg'], height=34)
        cancel_btn.pack(side=tk.RIGHT, padx=6)
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"+{x}+{y}")

    def _normalize_text(self, text: str) -> str:
        t = text.lower().strip().replace("’", "'").replace("`", "'")
        t = re.sub(r"\s+", " ", t).translate(str.maketrans('', '', string.punctuation))
        return re.sub(r"\s+", " ", t).strip()

    def _sanitize_explanation(self, text: str) -> str:
        """Nettoie les sorties IA: supprime Markdown/puces/blocs code, compacte, limite longueur."""
        try:
            if not text:
                return ""
            # Retirer blocs de code ``` ```
            text = re.sub(r"```[\s\S]*?```", " ", text)
            # Retirer emphases et backticks simples
            text = text.replace("**", "").replace("__", "").replace("*", "").replace("`", "")
            # Supprimer préfixes de liste/quote/titres en début de ligne
            lines = [re.sub(r"^\s{0,3}[#>*-]+\s*", "", ln).strip() for ln in text.splitlines()]
            text = " ".join([ln for ln in lines if ln])
            # Compacter espaces
            text = re.sub(r"\s+", " ", text).strip()
            # Limiter longueur raisonnable
            return text[:280]
        except Exception:
            return (text or "")[:280]

    def _clamp_index(self, idx: int, text_len: int) -> int:
        return max(0, min(idx or 0, max(0, text_len - 1)))

    @staticmethod
    def _display_word(text: str, start: int, end: int) -> str:
        """Mot tel qu'il doit APPARAÎTRE dans le diagnostic.

        Le comparateur ignore la ponctuation : « l'esprit » se découpe en deux
        mots, « l » et « esprit ». Afficher « Anomalie: 'l' » à un enfant ne
        veut rien dire — on rattache donc l'apostrophe d'élision au mot pour
        l'affichage, sans rien changer au découpage ni au comptage des fautes.
        """
        word = text[start:end]
        if end < len(text) and text[end] in "'’":
            word += text[end]
        return word

    def _tokenize_words(self, text: str):
        """Retourne une liste de tuples (mot, (start, end)) en ignorant la ponctuation.
        Les mots sont composés de lettres/chiffres Unicode. Utile pour comparer sans tenir compte
        de la casse et de la ponctuation tout en conservant les positions pour le surlignage.
        """
        pattern = r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+"
        tokens = []
        for m in re.finditer(pattern, text, flags=re.UNICODE):
            tokens.append((m.group(0), (m.start(), m.end())))
        return tokens

    def _show_high_scores(self):
        if self.high_scores_enabled: HighScoreWindow(self.root, self.high_score_service, self.colors)
        else: messagebox.showerror("Erreur", "Le service du Panthéon n'est pas disponible.")
    
    def end_dictation(self):
        self.anticheat_service.stop()
        duration = time.time() - self.start_time if self.start_time else 0
        shield_percent = int((self.score / 20) * 100)
        final_message = f"MISSION ACCOMPLIE ! // BOUCLIERS À {shield_percent}%"
        self.status_label.config(text=final_message, foreground=self.colors['accent2'])
        final_speech = f"Mission terminée. Les boucliers du dôme sont à {shield_percent} pourcent. L'invasion est repoussée. Excellent travail, Commandant."
        self.tts_service.speak(final_speech)
        
        if self.score > 0: self.event_video_service.set_video(VideoState.FINAL_VICTORY)
        
        self.music_service.resume_background()
        
        self.validate_button.config(state=tk.DISABLED)
        self.repeat_button.config(state=tk.DISABLED)
        self._clear_errors_frame()

        # Attribution des crédits en fin de mission si victoire (score > 0)
        if self.score > 0:
            level = self.level_var.get()
            # Barème commun à tous les jeux (commun/scoring.py) : crédits ET XP
            # pondérés par la difficulté. L'XP l'était pas avant : répéter le
            # niveau le plus facile était la façon la plus rapide de monter en
            # grade, alors que c'est se challenger qu'on veut récompenser.
            gain, xp_gain = compute_rewards(
                level, clamp_ratio(self.score, self.MAX_SCORE),
                self.LEVEL_MULTIPLIERS, self.GAME_WEIGHT,
            )
            new_record = self._record_best_score(level, self.score)
            self._award_xp(xp_gain)
            daily = self._daily_objective_check()
            if gain > 0:
                self.credits += gain
            newly = self._evaluate_badges(level, self.score, duration)
            stars = self._compute_precision_stars()
            self._update_precision_display(stars)
            self._save_profile()
            self._update_credits_label()
            self._update_helps_label()
            self._refresh_inventory_ui()
            try:
                star_text = "★ " * stars + "☆ " * (3 - stars)
                lines = [f"Niveau {level} terminé avec {shield_percent}% de bouclier.",
                         f"Précision : {star_text.strip()}"]
                if gain > 0:
                    lines.append(f"+ {gain} crédits")
                if daily:
                    bonus, streak = daily
                    lines.append(f"Objectif du jour réussi : + {bonus} crédits (série de {streak} j)")
                lines.append(f"+ {xp_gain} XP")
                if new_record:
                    lines.append("RECORD BATTU !")
                if newly:
                    names = ", ".join(self._badge_name(bid) for bid in newly)
                    lines.append(f"Nouveau(x) succès : {names}")
                messagebox.showinfo("Mission accomplie", "\n".join(lines))
            except Exception:
                pass

        if self.high_scores_enabled and self.score > 0 and self.username:
            self._save_high_score_async(self.level_var.get(), self.username, self.score, duration)

    def _save_high_score_async(self, level: str, name: str, score: int, duration: float) -> None:
        """add_score() parle au réseau (HTTP + FTP, jusqu'à ~10s de timeout, avec
        retries) : on la lance sur un thread worker pour ne pas geler l'UI en fin
        de mission, et on revient sur le thread Tk via root.after(0, ...)."""
        self.status_label.config(text="Transmission du score au Panthéon en cours...", foreground=self.colors['warning'])

        def _worker() -> None:
            error = None
            try:
                self.high_score_service.add_score(level, name, score, duration)
            except Exception as e:
                error = e

            def _deliver() -> None:
                if self._closing:
                    return
                if error is None:
                    self.status_label.config(text="Score gravé dans le Panthéon des Héros.", foreground=self.colors['accent2'])
                    messagebox.showinfo("Score Enregistré", "Votre exploit a été gravé dans le Panthéon des Héros !")
                else:
                    self.status_label.config(text="Échec de l'enregistrement du score.", foreground=self.colors['danger'])
                    messagebox.showerror("Erreur Sauvegarde", f"Impossible d'enregistrer le score :\n{error}")
            try:
                self.root.after(0, _deliver)
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=_worker, daemon=True).start()


    def start_new_dictation(self):
        self.anticheat_service.start()
        self.game_over = False
        self._sentence_penalized = False
        self._sentences_needing_correction = 0
        self._helps_used_this_dictation = 0
        self._update_precision_display(None)
        self.start_time = time.time()
        self.start_button.config(state=tk.DISABLED)
        self.status_label.config(text="DÉCRYPTAGE DE LA TRANSMISSION ENNEMIE...", foreground=self.colors['warning'])
        self.root.update()
        threading.Thread(target=self._generate_dictation_thread, daemon=True).start()

    def handle_game_over(self):
        self.anticheat_service.stop()
        self.game_over = True
        self.status_label.config(text="MISSION ÉCHOUÉE - BOUCLIERS HORS-SERVICE !", foreground=self.colors['danger'])
        self.tts_service.speak("Alerte, les boucliers sont tombés ! La ville est vulnérable ! Repli immédiat !")
        self.validate_button.config(state=tk.DISABLED)
        self.repeat_button.config(state=tk.DISABLED)
        self.music_service.resume_background()
        replay = messagebox.askyesno("Défaite", "Les boucliers de la ville sont à 0% !\n\nVoulez-vous relancer une mission ?")
        if replay:
            self.start_new_dictation()

    def _on_closing(self) -> None:
        # Doit être la toute première chose faite : tout callback différé (after/thread)
        # consulte ce drapeau avant de toucher un widget, pour éviter les erreurs
        # "invalid command name" une fois la fenêtre détruite.
        self._closing = True
        self.anticheat_service.stop()
        if self.avatar_video_service and self.avatar_video_service.player: self.avatar_video_service.player.stop()
        if self.event_video_service and self.event_video_service.player: self.event_video_service.player.stop()
        temp_audio_dir = getattr(self.tts_service, 'temp_dir', 'temp_audio')
        if os.path.exists(temp_audio_dir):
            for f in os.listdir(temp_audio_dir):
                try: os.remove(os.path.join(temp_audio_dir, f))
                except OSError as e: logger.warning("Impossible de supprimer le fichier temp %s: %s", f, e)
        try:
            if pygame.mixer.get_init():
                self.music_service.stop_background(fade_ms=500)
                pygame.mixer.quit()
        except Exception as e: logger.warning("Erreur à l'arrêt du mixer Pygame: %s", e)
        self.root.destroy()

    def _generate_dictation_thread(self) -> None:
        # Tourne sur un thread worker : l'appel réseau à Gemini ne doit jamais
        # geler la boucle Tk. Le retour vers l'UI passe systématiquement par after(0, ...).
        self.score = 20
        sentences = self.gemini_service.generate_dictation(self.level_var.get(), self.theme_var.get())
        if self._closing:
            return
        self.dictation_sentences = sentences
        try:
            self.root.after(0, self._on_dictation_generated)
        except (RuntimeError, tk.TclError):
            pass

    def _on_dictation_generated(self) -> None:
        if self._closing:
            return
        self.current_sentence_index = 0
        self.city_manager.reset()
        self.update_score_display()
        self.start_button.config(state=tk.NORMAL)
        if "Erreur" in self.dictation_sentences[0] or "Désolé" in self.dictation_sentences[0]:
            self.anticheat_service.stop()
            messagebox.showerror("Erreur IA", self.dictation_sentences[0])
            self.status_label.config(text="Erreur de transmission.", foreground=self.colors['danger'])
            self.event_video_service.set_video(VideoState.IDLE)
            return
        self.next_sentence()
        
    def lose_points(self, amount):
        if self.game_over: return
        for _ in range(amount):
            if self.score > 0:
                building_index_to_destroy = 20 - self.score
                self.city_manager.destroy_building(building_index_to_destroy)
                self.score -= 1
        self.update_score_display()
        if self.score <= 0 and not self.game_over: self.handle_game_over()
            
    def validate_sentence(self) -> None:
        if self.game_over or self._closing: return
        # Garde-fou : si un double-clic (ou un after(1500, next_sentence) en attente)
        # déclenche cette méthode alors que la dictée est déjà terminée, ne rien faire
        # plutôt que de planter sur un accès hors bornes de dictation_sentences.
        if self.current_sentence_index >= len(self.dictation_sentences): return
        # Désactivé immédiatement pour empêcher un double-clic de revalider (et de
        # pénaliser deux fois) pendant le court délai avant next_sentence().
        self.validate_button.config(state=tk.DISABLED)
        user_input = self.user_text.get("1.0", tk.END).strip()
        original_sentence = self.dictation_sentences[self.current_sentence_index].strip()

        if self._normalize_text(user_input) == self._normalize_text(original_sentence):
            self.event_video_service.set_video(VideoState.VALIDATION_SUCCESS)
            self.tts_service.speak("Transmission correcte. Boucliers stabilisés.")
            self.status_label.config(text="Décodage parfait !", foreground=self.colors['accent2'])
            self.current_sentence_index += 1
            self.root.after(1500, self.next_sentence)
        else:
            self.event_video_service.set_video(VideoState.VALIDATION_FAIL)
            self.tts_service.speak("Erreur de décodage ! Impact imminent sur les boucliers !")
            # Friction fix : on ne pénalise qu'une seule fois par phrase (1 point max),
            # même si l'élève se trompe à nouveau en corrigeant. display_errors plafonne
            # d'ailleurs la perte à 1 point quel que soit le nombre de fautes.
            penalize = not self._sentence_penalized
            self.display_errors(original_sentence, user_input, penalize=penalize)
            if penalize:
                self._sentence_penalized = True
                self._sentences_needing_correction += 1
            # L'élève doit pouvoir corriger et revalider.
            self.validate_button.config(state=tk.NORMAL)

    def display_errors(self, original: str, user: str, penalize: bool = True) -> None:
        self._clear_errors_frame(show_placeholder=False)
        self.user_text.tag_remove("error", "1.0", tk.END)
        # Tokeniser en ignorant la ponctuation, mais en conservant les positions sur le texte utilisateur
        orig_tokens = self._tokenize_words(original)
        user_tokens = self._tokenize_words(user)
        original_words = [w for w, _ in orig_tokens]
        orig_spans = [span for _, span in orig_tokens]
        user_words = [w for w, _ in user_tokens]
        user_spans = [span for _, span in user_tokens]
        # Comparaison insensible à la casse
        matcher = difflib.SequenceMatcher(
            None,
            [w.lower() for w in original_words],
            [w.lower() for w in user_words],
            autojunk=False,
        )
        mistake_count = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                continue
            mistake_count += max(i2 - i1, j2 - j1)
            if j1 < j2 and user_spans:
                start_char_index = user_spans[j1][0] if j1 < len(user_spans) else 0
                end_index_token = min(j2 - 1, len(user_spans) - 1)
                end_char_index = user_spans[end_index_token][1]
                # "1.0+Nc" (plutôt que "1.{N}") laisse Tk convertir un décalage de
                # caractères "à plat" en index ligne.colonne, y compris si l'élève a
                # tapé un retour à la ligne dans le texte (sinon les colonnes seraient
                # fausses dès la 2e ligne).
                self.user_text.tag_add("error", f"1.0+{start_char_index}c", f"1.0+{end_char_index}c")
            if tag == 'replace':
                for i in range(i1, i2):
                    if j1 + (i - i1) < j2:
                        cs, ce = user_spans[j1 + (i - i1)]
                        user_w = user_words[j1 + (i - i1)]
                        orig_w = original_words[i]
                        self._create_error_ui(
                            f"Anomalie: « {self._display_word(user, cs, ce)} »",
                            user_w,
                            orig_w,
                            char_start=cs,
                            char_end=ce,
                        )
            elif tag == 'delete':
                insert_pos = user_spans[j1][0] if (j1 < len(user_spans) and len(user) > 0) else len(user)
                for i in range(i1, i2):
                    os_, oe = orig_spans[i]
                    self._create_error_ui(
                        f"Signal manquant: « {self._display_word(original, os_, oe)} »",
                        None,
                        original_words[i],
                        insert_pos=insert_pos,
                    )
            elif tag == 'insert':
                for j in range(j1, j2):
                    cs, ce = user_spans[j]
                    user_w = user_words[j]
                    self._create_error_ui(
                        f"Signal parasite: « {self._display_word(user, cs, ce)} »",
                        user_w,
                        user_w,
                        is_insertion=True,
                        char_start=cs,
                        char_end=ce,
                    )
        if mistake_count == 0:
            # Arrive quand la seule différence est de la ponctuation ou une
            # majuscule (le comparateur de mots les ignore) : il faut le dire,
            # sinon l'élève voit un panneau vide sans comprendre pourquoi sa
            # phrase est refusée.
            self._show_no_anomaly()
        else:
            plural = "s" if mistake_count > 1 else ""
            self.status_label.config(text=f"{mistake_count} anomalie{plural} détectée{plural}.", foreground=self.colors['warning'])
            if penalize:
                # Plafond : une phrase ne fait jamais perdre plus d'un point de
                # bouclier, quel que soit le nombre de fautes détectées.
                self.lose_points(1)

    # Préfixe utilisé par GeminiService pour signaler, dans le texte même de
    # l'explication, que l'appel réseau a échoué (voir services.py). C'est le seul
    # signal disponible pour distinguer un vrai diagnostic d'un échec réseau, car
    # GeminiService avale ses propres exceptions et renvoie toujours une chaîne.
    _GEMINI_FAILURE_PREFIX = "Désolé, une erreur est survenue"

    def request_help(
        self,
        user_word: Optional[str],
        original_word: Optional[str],
        is_insertion: bool = False,
        char_start: Optional[int] = None,
        char_end: Optional[int] = None,
        insert_pos: Optional[int] = None,
        help_button: Optional[ttk.Button] = None,
    ) -> None:
        """Demande un diagnostic à Gemini pour un mot en erreur.

        L'appel réseau tourne sur un thread worker : le thread Tk ne doit jamais
        geler pendant la latence Gemini. Le bouton d'aide cliqué est désactivé
        immédiatement pour empêcher les clics multiples (et donc les appels API
        multiples facturés). Le coût (jeton gratuit ou point de bouclier) n'est
        prélevé, et le profil sauvegardé, qu'une seule fois et seulement après un
        appel réussi.
        """
        if self.game_over or self._closing: return
        if self.current_sentence_index >= len(self.dictation_sentences): return
        original_sentence = self.dictation_sentences[self.current_sentence_index]

        if help_button is not None:
            try:
                help_button.config(state=tk.DISABLED)
            except tk.TclError:
                pass
        self.status_label.config(text="Diagnostic en cours...", foreground=self.colors['warning'])

        def _worker() -> None:
            try:
                if is_insertion:
                    explanation = self.gemini_service.get_insertion_explanation(original_sentence, user_word)
                else:
                    explanation = self.gemini_service.get_error_explanation(original_sentence, original_word, user_word)
            except Exception as e:
                # GeminiService encapsule normalement ses propres erreurs, mais on se
                # protège quand même d'une exception imprévue côté réseau/SDK.
                explanation = f"{self._GEMINI_FAILURE_PREFIX} (thread aide) : {e}"

            def _deliver() -> None:
                self._on_help_ready(
                    explanation, user_word, original_word, is_insertion,
                    char_start, char_end, insert_pos, help_button, original_sentence,
                )
            try:
                self.root.after(0, _deliver)
            except (RuntimeError, tk.TclError):
                pass  # Fenêtre fermée pendant l'appel : rien à mettre à jour.

        threading.Thread(target=_worker, daemon=True).start()

    def _on_help_ready(
        self,
        explanation: str,
        user_word: Optional[str],
        original_word: Optional[str],
        is_insertion: bool,
        char_start: Optional[int],
        char_end: Optional[int],
        insert_pos: Optional[int],
        help_button: Optional[ttk.Button],
        original_sentence: str,
    ) -> None:
        """Exécuté sur le thread principal une fois la réponse Gemini reçue."""
        if self._closing: return

        failed = not explanation or explanation.startswith(self._GEMINI_FAILURE_PREFIX)
        if failed:
            self.status_label.config(text="Échec du diagnostic. Réessayez.", foreground=self.colors['danger'])
            if help_button is not None:
                try:
                    help_button.config(state=tk.NORMAL)
                except tk.TclError:
                    pass
            messagebox.showerror(
                "LIAISON INTERROMPUE",
                "Impossible de contacter le centre de diagnostic. Aucune aide ni point n'a été consommé. Réessayez, Commandant.",
            )
            return

        # Compte pour la précision (indépendant du coût crédits/jeton ci-dessous) :
        # toute aide utilisée, gratuite ou payante, signale une aide extérieure.
        self._helps_used_this_dictation += 1

        # Coût prélevé une seule fois, seulement maintenant que l'appel a réussi.
        if not self.game_over:
            if self.help_tokens > 0 and self._consume_help_from_pool():
                # _consume_help_from_pool met déjà à jour help_tokens et owned_weapons
                self._save_profile()
                self.status_label.config(text=f"Aide gratuite utilisée. Aides restantes: {self.help_tokens}", foreground=self.colors['accent2'])
                self._update_helps_label()
                self._refresh_inventory_ui()
            else:
                self.lose_points(1)
                self.status_label.config(text="Diagnostic terminé. Correction appliquée.", foreground=self.colors['muted'])

        safe_expl = self._sanitize_explanation(explanation)
        messagebox.showinfo(f"DIAGNOSTIC: '{user_word if user_word else original_word}'", safe_expl)
        try:
            current_text = self.user_text.get("1.0", tk.END)
            n = len(current_text)
            if is_insertion and char_start is not None and char_end is not None:
                s = self._clamp_index(char_start, n)
                e = self._clamp_index(char_end, n)
                if e < s: s, e = e, s
                self.user_text.delete(f"1.0+{s}c", f"1.0+{e}c")
            elif user_word and original_word and char_start is not None and char_end is not None:
                s = self._clamp_index(char_start, n)
                e = self._clamp_index(char_end, n)
                if e < s: s, e = e, s
                self.user_text.delete(f"1.0+{s}c", f"1.0+{e}c")
                self.user_text.insert(f"1.0+{s}c", original_word)
            elif not user_word and original_word and insert_pos is not None:
                pos = self._clamp_index(insert_pos, n)
                # Gestion des espaces avant/après pour éviter de coller aux mots adjacents
                before = current_text[pos-1] if pos > 0 else "\n"
                after = current_text[pos] if pos < n else "\n"
                prefix = "" if before.isspace() else " "
                suffix = "" if (after.isspace() or after in ",.;:!?\n") else " "
                self.user_text.insert(f"1.0+{pos}c", prefix + original_word + suffix)
        except tk.TclError as e:
            logger.warning("Auto-correction échouée (widget indisponible): %s", e)

        # Rafraîchir l'affichage des erreurs pour mettre à jour les indices
        updated_user_input = self.user_text.get("1.0", tk.END).strip()
        self.display_errors(original_sentence, updated_user_input, penalize=False)

    def update_score_display(self):
        shield_percent = int((self.score / 20) * 100)
        color = self.colors['accent2'] if shield_percent > 60 else self.colors['warning'] if shield_percent > 25 else self.colors['danger']
        try:
            self.score_label.config(text=f"{shield_percent}%", foreground=color)
            self.shield_meter.set_value(shield_percent)
        except tk.TclError:
            # Fenêtre en cours de fermeture : rien à rafraîchir.
            pass

    def _compute_precision_stars(self) -> int:
        """Mesure de maîtrise indépendante du score/crédits (jamais punitive,
        contrairement au bouclier qui plafonne déjà la perte à 1 point par
        phrase) : 3 étoiles = dictée réussie du premier coup sans aide, jusqu'à
        1 étoile minimum dès que la mission est terminée avec un score > 0."""
        penalty = self._sentences_needing_correction + self._helps_used_this_dictation
        return max(1, 3 - penalty)

    def _update_precision_display(self, stars: int | None) -> None:
        """Affiche les étoiles de précision à côté du bouclier. `None` = pas
        encore de dictée terminée cette session (affichage neutre)."""
        try:
            if stars is None:
                self.precision_label.config(text="☆ ☆ ☆", foreground=self.colors['muted'])
            else:
                text = "★ " * stars + "☆ " * (3 - stars)
                color = self.colors['accent2'] if stars == 3 else (
                    self.colors['warning'] if stars == 2 else self.colors['muted']
                )
                self.precision_label.config(text=text.strip(), foreground=color)
        except tk.TclError:
            pass

    def next_sentence(self) -> None:
        if self.game_over or self._closing: return
        if self.current_sentence_index < len(self.dictation_sentences):
            if self.current_sentence_index == 0: self.music_service.stop_background()
            self._sentence_penalized = False
            
            self.event_video_service.set_video(VideoState.TRANSMISSION)
            self._clear_errors_frame()
            self.user_text.config(state=tk.NORMAL)
            self.user_text.delete("1.0", tk.END)
            self.validate_button.config(state=tk.NORMAL)
            self.repeat_button.config(state=tk.NORMAL)
            sentence = self.dictation_sentences[self.current_sentence_index]
            self.status_label.config(text=f"Transmission {self.current_sentence_index + 1}/{len(self.dictation_sentences)} reçue. En attente de décodage...", foreground=self.colors['muted'])
            self.tts_service.speak(sentence, is_dictation_sentence=True)
        else:
            self.end_dictation()
            
    def repeat_sentence(self) -> None:
        if self.game_over or self._closing: return
        if self.dictation_sentences and self.current_sentence_index < len(self.dictation_sentences):
            sentence = self.dictation_sentences[self.current_sentence_index]
            self.tts_service.speak(sentence, is_dictation_sentence=True)
            
    def _clear_errors_frame(self, show_placeholder: bool = True):
        """Vide la liste des anomalies.

        `show_placeholder=False` quand on s'apprête à y écrire des anomalies :
        sinon « Aucune anomalie détectée. » restait affiché AU-DESSUS de la
        liste des anomalies, ce qui se contredisait à l'écran."""
        for widget in self.errors_list.winfo_children():
            widget.destroy()
        if show_placeholder:
            self._show_no_anomaly()

    def _show_no_anomaly(self):
        tk.Label(self.errors_list, text="Aucune anomalie détectée.",
                 bg=self.colors['panel2'], fg=self.colors['muted'],
                 font=(FONT_BODY, 10, 'italic')).pack(anchor='w', padx=4, pady=2)

    def _create_error_ui(self, label_text, user_word, original_word_for_help, is_insertion=False, help_needed=True, char_start=None, char_end=None, insert_pos=None):
        frame = tk.Frame(self.errors_list, bg=self.colors['panel2'])
        frame.pack(fill=tk.X, pady=2, padx=4)
        fg = self.colors['warning'] if is_insertion else self.colors['text']
        error_label = tk.Label(frame, text=f"> {label_text}", bg=self.colors['panel2'],
                               fg=fg, font=(FONT_MONO, 10), anchor='w', wraplength=210, justify='left')
        error_label.pack(side=tk.LEFT, expand=True, fill=tk.X)
        if help_needed:
            help_button = NeonButton(frame, text="?", variant="help", height=24, padx=10, min_width=24, bg=self.colors['panel2'])
            # btn=help_button capturé en argument par défaut : au moment du clic, la
            # variable help_button pointe déjà vers ce bouton précis, ce qui permet à
            # request_help() de le désactiver pour empêcher les clics multiples.
            help_button.config(command=lambda uw=user_word, ow=original_word_for_help, ins=is_insertion, cs=char_start, ce=char_end, ip=insert_pos, btn=help_button: self.request_help(uw, ow, ins, cs, ce, ip, btn))
            help_button.pack(side=tk.RIGHT, padx=5)

    def _update_credits_label(self):
        try:
            self.credits_var.set(f"Crédits : {self.credits}")
        except Exception:
            pass

    def _update_helps_label(self):
        try:
            self.helps_var.set(f"Aides : {self.help_tokens}")
        except Exception:
            pass

    # --- Progression : grades, XP, succès, objectif quotidien ---
    def _badge_name(self, bid: str) -> str:
        return badge_name(bid)

    def _grade_info(self):
        """(grade, grade suivant, XP dans le palier, XP requis) — calcul partagé
        avec les autres jeux et le Hub (commun/scoring.py)."""
        return grade_info(self.xp)

    def _update_xp_display(self):
        name, nxt, xp_in, xp_needed = self._grade_info()
        try:
            self.grade_label.config(text=name)
            if nxt:
                self.xp_bar.config(maximum=max(xp_needed, 1), value=xp_in)
                self.xp_text.config(text=f"{xp_in} / {xp_needed} XP")
            else:
                self.xp_bar.config(maximum=100, value=100)
                self.xp_text.config(text="Grade maximum")
        except (tk.TclError, AttributeError):
            pass

    def _award_xp(self, gain: int) -> int:
        """Crédite l'XP déjà calculée par le barème commun (compute_rewards) —
        ne recalcule rien ici, pour qu'il n'existe qu'une seule formule."""
        gain = max(0, int(gain or 0))
        self.xp += gain
        self._update_xp_display()
        return gain

    def _record_best_score(self, level: str, score: int) -> bool:
        prev = int(self.best_scores.get(level, 0) or 0)
        if score > prev:
            self.best_scores[level] = score
            return True
        return False

    def _evaluate_badges(self, level: str, score: int, duration: float) -> list:
        newly = []

        def unlock(bid):
            if bid not in self.badges:
                self.badges.append(bid)
                newly.append(bid)

        if score > 0:
            unlock("premiere_victoire")
        if score >= 20:
            unlock("sans_faute")
            slug = self._LEVEL_SLUGS.get(level)
            if slug:
                unlock(f"sans_faute_{slug}")
        if score > 0 and duration is not None and 0 <= duration <= self.ECLAIR_MAX_SECONDS:
            unlock("eclair")
        if level == "Collège" and score > 0:
            unlock("grand_strategie")
        if level not in self.levels_played:
            self.levels_played.append(level)
        if len(self.levels_played) >= len(self.DIFFICULTY_LEVELS):
            unlock("explorateur")
        if self.credits >= self.RICH_CREDITS_THRESHOLD:
            unlock("riche")
        # Paliers de série quotidienne : self.streak est déjà à jour à ce stade
        # (_daily_objective_check tourne avant _evaluate_badges dans end_dictation).
        for milestone in self.STREAK_MILESTONES:
            if self.streak >= milestone:
                unlock(f"streak_{milestone}")
        return newly

    def _daily_objective_check(self):
        """Valide l'objectif du jour (1 dictée/jour). Retourne (bonus, streak) ou None."""
        today = date.today().isoformat()
        if self.last_play_date == today:
            return None
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.streak = (self.streak + 1) if self.last_play_date == yesterday else 1
        self.last_play_date = today
        bonus = min(
            self.DAILY_BONUS_BASE + self.DAILY_BONUS_PER_STREAK * (self.streak - 1),
            self.DAILY_BONUS_CAP,
        )
        self.credits += bonus
        return bonus, self.streak

    def _show_badges(self):
        c = self.colors
        win = tk.Toplevel(self.root)
        win.title("Succès & Progression")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=c['bg'])

        name, nxt, xp_in, xp_needed = self._grade_info()
        info = f"Grade : {name}"
        if nxt:
            info += f"   ·   {xp_in}/{xp_needed} XP vers {nxt}"
        info += f"   ·   Série : {self.streak} jour(s)   ·   Crédits : {self.credits}"
        tk.Label(win, text=info, bg=c['bg'], fg=c['accent2'],
                 font=(FONT_DISPLAY, 11, 'bold')).pack(padx=16, pady=(14, 10), anchor='w')

        unlocked = set(self.badges)
        for b in self.BADGES:
            done = b["id"] in unlocked
            marker = "✓" if done else "○"
            fg = c['accent2'] if done else c['muted']
            row = tk.Frame(win, bg=c['panel2'])
            row.pack(fill=tk.X, padx=16, pady=3)
            tk.Label(row, text=f"{marker}  {b['name']}", bg=c['panel2'], fg=fg,
                     font=(FONT_DISPLAY, 10, 'bold'), anchor='w').pack(side=tk.LEFT, padx=6)
            tk.Label(row, text=b['desc'], bg=c['panel2'], fg=c['text'],
                     font=(FONT_BODY, 9), anchor='w').pack(side=tk.LEFT, padx=6)

        btns = tk.Frame(win, bg=c['bg'])
        btns.pack(fill=tk.X, padx=16, pady=12)
        NeonButton(btns, text="Fermer", command=win.destroy, variant="ghost", bg=c['bg'], height=32).pack(side=tk.RIGHT)

    # --- Gestion des armes et images ---
    def _weapon_spec(self, key: str):
        for it in self.SHOP_ITEMS:
            if it['key'] == key:
                return it
        return None

    def _recompute_total_help_tokens(self):
        self.help_tokens = sum(int(v) for v in self.weapon_help_pool.values()) if isinstance(self.weapon_help_pool, dict) else 0

    def _get_weapon_image(self, weapon_key: str, size=(36, 36)):
        # Recherche d'image: assets/images/{weapon_key}.png|jpg
        try:
            if weapon_key in self.weapon_image_cache:
                return self.weapon_image_cache[weapon_key]
            base_dir = os.path.join('assets', 'images')
            candidates = [
                os.path.join(base_dir, f"{weapon_key}.png"),
                os.path.join(base_dir, f"{weapon_key}.jpg"),
                os.path.join(base_dir, f"{weapon_key}.jpeg"),
            ]
            img_path = next((p for p in candidates if os.path.exists(p)), None)
            if not img_path:
                return None
            im = Image.open(img_path)
            im = im.resize(size, Image.Resampling.LANCZOS)
            ph = ImageTk.PhotoImage(im)
            self.weapon_image_cache[weapon_key] = ph
            return ph
        except Exception:
            return None

    def _consume_help_from_pool(self) -> bool:
        """Consomme 1 aide depuis le pool d'armes et ajuste owned_weapons.
        Retourne True si une aide a été consommée, sinon False.
        Politique: consommer d'abord l'arme au palier le plus élevé (helps max).
        """
        if not isinstance(self.weapon_help_pool, dict) or self.help_tokens <= 0:
            return False
        # Trier les armes par capacité d'aide décroissante
        sorted_items = sorted(self.SHOP_ITEMS, key=lambda it: int(it['helps']), reverse=True)
        for it in sorted_items:
            key = it['key']
            pool = int(self.weapon_help_pool.get(key, 0))
            if pool > 0:
                self.weapon_help_pool[key] = pool - 1
                # Recalcul des unités possédées basé sur le pool restant
                helps_per = int(it['helps'])
                new_units = int(math.ceil(max(self.weapon_help_pool.get(key, 0), 0) / helps_per)) if helps_per > 0 else 0
                self.owned_weapons[key] = new_units
                # Resynchroniser le total
                self._recompute_total_help_tokens()
                return True
        return False

    def _refresh_inventory_ui(self):
        c = self.colors
        # Effacer le contenu et réafficher l'inventaire
        for w in self.inventory_content.winfo_children():
            w.destroy()
        tk.Label(self.inventory_content, text=f"Aides gratuites : {self.help_tokens}",
                 bg=c['panel2'], fg=c['accent2'], font=(FONT_DISPLAY, 10, 'bold')).pack(anchor='w', padx=2, pady=(0, 2))
        # Détail des armes possédées
        has_any = False
        for item in self.SHOP_ITEMS:
            count = int(self.owned_weapons.get(item['key'], 0))
            if count > 0:
                has_any = True
                row = tk.Frame(self.inventory_content, bg=c['panel2'])
                row.pack(fill=tk.X, anchor='w', pady=1)
                img = self._get_weapon_image(item['key'])
                if img is not None:
                    lbl_img = tk.Label(row, image=img, bg=c['panel2'])
                    lbl_img.image = img  # éviter GC
                    lbl_img.pack(side=tk.LEFT, padx=(2, 8))
                tk.Label(row, text=f"{item['name']}  ×{count}", bg=c['panel2'],
                         fg=c['muted'], font=(FONT_BODY, 10)).pack(side=tk.LEFT)
        if not has_any:
            tk.Label(self.inventory_content, text="Aucune arme achetée", bg=c['panel2'],
                     fg=c['muted'], font=(FONT_BODY, 10, 'italic')).pack(anchor='w', padx=2)
        if hasattr(self, 'inventory_panel'):
            self.inventory_panel.fit_height()

    def _open_shop(self):
        c = self.colors
        shop = tk.Toplevel(self.root)
        shop.title("Boutique d'Armement")
        shop.transient(self.root)
        shop.grab_set()
        shop.configure(bg=c['bg'])

        header = tk.Frame(shop, bg=c['bg'])
        header.pack(fill=tk.X, padx=16, pady=(14, 6))
        tk.Label(header, text="BOUTIQUE D'ARMEMENT", bg=c['bg'], fg=c['text_strong'],
                 font=(FONT_DISPLAY, 14, 'bold')).pack(side=tk.LEFT)
        credits_lbl = tk.Label(header, text=f"Crédits : {self.credits}", bg=c['bg'],
                               fg=c['accent2'], font=(FONT_DISPLAY, 11, 'bold'))
        credits_lbl.pack(side=tk.RIGHT)

        list_frame = tk.Frame(shop, bg=c['panel2'])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)

        for item in self.SHOP_ITEMS:
            row = tk.Frame(list_frame, bg=c['panel2'])
            row.pack(fill=tk.X, padx=8, pady=6)
            owned_count = int(self.owned_weapons.get(item['key'], 0))
            img = self._get_weapon_image(item['key'])
            if img is not None:
                lbl_img = tk.Label(row, image=img, bg=c['panel2'])
                lbl_img.image = img
                lbl_img.pack(side=tk.LEFT, padx=(0, 8))
            tk.Label(row, text=item['name'], bg=c['panel2'], fg=c['text'],
                     font=(FONT_BODY, 11)).pack(side=tk.LEFT)
            tk.Label(row, text=f"Prix : {item['price']}   ·   +{item['helps']} aide(s)", bg=c['panel2'],
                     fg=c['muted'], font=(FONT_BODY, 10)).pack(side=tk.LEFT, padx=10)
            owned_label = tk.Label(row, text=f"Possédé : {owned_count}", bg=c['panel2'],
                                   fg=c['accent2'], font=(FONT_BODY, 10))
            owned_label.pack(side=tk.LEFT, padx=10)
            buy_btn = NeonButton(row, text="Acheter", variant="primary",
                                 command=lambda it=item, ol=owned_label: self._buy_item(it, credits_lbl, helps_lbl, ol),
                                 bg=c['panel2'], height=30)
            buy_btn.pack(side=tk.RIGHT)

        footer = tk.Frame(shop, bg=c['bg'])
        footer.pack(fill=tk.X, padx=16, pady=(6, 14))
        helps_lbl = tk.Label(footer, text=f"Aides gratuites disponibles : {self.help_tokens}", bg=c['bg'],
                             fg=c['accent2'], font=(FONT_DISPLAY, 10, 'bold'))
        helps_lbl.pack(side=tk.LEFT)
        NeonButton(footer, text="Fermer", command=shop.destroy, variant="ghost", bg=c['bg'], height=30).pack(side=tk.RIGHT)

        # Centrer la fenêtre
        shop.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - shop.winfo_reqwidth()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - shop.winfo_reqheight()) // 2
        shop.geometry(f"+{x}+{y}")

    def _buy_item(self, item, credits_label_widget, helps_label_widget=None, owned_label_widget=None):
        price = int(item['price'])
        if self.credits < price:
            messagebox.showwarning("Crédits insuffisants", "Vous n'avez pas assez de crédits pour cet achat.")
            return
        self.credits -= price
        helps_per = int(item['helps'])
        # Mettre à jour le pool d'aides par arme et recalculer le total + possession
        current_pool = int(self.weapon_help_pool.get(item['key'], 0)) if isinstance(self.weapon_help_pool, dict) else 0
        self.weapon_help_pool[item['key']] = current_pool + helps_per
        # Re-synchroniser total et unités
        self._recompute_total_help_tokens()
        # unités = ceil(pool/helps_per)
        pool_for_key = int(self.weapon_help_pool.get(item['key'], 0))
        new_units = int(math.ceil(pool_for_key / helps_per)) if helps_per > 0 else 0
        self.owned_weapons[item['key']] = new_units
        self._save_profile()
        self._update_credits_label()
        self._update_helps_label()
        self._refresh_inventory_ui()
        try:
            credits_label_widget.config(text=f"Crédits : {self.credits}")
        except Exception:
            pass
        if helps_label_widget is not None:
            try:
                helps_label_widget.config(text=f"Aides gratuites disponibles : {self.help_tokens}")
            except Exception:
                pass
        if owned_label_widget is not None:
            try:
                owned_label_widget.config(text=f"Possédé : {int(self.owned_weapons.get(item['key'], 0))}")
            except Exception:
                pass
        messagebox.showinfo("Achat effectué", f"Vous avez acheté: {item['name']}\nAides gratuites totales: {self.help_tokens}")

if __name__ == "__main__":
    try:
        # Le jeu se lance sans console (pythonw, voir LANCER.bat) : sans journal
        # fichier, une erreur au démarrage serait totalement invisible.
        setup_file_logging(_HERE)
        load_dotenv()
        root = tk.Tk()
        log_tk_exceptions(root)
        root.withdraw()
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or "REMPLACEZ" in api_key:
            messagebox.showerror("Erreur Critique", "Clé API Gemini non trouvée ou non configurée dans le fichier .env")
            root.destroy()
            sys.exit(1)
        
        gemini_service = GeminiService(api_key)
        tts_service = TTSService()
        anticheat_service = AntiCheatService()
        music_service = MusicService()
        
        app = DictationApp(root, gemini_service, tts_service, anticheat_service, music_service)
        root.deiconify()
        root.mainloop()

    except ConnectionError as e:
        logger.error("Démarrage impossible (connexion) : %s", e)
        messagebox.showerror("Erreur de Connexion", str(e))
    except Exception as e:
        logger.exception("Erreur critique au démarrage")
        messagebox.showerror("Erreur Inattendue", f"Une erreur critique est survenue au démarrage: {e}")
        if 'anticheat_service' in locals() and anticheat_service: anticheat_service.stop()