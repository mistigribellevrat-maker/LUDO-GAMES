# main.py
"""TOURELLE DE DÉFENSE — jeu de conjugaison.

Des vaisseaux ennemis approchent d'un dôme central, chacun affichant une
forme conjuguée (une correcte, plusieurs leurres qui sont d'autres formes
réelles du même verbe à un autre temps). Le joueur vise à la souris et tire
sur le bon vaisseau avant qu'un vaisseau n'atteigne le dôme (5 niveaux, un
temps dominant par niveau — voir conjugation_data.py/problems.py). 2 échecs
autorisés avant la défaite. Aucun appel IA : le contenu vient d'une table de
conjugaison curée à la main (voir conjugation_data.py).
"""

import json
import logging
import os
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

import pygame
from PIL import Image, ImageTk

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

from theme import PALETTE, FONT_DISPLAY, FONT_BODY, FONT_MONO
from ui_widgets import NeonButton, RoundedFrame, SectionHeader, SegmentedControl, ShieldMeter
from server_client import HighScoreService
from scoring import GRADES as SHARED_GRADES, grade_name
from badges import badge_name
from video import play_intro
from logs import log_tk_exceptions, setup_file_logging

from conjugation_data import PRONOUN_LABELS, TENSE_LABELS
from problems import (
    LEVELS, FLIGHT_TIME_S, SEGMENTS, ConjugationMission, compute_rewards, evaluate_badges,
)
from ui_components import TurretScene, ConjugationHighScoreWindow
from ui_extras import CommandBackdrop, IconBadge, StatChip, LEVEL_ICONS

logger = logging.getLogger(__name__)


class ConjugaisonApp:
    LEVELS = LEVELS

    # Grades partagés avec tous les jeux (commun/scoring.py) : l'XP est une
    # progression globale, un même total doit donner le même titre partout.
    GRADES = SHARED_GRADES

    # Catalogue de la boutique : chaque achat ajoute `helps` charges
    # utilisables en mission (voir _buy_item/_consume_charge). L'inventaire
    # (`shop_charges`) est local au jeu, comme l'inventaire d'armes de la
    # dictée ; seuls les crédits (globaux) sont synchronisés au serveur.
    SHOP_ITEMS = [
        {"key": "traqueur", "name": "Traqueur de cible", "price": 150, "helps": 1,
         "icon": "🎯", "effect": "Le bon vaisseau clignote 3 s au début de la vague"},
        {"key": "bouclier", "name": "Coque renforcée", "price": 200, "helps": 1,
         "icon": "🛡", "effect": "+1 échec autorisé pour la mission"},
        {"key": "ralenti", "name": "Propulsion ralentie", "price": 150, "helps": 1,
         "icon": "🐢", "effect": "+2 s de vol pour la vague en cours"},
    ]

    # Délai d'affichage de l'écran de résultat avant passage automatique au
    # jeu suivant (mode campagne).
    CAMPAIGN_RESULT_DELAY_S = 10

    def __init__(self, root: tk.Tk, campaign: bool = False) -> None:
        self.root = root
        # Mode campagne (lancé par le Hub avec --campagne) : l'écran de
        # résultat se referme tout seul pour laisser le jeu suivant démarrer.
        self.campaign_mode = campaign
        self._campaign_close_after_id: str | None = None
        self.root.title("TOURELLE DE DÉFENSE // SECTEUR LINGUISTIQUE")
        self.root.geometry("1100x750")
        self.root.minsize(900, 650)
        self.root.configure(bg=PALETTE["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.username = None
        self.player_id = None
        self.avatar_path = None
        self.best_scores: dict[str, int] = {}
        # Progression globale, partagée avec les autres jeux (voir commun/server_client.py).
        self.credits = 0
        self.xp = 0
        self.badges: list[str] = []
        self.streak = 0
        self.last_play_date = ""
        # Charges de boutique possédées (inventaire local, voir SHOP_ITEMS).
        self.shop_charges: dict[str, int] = {}
        self.profile_path = os.path.join(os.getcwd(), "user_profile.json")

        self._intro_spoken = False
        self._avatar_thumb_cache: dict[str, ImageTk.PhotoImage] = {}

        self.high_score_service = None
        self.high_scores_enabled = True
        self._reinit_high_score_service(warn_on_failure=True)

        self._load_profile()
        if not self.username:
            self.username = self._ask_username() or "Commandant"
            self._save_profile()

        self.content = CommandBackdrop(self.root, bg=PALETTE["bg"])
        self.content.pack(fill=tk.BOTH, expand=True)

        self.mission: ConjugationMission | None = None
        self._mission_start_time = 0.0

        self.show_intro()
        self._identify_with_server()

    # --- Profil local (léger : juste pseudo + meilleurs scores) -----------

    def _load_profile(self) -> None:
        if not os.path.exists(self.profile_path):
            return
        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
        except (json.JSONDecodeError, OSError):
            return
        self.username = data.get("username") or None
        self.avatar_path = data.get("avatar_path")
        if self.avatar_path and not os.path.exists(self.avatar_path):
            self.avatar_path = None
        best = data.get("best_scores")
        self.best_scores = best if isinstance(best, dict) else {}
        self.credits = int(data.get("credits", 0) or 0)
        self.xp = int(data.get("xp", 0) or 0)
        badges = data.get("badges")
        self.badges = badges if isinstance(badges, list) else []
        self.streak = int(data.get("streak", 0) or 0)
        self.last_play_date = data.get("last_play_date") or ""
        charges = data.get("shop_charges")
        self.shop_charges = charges if isinstance(charges, dict) else {}

    def _save_profile(self) -> None:
        data = {
            "username": self.username,
            "avatar_path": self.avatar_path,
            "best_scores": self.best_scores,
            "credits": self.credits,
            "xp": self.xp,
            "badges": self.badges,
            "streak": self.streak,
            "last_play_date": self.last_play_date,
            "shop_charges": self.shop_charges,
        }
        tmp_path = f"{self.profile_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.profile_path)
        except OSError as e:
            logger.warning("Impossible d'enregistrer le profil: %s", e)
        self._sync_profile_to_server()

    def _sync_profile_to_server(self) -> None:
        if not self.high_scores_enabled or not self.username:
            return
        service = self.high_score_service
        name = self.username
        payload = {"best_scores": self.best_scores}
        global_progress = {
            "credits": self.credits,
            "xp": self.xp,
            "badges": self.badges,
            "streak": self.streak,
            "last_play_date": self.last_play_date,
        }

        def _worker() -> None:
            try:
                service.save_profile(name, payload, **global_progress)
            except Exception as e:
                logger.warning("Synchronisation du profil vers le serveur échouée: %s", e)

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    # --- Serveur de scores --------------------------------------------------

    def _reinit_high_score_service(self, warn_on_failure: bool = False) -> None:
        try:
            self.high_score_service = HighScoreService()
            self.high_scores_enabled = True
        except Exception as e:
            self.high_score_service = None
            self.high_scores_enabled = False
            if warn_on_failure:
                messagebox.showwarning(
                    "Scores désactivés",
                    f"Impossible d'initialiser le service des scores.\n{e}\n"
                    "Le classement ne sera pas disponible.",
                )

    def _identify_with_server(self) -> None:
        if not self.high_scores_enabled or not self.username:
            return

        def _worker() -> None:
            info, error = None, None
            try:
                info = self.high_score_service.identify(self.username, avatar_path=self.avatar_path)
            except Exception as e:
                error = e

            def _apply() -> None:
                if info is not None and info.get("player_id"):
                    self.player_id = info.get("player_id")
                    profile = info.get("profile")
                    if isinstance(profile, dict):
                        best = profile.get("best_scores")
                        if isinstance(best, dict):
                            self.best_scores = best
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
                    self._refresh_avatar_display()
                if error is not None:
                    logger.warning("Identification auprès du serveur échouée: %s", error)

            try:
                self.root.after(0, _apply)
            except (RuntimeError, tk.TclError):
                pass

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    # --- Identité (premier lancement) --------------------------------------

    def _ask_username(self) -> str | None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Identification")
        dialog.configure(bg=PALETTE["bg"])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        tk.Label(dialog, text="Identifiant du Commandant", bg=PALETTE["bg"], fg=PALETTE["accent"],
                 font=(FONT_DISPLAY, 12, "bold")).pack(padx=20, pady=(18, 8))
        name_var = tk.StringVar(value="Commandant")
        entry = ttk.Entry(dialog, textvariable=name_var, width=28)
        entry.pack(padx=20, pady=(0, 16))
        entry.focus_set()

        result = {"name": None}

        def confirm() -> None:
            result["name"] = name_var.get().strip() or "Commandant"
            dialog.destroy()

        NeonButton(dialog, text="Confirmer", command=confirm, variant="solid",
                   bg=PALETTE["bg"], height=34).pack(pady=(0, 18))
        dialog.bind("<Return>", lambda e: confirm())
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.wait_window()
        return result["name"]

    # --- Avatar --------------------------------------------------------

    def _avatar_thumbnail_path(self) -> str | None:
        if not self.avatar_path:
            return None
        base = os.path.splitext(os.path.basename(self.avatar_path))[0]
        img_path = os.path.join(os.path.dirname(self.avatar_path), f"{base}.jpg")
        return img_path if os.path.exists(img_path) else None

    def _get_avatar_photo(self, size=(96, 96)) -> ImageTk.PhotoImage | None:
        img_path = self._avatar_thumbnail_path()
        if not img_path:
            return None
        cache_key = f"{img_path}:{size}"
        if cache_key in self._avatar_thumb_cache:
            return self._avatar_thumb_cache[cache_key]
        try:
            im = Image.open(img_path).resize(size, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(im)
        except (OSError, ValueError):
            return None
        self._avatar_thumb_cache[cache_key] = photo
        return photo

    def _build_avatar_portrait(self, parent, size=(96, 96)) -> tk.Widget:
        """Portrait du joueur dans un anneau circulaire accent : vignette
        réelle si un avatar est choisi, sinon un médaillon générique aux
        initiales (jamais d'écran vide)."""
        w, h = size
        canvas = tk.Canvas(parent, width=w, height=h, bg=PALETTE["panel2"], highlightthickness=0)
        photo = self._get_avatar_photo(size)
        if photo is not None:
            canvas.image = photo
            canvas.create_image(w / 2, h / 2, image=photo)
        else:
            initial = (self.username or "?")[0].upper()
            canvas.create_oval(3, 3, w - 3, h - 3, fill=PALETTE["panel3"], outline="")
            canvas.create_text(w / 2, h / 2, text=initial, fill=PALETTE["accent_hi"],
                                font=(FONT_DISPLAY, int(h * 0.4), "bold"))
        canvas.create_oval(3, 3, w - 3, h - 3, fill="", outline=PALETTE["accent"], width=2)
        return canvas

    def _refresh_avatar_display(self) -> None:
        # Les écrans se reconstruisent entièrement à chaque affichage (show_intro/
        # start_mission relisent l'avatar courant) : rien à faire de plus ici que
        # de vider le cache si l'avatar vient de changer.
        pass

    # --- Écrans ----------------------------------------------------------

    def _clear_content(self) -> None:
        for widget in self.content.winfo_children():
            widget.destroy()

    def show_intro(self) -> None:
        self._clear_content()
        c = self.content

        header = tk.Frame(c, bg=PALETTE["bg"])
        header.pack(fill=tk.X, padx=28, pady=(24, 8))
        self._build_avatar_portrait(header, size=(72, 72)).pack(side=tk.LEFT, padx=(0, 16))
        title_box = tk.Frame(header, bg=PALETTE["bg"])
        title_box.pack(side=tk.LEFT, anchor="w")
        SectionHeader(title_box, eyebrow="Transmission entrante", title=f"Commandant {self.username}",
                      bg=PALETTE["bg"]).pack(anchor="w")
        stats_row = tk.Frame(title_box, bg=PALETTE["bg"])
        stats_row.pack(anchor="w", pady=(6, 0))
        StatChip(stats_row, "GRADE", self._grade_name(), width=150).pack(side=tk.LEFT, padx=(0, 8))
        self._credits_chip = StatChip(stats_row, "CRÉDITS", self.credits, width=110)
        self._credits_chip.pack(side=tk.LEFT)

        panel = RoundedFrame(c, padding=20, bg=PALETTE["bg"])
        panel.pack(fill=tk.X, padx=28, pady=12)

        level_row = tk.Frame(panel.inner, bg=PALETTE["panel2"])
        level_row.pack(anchor="w", fill=tk.X, pady=(0, 16))
        self._level_badge = IconBadge(level_row, LEVEL_ICONS[LEVELS[0]], diameter=32)
        self._level_badge.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(level_row, text="Niveau :", bg=PALETTE["panel2"], fg=PALETTE["accent"],
                 font=(FONT_DISPLAY, 10, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        self.level_var = tk.StringVar(value=LEVELS[0])
        SegmentedControl(level_row, LEVELS, self.level_var, bg=PALETTE["panel2"]).pack(side=tk.LEFT)
        self._record_chip = StatChip(level_row, "RECORD", self._best_score_value(), width=110)
        self._record_chip.pack(side=tk.RIGHT)

        def _on_level_change(*_a):
            self._record_chip.update(self._best_score_value())
            self._level_badge.set_icon(LEVEL_ICONS[self.level_var.get()])
        self.level_var.trace_add("write", _on_level_change)

        btn_row = tk.Frame(panel.inner, bg=PALETTE["panel2"])
        btn_row.pack(anchor="w")
        NeonButton(btn_row, text="🎯 Lancer la défense", command=self.start_mission,
                   variant="solid", bg=PALETTE["panel2"], height=44).pack(side=tk.LEFT, padx=(0, 10))
        NeonButton(btn_row, text="Panthéon", command=self._open_high_scores,
                   variant="ghost", bg=PALETTE["panel2"], height=44).pack(side=tk.LEFT)
        NeonButton(btn_row, text="Boutique", command=self._open_shop,
                   variant="ghost", bg=PALETTE["panel2"], height=44).pack(side=tk.LEFT, padx=(6, 0))

        # Intro vidéo 16/9 en pop-up : elle remplace le briefing parlé par
        # défaut (la vidéo fait déjà l'accueil, voir commun/video.py::play_intro).
        # En mode campagne, on la saute : le Hub enchaîne les jeux tout seul,
        # une intro à chaque lancement ralentirait l'enchaînement.
        if not self._intro_spoken and not self.campaign_mode:
            self._intro_spoken = True
            self._play_intro_video()

    # Intro jouée au démarrage : déposer le fichier à cet emplacement suffit à
    # l'activer, aucun réglage à faire.
    INTRO_VIDEO_PATH = os.path.join("assets", "videos", "intro.mp4")

    def _play_intro_video(self) -> None:
        play_intro(
            self.root,
            os.path.join(_HERE, self.INTRO_VIDEO_PATH),
            bg=PALETTE["bg"],
            hint_fg=PALETTE["muted"],
            font=(FONT_BODY, 9, "italic"),
        )

    # Vidéos de fin de mission (victoire/défaite) : déposer le fichier à cet
    # emplacement suffit à l'activer (voir commun/video.py::play_intro — sans
    # fichier, rien ne se passe, l'écran de résultat s'affiche normalement).
    RESULT_VIDEO_PATH = {
        True: os.path.join("assets", "videos", "victoire.mp4"),
        False: os.path.join("assets", "videos", "defaite.mp4"),
    }

    def _play_result_video(self, victory: bool) -> None:
        play_intro(
            self.root,
            os.path.join(_HERE, self.RESULT_VIDEO_PATH[victory]),
            bg=PALETTE["bg"],
            hint_fg=PALETTE["muted"],
            font=(FONT_BODY, 9, "italic"),
        )

    def _grade_name(self) -> str:
        """Grade militaire correspondant à l'XP courante. Le calcul vit dans
        commun/scoring.py, partagé avec les autres jeux : l'XP est une
        progression globale, un même total doit afficher le même titre partout."""
        return grade_name(self.xp)

    def _best_score_value(self) -> str:
        best = self.best_scores.get(self.level_var.get())
        if best is None:
            return "—"
        return f"{best}/{SEGMENTS}"

    def _open_high_scores(self) -> None:
        if self.high_scores_enabled:
            ConjugationHighScoreWindow(self.root, self.high_score_service, PALETTE)
        else:
            messagebox.showerror("Erreur", "Le service du classement n'est pas disponible.")

    # --- Boutique --------------------------------------------------------

    def _update_credits_chip(self) -> None:
        chip = getattr(self, "_credits_chip", None)
        if chip is not None:
            try:
                chip.update(self.credits)
            except tk.TclError:
                pass

    def _open_shop(self) -> None:
        c = PALETTE
        shop = tk.Toplevel(self.root)
        shop.title("Boutique d'Améliorations")
        shop.transient(self.root)
        shop.grab_set()
        shop.configure(bg=c["bg"])

        header = tk.Frame(shop, bg=c["bg"])
        header.pack(fill=tk.X, padx=16, pady=(14, 6))
        tk.Label(header, text="BOUTIQUE D'AMÉLIORATIONS", bg=c["bg"], fg=c["text_strong"],
                 font=(FONT_DISPLAY, 14, "bold")).pack(side=tk.LEFT)
        credits_lbl = tk.Label(header, text=f"Crédits : {self.credits}", bg=c["bg"],
                               fg=c["accent2"], font=(FONT_DISPLAY, 11, "bold"))
        credits_lbl.pack(side=tk.RIGHT)

        list_frame = tk.Frame(shop, bg=c["panel2"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)

        for item in self.SHOP_ITEMS:
            row = tk.Frame(list_frame, bg=c["panel2"])
            row.pack(fill=tk.X, padx=8, pady=6)
            tk.Label(row, text=item["icon"], bg=c["panel2"],
                     font=(FONT_DISPLAY, 16)).pack(side=tk.LEFT, padx=(0, 8))
            name_box = tk.Frame(row, bg=c["panel2"])
            name_box.pack(side=tk.LEFT)
            tk.Label(name_box, text=item["name"], bg=c["panel2"], fg=c["text"],
                     font=(FONT_BODY, 11)).pack(anchor="w")
            tk.Label(name_box, text=item["effect"], bg=c["panel2"], fg=c["muted"],
                     font=(FONT_BODY, 9)).pack(anchor="w")
            owned_label = tk.Label(row, text=f"Possédé : {int(self.shop_charges.get(item['key'], 0))}",
                                   bg=c["panel2"], fg=c["accent2"], font=(FONT_BODY, 10))
            owned_label.pack(side=tk.LEFT, padx=10)
            buy_btn = NeonButton(row, text=f"Acheter — {item['price']} crédits", variant="primary",
                                 command=lambda it=item, ol=owned_label: self._buy_item(it, credits_lbl, ol),
                                 bg=c["panel2"], height=30)
            buy_btn.pack(side=tk.RIGHT)

        footer = tk.Frame(shop, bg=c["bg"])
        footer.pack(fill=tk.X, padx=16, pady=(6, 14))
        NeonButton(footer, text="Fermer", command=shop.destroy, variant="ghost",
                   bg=c["bg"], height=30).pack(side=tk.RIGHT)

        shop.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - shop.winfo_reqwidth()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - shop.winfo_reqheight()) // 2
        shop.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _buy_item(self, item: dict, credits_label_widget=None, owned_label_widget=None) -> None:
        price = int(item["price"])
        if self.credits < price:
            messagebox.showwarning("Crédits insuffisants", "Vous n'avez pas assez de crédits pour cet achat.")
            return
        self.credits -= price
        key = item["key"]
        self.shop_charges[key] = int(self.shop_charges.get(key, 0)) + int(item["helps"])
        self._save_profile()
        self._update_credits_chip()
        if credits_label_widget is not None:
            try:
                credits_label_widget.config(text=f"Crédits : {self.credits}")
            except tk.TclError:
                pass
        if owned_label_widget is not None:
            try:
                owned_label_widget.config(text=f"Possédé : {int(self.shop_charges.get(key, 0))}")
            except tk.TclError:
                pass
        messagebox.showinfo("Achat effectué", f"Vous avez acheté : {item['name']}\nCharges : {int(item['helps'])}")

    def _consume_charge(self, key: str) -> None:
        current = int(self.shop_charges.get(key, 0))
        if current <= 0:
            return
        self.shop_charges[key] = current - 1
        self._save_profile()
        self._refresh_boost_buttons()

    # --- Bonus de boutique en mission ------------------------------------

    def _use_traqueur(self) -> None:
        if self.mission is None or self.mission.finished:
            return
        if int(self.shop_charges.get("traqueur", 0)) <= 0:
            return
        self.turret_scene.highlight_correct(3.0)
        self._consume_charge("traqueur")

    def _use_bouclier(self) -> None:
        if self.mission is None or self.mission.finished:
            return
        if int(self.shop_charges.get("bouclier", 0)) <= 0:
            return
        self.mission.max_mistakes += 1
        self._consume_charge("bouclier")
        self._refresh_mission_labels()

    def _use_ralenti(self) -> None:
        if self.mission is None or self.mission.finished:
            return
        if int(self.shop_charges.get("ralenti", 0)) <= 0:
            return
        self.turret_scene.slow_ships(2.0)
        self._consume_charge("ralenti")

    def _refresh_boost_buttons(self) -> None:
        buttons = getattr(self, "_boost_buttons", {})
        if not buttons:
            return
        finished = self.mission is not None and self.mission.finished
        for key, btn in buttons.items():
            has_charge = int(self.shop_charges.get(key, 0)) > 0
            btn.set_state(tk.NORMAL if has_charge and not finished else tk.DISABLED)

    def start_mission(self) -> None:
        level = self.level_var.get()
        self.mission = ConjugationMission(level=level)
        self._mission_start_time = time.time()
        self._build_battle_screen(level)

    def _build_battle_screen(self, level: str) -> None:
        self._clear_content()
        c = self.content

        top = tk.Frame(c, bg=PALETTE["bg"])
        top.pack(fill=tk.X, padx=24, pady=(18, 6))
        self._build_avatar_portrait(top, size=(56, 56)).pack(side=tk.LEFT, padx=(0, 12))
        info = tk.Frame(top, bg=PALETTE["bg"])
        info.pack(side=tk.LEFT, anchor="w", fill=tk.X, expand=True, padx=(0, 12))
        level_title_row = tk.Frame(info, bg=PALETTE["bg"])
        level_title_row.pack(anchor="w")
        IconBadge(level_title_row, LEVEL_ICONS.get(level, "🎯"), diameter=26).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(level_title_row, text=f"NIVEAU {level.upper()}", bg=PALETTE["bg"], fg=PALETTE["accent"],
                 font=(FONT_DISPLAY, 10, "bold")).pack(side=tk.LEFT)
        self.progress_label = tk.Label(info, text="", bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                                        font=(FONT_DISPLAY, 12, "bold"))
        self.progress_label.pack(anchor="w")
        self._shield_meter = ShieldMeter(info, height=12, bg=PALETTE["bg"])
        self._shield_meter.pack(anchor="w", fill=tk.X, pady=(4, 0))
        NeonButton(top, text="Abandonner", command=self.show_intro, variant="ghost",
                   bg=PALETTE["bg"], height=30).pack(side=tk.RIGHT)

        self.prompt_label = tk.Label(c, text="", bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                                      font=(FONT_MONO, 15, "bold"))
        self.prompt_label.pack(pady=(2, 4))

        boost_row = tk.Frame(c, bg=PALETTE["bg"])
        boost_row.pack(pady=(0, 4))
        self._boost_buttons = {}

        def _make_boost(key: str, text: str, command) -> None:
            btn = NeonButton(boost_row, text=text, command=command, variant="ghost",
                             bg=PALETTE["bg"], height=30)
            btn.pack(side=tk.LEFT, padx=4)
            self._boost_buttons[key] = btn

        _make_boost("traqueur", "🎯 Traqueur", self._use_traqueur)
        _make_boost("bouclier", "🛡 Bouclier", self._use_bouclier)
        _make_boost("ralenti", "🐢 Ralentir", self._use_ralenti)
        self._refresh_boost_buttons()

        scene_wrap = tk.Frame(c, bg=PALETTE["bg"])
        scene_wrap.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 16))
        self.turret_scene = TurretScene(scene_wrap, on_result=self._on_wave_click_result, bg=PALETTE["bg"])
        self.turret_scene.pack(fill=tk.BOTH, expand=True)

        self._refresh_mission_labels()
        self._load_current_wave()

    def _refresh_mission_labels(self) -> None:
        m = self.mission
        self.progress_label.config(
            text=f"Vagues repoussées : {m.closed}/{SEGMENTS}   —   Échecs : {m.mistakes}/{m.max_mistakes}"
        )
        remaining = max(0, m.max_mistakes - m.mistakes)
        self._shield_meter.set_value(100 * remaining / m.max_mistakes)

    def _load_current_wave(self) -> None:
        wave = self.mission.current
        tense_label = TENSE_LABELS.get(wave.tense, wave.tense)
        pronoun_label = PRONOUN_LABELS[wave.pronoun_index]
        self.prompt_label.config(
            text=f"Conjuguez {wave.verb.upper()} — {tense_label} — {pronoun_label}"
        )
        self.turret_scene.set_flight_time(FLIGHT_TIME_S.get(self.mission.level, 8))
        self.turret_scene.load_wave(wave)

    def _on_wave_click_result(self, hit: bool) -> None:
        if self.mission is None or self.mission.finished:
            return
        result = self.mission.resolve(hit)
        self._refresh_mission_labels()

        if result in ("correct", "wrong"):
            self._load_current_wave()
        elif result == "victory":
            self._end_mission(victory=True)
        elif result == "defeat":
            self._end_mission(victory=False)

    def _end_mission(self, victory: bool) -> None:
        m = self.mission
        duration = time.time() - self._mission_start_time
        level = m.level
        score = m.closed

        prev_best = self.best_scores.get(level, 0)
        is_new_best = score > prev_best
        if is_new_best:
            self.best_scores[level] = score

        # Crédits/XP : même barème que les autres jeux (voir problems.compute_rewards),
        # pour que la même performance rapporte pareil des deux côtés — c'est une
        # progression globale, partagée entre tous les jeux.
        credit_gain, xp_gain = compute_rewards(level, score, SEGMENTS)
        self.credits += credit_gain
        self.xp += xp_gain

        # Succès : badges partagés globalement avec les autres jeux (voir
        # commun/badges.py pour le catalogue affiché).
        newly_unlocked = evaluate_badges(victory, m.mistakes, self.best_scores, self.badges)
        self.badges.extend(newly_unlocked)

        if is_new_best or score > 0 or newly_unlocked:
            self._save_profile()

        if self.high_scores_enabled and self.username:
            service = self.high_score_service

            def _worker() -> None:
                try:
                    service.add_score(level, self.username, score, duration)
                except Exception as e:
                    logger.warning("Envoi du score échoué: %s", e)

            import threading
            threading.Thread(target=_worker, daemon=True).start()

        self.root.after(900, lambda: self._show_result_screen(
            victory, score, SEGMENTS, level, credit_gain, xp_gain, newly_unlocked
        ))

    def _show_result_screen(self, victory: bool, score: int, total: int, level: str,
                             credit_gain: int = 0, xp_gain: int = 0, newly_unlocked: list = None) -> None:
        self._cancel_campaign_auto_close()
        self._clear_content()
        c = self.content
        self._play_result_video(victory)

        banner_color = PALETTE["accent2"] if victory else PALETTE["danger"]
        banner_text = "SECTEUR SÉCURISÉ — DÉFENSE RÉUSSIE" if victory else "DÔME PERCÉ — LE SECTEUR EST TOMBÉ"
        badge_icon = "🛡" if victory else "⚠"
        mistakes = self.mission.mistakes if self.mission else 0

        wrap = tk.Frame(c, bg=PALETTE["bg"])
        wrap.pack(expand=True)

        IconBadge(wrap, badge_icon, diameter=64, ring_color=banner_color).pack(pady=(40, 12))

        card = RoundedFrame(wrap, padding=24, bg=PALETTE["bg"])
        card.pack()

        tk.Label(card.inner, text=banner_text, bg=PALETTE["panel2"], fg=banner_color,
                 font=(FONT_DISPLAY, 18, "bold"), wraplength=420, justify=tk.CENTER).pack(pady=(0, 14))

        stats_row = tk.Frame(card.inner, bg=PALETTE["panel2"])
        stats_row.pack(pady=(0, 14))
        StatChip(stats_row, "VAGUES", f"{score}/{total}", width=110).pack(side=tk.LEFT, padx=4)
        StatChip(stats_row, "ÉCHECS", str(mistakes), width=100).pack(side=tk.LEFT, padx=4)
        if credit_gain > 0 or xp_gain > 0:
            StatChip(stats_row, "CRÉDITS", f"+{credit_gain}", width=100).pack(side=tk.LEFT, padx=4)
            StatChip(stats_row, "XP", f"+{xp_gain}", width=90).pack(side=tk.LEFT, padx=4)

        if newly_unlocked:
            names = ", ".join(badge_name(bid) for bid in newly_unlocked)
            tk.Label(card.inner, text=f"Nouveau(x) succès : {names}", bg=PALETTE["panel2"], fg=PALETTE["accent2"],
                     font=(FONT_BODY, 11, "italic"), wraplength=420, justify=tk.CENTER).pack(pady=(0, 6))

        btn_row = tk.Frame(card.inner, bg=PALETTE["panel2"])
        btn_row.pack(pady=(10, 0))
        NeonButton(btn_row, text="Rejouer ce niveau", command=lambda: self._replay(level),
                   variant="solid", bg=PALETTE["panel2"], height=40).pack(side=tk.LEFT, padx=6)
        NeonButton(btn_row, text="Panthéon", command=self._open_high_scores,
                   variant="ghost", bg=PALETTE["panel2"], height=40).pack(side=tk.LEFT, padx=6)
        NeonButton(btn_row, text="Retour à la transmission", command=self.show_intro,
                   variant="ghost", bg=PALETTE["panel2"], height=40).pack(side=tk.LEFT, padx=6)

        # En mode campagne, l'écran de résultat se referme tout seul pour que
        # le Hub lance le jeu suivant. Tout clic sur un bouton annule le
        # compte à rebours (le joueur a décidé de rester sur ce jeu).
        if self.campaign_mode:
            self._campaign_countdown = self.CAMPAIGN_RESULT_DELAY_S
            self.countdown_label = tk.Label(card.inner, text="", bg=PALETTE["panel2"],
                                            fg=PALETTE["muted"], font=(FONT_BODY, 10, "italic"))
            self.countdown_label.pack(pady=(10, 0))
            self._tick_campaign_countdown()

    def _tick_campaign_countdown(self) -> None:
        if self._campaign_countdown <= 0:
            self._on_closing()
            return
        try:
            self.countdown_label.config(
                text=f"Prochaine mission dans {self._campaign_countdown} s — passage automatique")
        except tk.TclError:
            return
        self._campaign_countdown -= 1
        self._campaign_close_after_id = self.root.after(1000, self._tick_campaign_countdown)

    def _cancel_campaign_auto_close(self) -> None:
        if self._campaign_close_after_id is not None:
            try:
                self.root.after_cancel(self._campaign_close_after_id)
            except tk.TclError:
                pass
            self._campaign_close_after_id = None

    def _replay(self, level: str) -> None:
        self.level_var = tk.StringVar(value=level)
        self.start_mission()

    # --- Fermeture -------------------------------------------------------

    def _on_closing(self) -> None:
        try:
            if pygame.mixer.get_init():
                pygame.mixer.quit()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    # Sans console (pythonw, voir LANCER.bat), le journal fichier est la seule
    # trace en cas d'erreur.
    setup_file_logging(_HERE)
    # Mode campagne : lancé par le Hub avec --campagne, le jeu se referme tout
    # seul après l'écran de résultat (voir _show_result_screen).
    campaign = "--campagne" in sys.argv
    root = tk.Tk()
    log_tk_exceptions(root)
    ConjugaisonApp(root, campaign=campaign)
    root.mainloop()


if __name__ == "__main__":
    main()
