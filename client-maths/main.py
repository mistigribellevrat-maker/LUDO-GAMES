# main.py
"""GRILLE DE PROTECTION — jeu de maths.

Un space marine isolé a été attaqué : le joueur doit verrouiller sa grille de
protection en résolvant des opérations mathématiques (5 niveaux, une
opération dominante par niveau — voir problems.py). 2 échecs autorisés avant
que les aliens ne franchissent la grille. Aucun appel IA : les opérations
sont générées localement, gratuitement et instantanément.
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
from server_client import HighScoreService, load_server_config
from scoring import GRADES as SHARED_GRADES, grade_name
from badges import badge_name
from video import play_intro
from logs import log_tk_exceptions, setup_file_logging

from problems import LEVELS, MathMission, QUESTION_TIME_S, compute_rewards, evaluate_badges
from services import TTSService
from ui_components import ProtectionGrid, MathHighScoreWindow
from ui_extras import CommandBackdrop, IconBadge, StatChip, LEVEL_ICONS

logger = logging.getLogger(__name__)


class MathsApp:
    LEVELS = LEVELS

    # Grades partagés avec tous les jeux (commun/scoring.py) : l'XP est une
    # progression globale, un même total doit afficher le même titre partout.
    GRADES = SHARED_GRADES

    # Catalogue de la boutique : chaque achat ajoute `helps` charges
    # utilisables en mission (voir _buy_item/_consume_charge). L'inventaire
    # (`shop_charges`) est local au jeu, comme l'inventaire d'armes de la
    # dictée ; seuls les crédits (globaux) sont synchronisés au serveur.
    SHOP_ITEMS = [
        {"key": "indice", "name": "Calculateur d'urgence", "price": 150, "helps": 1,
         "icon": "💡", "effect": "Révèle la réponse d'une question"},
        {"key": "bouclier", "name": "Bouclier de secours", "price": 200, "helps": 1,
         "icon": "🛡", "effect": "+1 échec autorisé pour la mission"},
        {"key": "horloge", "name": "Horloge étendue", "price": 150, "helps": 1,
         "icon": "⏱", "effect": "+3 secondes sur la question en cours"},
    ]

    def __init__(self, root: tk.Tk, campaign: bool = False) -> None:
        self.root = root
        # Mode campagne (lancé par le Hub avec --campagne) : l'écran de
        # résultat se referme tout seul pour laisser le jeu suivant démarrer.
        self.campaign_mode = campaign
        self._campaign_close_after_id: str | None = None
        self.root.title("GRILLE DE PROTECTION // DÉFENSE ORBITALE")
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

        self.tts_service = TTSService()
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

        self.mission: MathMission | None = None
        self._mission_start_time = 0.0
        self._timer_after_id: str | None = None
        # Jeton de session : incrémenté à chaque nouvelle mission, pour qu'un
        # tick de minuteur en vol (après un Abandonner ou un Rejouer) ne
        # s'applique jamais à la mission suivante (même technique que
        # commun/video.py::ControlledVideoPlayer._session).
        self._mission_session = 0

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
        self._cancel_question_timer()
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
        NeonButton(btn_row, text="🔒 Verrouiller la grille", command=self.start_mission,
                   variant="solid", bg=PALETTE["panel2"], height=44).pack(side=tk.LEFT, padx=(0, 10))
        NeonButton(btn_row, text="Panthéon", command=self._open_high_scores,
                   variant="ghost", bg=PALETTE["panel2"], height=44).pack(side=tk.LEFT)
        NeonButton(btn_row, text="Boutique", command=self._open_shop,
                   variant="ghost", bg=PALETTE["panel2"], height=44).pack(side=tk.LEFT, padx=(6, 0))

        # Le briefing parlé attend la fin de l'intro vidéo : les deux en même
        # temps se parleraient dessus. Sans fichier vidéo, _play_intro_video
        # enchaîne immédiatement (voir commun/video.py::play_intro). En mode
        # campagne, on la saute : le Hub enchaîne les jeux tout seul, une
        # intro à chaque lancement ralentirait l'enchaînement.
        if not self._intro_spoken and not self.campaign_mode:
            self._intro_spoken = True
            self._play_intro_video()

    # Intro jouée au démarrage : déposer le fichier à cet emplacement suffit à
    # l'activer, aucun réglage à faire.
    INTRO_VIDEO_PATH = os.path.join("assets", "videos", "intro.mp4")

    def _play_intro_video(self) -> None:
        # La vidéo remplace le briefing parlé par défaut (elle fait déjà l'accueil).
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
        commun/scoring.py, partagé avec la dictée et le Hub : l'XP est une
        progression globale, un même total doit afficher le même titre partout."""
        return grade_name(self.xp)

    def _best_score_value(self) -> str:
        best = self.best_scores.get(self.level_var.get())
        if best is None:
            return "—"
        from problems import SEGMENTS
        return f"{best}/{SEGMENTS}"

    def _open_high_scores(self) -> None:
        if self.high_scores_enabled:
            MathHighScoreWindow(self.root, self.high_score_service, PALETTE)
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
        shop.title("Boutique d'Équipement")
        shop.transient(self.root)
        shop.grab_set()
        shop.configure(bg=c["bg"])

        header = tk.Frame(shop, bg=c["bg"])
        header.pack(fill=tk.X, padx=16, pady=(14, 6))
        tk.Label(header, text="BOUTIQUE D'ÉQUIPEMENT", bg=c["bg"], fg=c["text_strong"],
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

    # Délai d'affichage de l'écran de résultat avant passage automatique au
    # jeu suivant (mode campagne).
    CAMPAIGN_RESULT_DELAY_S = 10

    # --- Bonus de boutique en mission ------------------------------------

    def _use_indice(self) -> None:
        if self.mission is None or self.mission.finished:
            return
        if int(self.shop_charges.get("indice", 0)) <= 0:
            return
        self.answer_var.set(str(self.mission.current.answer))
        self._consume_charge("indice")

    def _use_bouclier(self) -> None:
        if self.mission is None or self.mission.finished:
            return
        if int(self.shop_charges.get("bouclier", 0)) <= 0:
            return
        self.mission.max_mistakes += 1
        self._consume_charge("bouclier")
        self._refresh_mission_labels()

    def _use_horloge(self) -> None:
        if self.mission is None or self.mission.finished:
            return
        if int(self.shop_charges.get("horloge", 0)) <= 0:
            return
        self._time_left += 3
        self._update_timer_display()
        self._consume_charge("horloge")

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
        self.mission = MathMission(level=level)
        self._mission_start_time = time.time()
        self._build_mission_screen(level)

    def _build_mission_screen(self, level: str) -> None:
        self._cancel_question_timer()
        self._mission_session += 1
        self._clear_content()
        c = self.content

        top = tk.Frame(c, bg=PALETTE["bg"])
        top.pack(fill=tk.X, padx=24, pady=(18, 6))
        self._build_avatar_portrait(top, size=(56, 56)).pack(side=tk.LEFT, padx=(0, 12))
        info = tk.Frame(top, bg=PALETTE["bg"])
        info.pack(side=tk.LEFT, anchor="w", fill=tk.X, expand=True, padx=(0, 12))
        level_title_row = tk.Frame(info, bg=PALETTE["bg"])
        level_title_row.pack(anchor="w")
        IconBadge(level_title_row, LEVEL_ICONS.get(level, "🧮"), diameter=26).pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(level_title_row, text=f"NIVEAU {level.upper()}", bg=PALETTE["bg"], fg=PALETTE["accent"],
                 font=(FONT_DISPLAY, 10, "bold")).pack(side=tk.LEFT)
        self.progress_label = tk.Label(info, text="", bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                                        font=(FONT_DISPLAY, 12, "bold"))
        self.progress_label.pack(anchor="w")
        self._shield_meter = ShieldMeter(info, height=12, bg=PALETTE["bg"])
        self._shield_meter.pack(anchor="w", fill=tk.X, pady=(4, 0))
        NeonButton(top, text="Abandonner", command=self.show_intro, variant="ghost",
                   bg=PALETTE["bg"], height=30).pack(side=tk.RIGHT)

        body = tk.Frame(c, bg=PALETTE["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=24, pady=8)

        ring_wrap = tk.Frame(body, bg=PALETTE["bg"], width=380, height=380)
        ring_wrap.pack_propagate(False)
        ring_wrap.pack(pady=(0, 6))
        self.grid_canvas = ProtectionGrid(ring_wrap, bg=PALETTE["bg"])
        self.grid_canvas.pack(fill=tk.BOTH, expand=True)

        self.timer_label = tk.Label(body, text="", bg=PALETTE["bg"], fg=PALETTE["accent2"],
                                     font=(FONT_DISPLAY, 13, "bold"))
        self.timer_label.pack(pady=(4, 0))

        self.question_label = tk.Label(body, text="", bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                                        font=(FONT_MONO, 30, "bold"))
        self.question_label.pack(pady=(10, 6))

        answer_row = tk.Frame(body, bg=PALETTE["bg"])
        answer_row.pack(pady=(0, 12))
        self.answer_var = tk.StringVar()
        entry = ttk.Entry(answer_row, textvariable=self.answer_var, width=10,
                           font=(FONT_MONO, 16), justify=tk.CENTER)
        entry.pack(side=tk.LEFT, padx=(0, 10))
        entry.bind("<Return>", lambda e: self._submit_answer())
        entry.focus_set()
        NeonButton(answer_row, text="Valider", command=self._submit_answer, variant="solid",
                   bg=PALETTE["bg"], height=36).pack(side=tk.LEFT)
        self._answer_entry = entry

        boost_row = tk.Frame(body, bg=PALETTE["bg"])
        boost_row.pack(pady=(0, 10))
        self._boost_buttons = {}

        def _make_boost(key: str, text: str, command) -> None:
            btn = NeonButton(boost_row, text=text, command=command, variant="ghost",
                             bg=PALETTE["bg"], height=30)
            btn.pack(side=tk.LEFT, padx=4)
            self._boost_buttons[key] = btn

        _make_boost("indice", "💡 Indice", self._use_indice)
        _make_boost("bouclier", "🛡 Bouclier", self._use_bouclier)
        _make_boost("horloge", "⏱ +3 s", self._use_horloge)
        self._refresh_boost_buttons()

        self._refresh_mission_labels()
        self._show_current_question()

    def _refresh_mission_labels(self) -> None:
        from problems import SEGMENTS
        m = self.mission
        self.progress_label.config(
            text=f"Cases verrouillées : {m.closed}/{SEGMENTS}   —   Échecs : {m.mistakes}/{m.max_mistakes}"
        )
        remaining = max(0, m.max_mistakes - m.mistakes)
        self._shield_meter.set_value(100 * remaining / m.max_mistakes)

    def _show_current_question(self) -> None:
        self.question_label.config(text=f"{self.mission.current.question} = ?")
        self.answer_var.set("")
        try:
            self._answer_entry.focus_set()
        except tk.TclError:
            pass
        self._start_question_timer()

    # --- Minuteur par question ---------------------------------------
    # Chaque question doit être résolue avant la fin du compte à rebours
    # (durée par niveau : problems.QUESTION_TIME_S), sinon c'est compté comme
    # une mauvaise réponse — même conséquence qu'une erreur de calcul. Le
    # jeton `_mission_session` évite qu'un tick en vol après un Abandonner/
    # Rejouer ne s'applique à la mission suivante.

    def _cancel_question_timer(self) -> None:
        if self._timer_after_id is not None:
            try:
                self.root.after_cancel(self._timer_after_id)
            except tk.TclError:
                pass
            self._timer_after_id = None

    def _start_question_timer(self) -> None:
        self._cancel_question_timer()
        self._time_left = QUESTION_TIME_S.get(self.mission.level, 10)
        self._update_timer_display()
        session = self._mission_session
        self._timer_after_id = self.root.after(1000, lambda: self._tick_question_timer(session))

    def _tick_question_timer(self, session: int) -> None:
        self._timer_after_id = None
        if session != self._mission_session:
            return
        self._time_left -= 1
        self._update_timer_display()
        if self._time_left <= 0:
            self._on_time_up()
            return
        self._timer_after_id = self.root.after(1000, lambda: self._tick_question_timer(session))

    def _update_timer_display(self) -> None:
        try:
            if not self.timer_label.winfo_exists():
                return
        except tk.TclError:
            return
        total = QUESTION_TIME_S.get(self.mission.level, 10)
        t = max(0, self._time_left)
        ratio = t / total if total else 0
        color = PALETTE["accent2"] if ratio > 0.5 else PALETTE["warning"] if ratio > 0.2 else PALETTE["danger"]
        self.timer_label.config(text=f"⏱ {t}s", fg=color)

    def _on_time_up(self) -> None:
        if self.mission is None or self.mission.finished:
            return
        self.answer_var.set("")
        self._submit_answer()

    def _submit_answer(self) -> None:
        if self.mission is None or self.mission.finished:
            return
        self._cancel_question_timer()
        value = self.answer_var.get().strip()
        result = self.mission.answer(value)
        self._refresh_mission_labels()

        if result == "correct":
            self.grid_canvas.close_next_segment()
            self._show_current_question()
        elif result == "wrong":
            self.grid_canvas.flash_wrong()
            self._show_current_question()
        elif result == "victory":
            self.grid_canvas.close_next_segment()
            self._end_mission(victory=True)
        elif result == "defeat":
            self.grid_canvas.trigger_breach()
            self._end_mission(victory=False)

    def _end_mission(self, victory: bool) -> None:
        from problems import SEGMENTS
        m = self.mission
        duration = time.time() - self._mission_start_time
        level = m.level
        score = m.closed

        prev_best = self.best_scores.get(level, 0)
        is_new_best = score > prev_best
        if is_new_best:
            self.best_scores[level] = score

        # Crédits/XP : même barème que la dictée (voir problems.compute_rewards),
        # pour que la même performance rapporte pareil des deux côtés — c'est une
        # progression globale, partagée entre tous les jeux.
        credit_gain, xp_gain = compute_rewards(level, score, SEGMENTS)
        self.credits += credit_gain
        self.xp += xp_gain

        # Succès : badges partagés globalement avec les autres jeux (voir
        # client-dictee/main.py::BADGES pour le catalogue affiché).
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
        self._cancel_question_timer()
        self._cancel_campaign_auto_close()
        self._clear_content()
        c = self.content
        self._play_result_video(victory)

        banner_color = PALETTE["accent2"] if victory else PALETTE["danger"]
        banner_text = "GRILLE VERROUILLÉE — MISSION ACCOMPLIE" if victory else "BRÈCHE DÉTECTÉE — LES ALIENS ONT PERCÉ"
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
        StatChip(stats_row, "CASES", f"{score}/{total}", width=110).pack(side=tk.LEFT, padx=4)
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
    MathsApp(root, campaign=campaign)
    root.mainloop()


if __name__ == "__main__":
    main()
