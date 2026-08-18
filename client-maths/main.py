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
from ui_widgets import NeonButton, RoundedFrame, SectionHeader, SegmentedControl
from server_client import HighScoreService, load_server_config
from scoring import GRADES as SHARED_GRADES, grade_name
from badges import badge_name
from video import play_intro
from logs import log_tk_exceptions, setup_file_logging

from problems import LEVELS, MathMission, compute_rewards, evaluate_badges
from services import TTSService
from ui_components import ProtectionGrid, MathHighScoreWindow

logger = logging.getLogger(__name__)

INTRO_TEXT = (
    "Ici Commandant {name}. Unité de défense orbitale isolée, secteur sept. "
    "Nous avons été attaqués. La grille de protection a tenu, mais elle "
    "faiblit. Je ne peux pas la reverrouiller seul — j'ai besoin de vous. "
    "Résolvez les calculs pour refermer chaque section. Vous avez droit à "
    "deux erreurs. Pas une de plus : à la troisième, les aliens passent. "
    "Prêt, Commandant ?"
)


class MathsApp:
    LEVELS = LEVELS

    # Grades partagés avec tous les jeux (commun/scoring.py) : l'XP est une
    # progression globale, un même total doit donner le même titre partout.
    GRADES = SHARED_GRADES

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
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

        self.content = tk.Frame(self.root, bg=PALETTE["bg"])
        self.content.pack(fill=tk.BOTH, expand=True)

        self.mission: MathMission | None = None
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
        """Portrait du joueur : vignette réelle si un avatar est choisi, sinon
        un médaillon générique aux initiales (jamais d'écran vide)."""
        photo = self._get_avatar_photo(size)
        if photo is not None:
            label = tk.Label(parent, image=photo, bg=PALETTE["panel2"],
                              highlightthickness=2, highlightbackground=PALETTE["accent"])
            label.image = photo
            return label
        canvas = tk.Canvas(parent, width=size[0], height=size[1], bg=PALETTE["panel2"],
                            highlightthickness=2, highlightbackground=PALETTE["accent"])
        initial = (self.username or "?")[0].upper()
        canvas.create_oval(4, 4, size[0] - 4, size[1] - 4, fill=PALETTE["panel3"], outline=PALETTE["accent"], width=2)
        canvas.create_text(size[0] / 2, size[1] / 2, text=initial, fill=PALETTE["accent_hi"],
                            font=(FONT_DISPLAY, int(size[1] * 0.4), "bold"))
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
        tk.Label(title_box, text=f"{self._grade_name()}  —  {self.credits} crédits",
                 bg=PALETTE["bg"], fg=PALETTE["muted"], font=(FONT_BODY, 10, "italic")).pack(anchor="w")

        panel = RoundedFrame(c, padding=20, bg=PALETTE["bg"])
        panel.pack(fill=tk.BOTH, expand=True, padx=28, pady=12)

        tk.Label(panel.inner, text=INTRO_TEXT.format(name=self.username), bg=PALETTE["panel2"],
                 fg=PALETTE["text"], font=(FONT_BODY, 12), wraplength=760, justify=tk.LEFT).pack(
            anchor="w", pady=(0, 16))

        level_row = tk.Frame(panel.inner, bg=PALETTE["panel2"])
        level_row.pack(anchor="w", pady=(0, 16))
        tk.Label(level_row, text="Niveau :", bg=PALETTE["panel2"], fg=PALETTE["accent"],
                 font=(FONT_DISPLAY, 10, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        self.level_var = tk.StringVar(value=LEVELS[0])
        SegmentedControl(level_row, LEVELS, self.level_var, bg=PALETTE["panel2"]).pack(side=tk.LEFT)

        best = self.best_scores.get(self.level_var.get())
        self.best_score_label = tk.Label(
            panel.inner, text=self._best_score_text(), bg=PALETTE["panel2"],
            fg=PALETTE["muted"], font=(FONT_BODY, 10, "italic"))
        self.best_score_label.pack(anchor="w", pady=(0, 16))

        def _on_level_change(*_a):
            self.best_score_label.config(text=self._best_score_text())
        self.level_var.trace_add("write", _on_level_change)

        btn_row = tk.Frame(panel.inner, bg=PALETTE["panel2"])
        btn_row.pack(anchor="w")
        NeonButton(btn_row, text="Verrouiller la grille", command=self.start_mission,
                   variant="solid", bg=PALETTE["panel2"], height=38).pack(side=tk.LEFT, padx=(0, 10))
        NeonButton(btn_row, text="Panthéon", command=self._open_high_scores,
                   variant="ghost", bg=PALETTE["panel2"], height=38).pack(side=tk.LEFT)

        # Le briefing parlé attend la fin de l'intro vidéo : les deux en même
        # temps se parleraient dessus. Sans fichier vidéo, _play_intro_video
        # enchaîne immédiatement (voir commun/video.py::play_intro).
        if not self._intro_spoken:
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

    def _grade_name(self) -> str:
        """Grade militaire correspondant à l'XP courante. Le calcul vit dans
        commun/scoring.py, partagé avec la dictée et le Hub : l'XP est une
        progression globale, un même total doit afficher le même titre partout."""
        return grade_name(self.xp)

    def _best_score_text(self) -> str:
        best = self.best_scores.get(self.level_var.get())
        if best is None:
            return "Aucune fermeture de grille enregistrée à ce niveau."
        from problems import SEGMENTS
        return f"Meilleure fermeture à ce niveau : {best}/{SEGMENTS}"

    def _open_high_scores(self) -> None:
        if self.high_scores_enabled:
            MathHighScoreWindow(self.root, self.high_score_service, PALETTE)
        else:
            messagebox.showerror("Erreur", "Le service du classement n'est pas disponible.")

    def start_mission(self) -> None:
        level = self.level_var.get()
        self.mission = MathMission(level=level)
        self._mission_start_time = time.time()
        self._build_mission_screen(level)

    def _build_mission_screen(self, level: str) -> None:
        self._clear_content()
        c = self.content

        top = tk.Frame(c, bg=PALETTE["bg"])
        top.pack(fill=tk.X, padx=24, pady=(18, 6))
        self._build_avatar_portrait(top, size=(56, 56)).pack(side=tk.LEFT, padx=(0, 12))
        info = tk.Frame(top, bg=PALETTE["bg"])
        info.pack(side=tk.LEFT, anchor="w")
        tk.Label(info, text=f"NIVEAU {level.upper()}", bg=PALETTE["bg"], fg=PALETTE["accent"],
                 font=(FONT_DISPLAY, 10, "bold")).pack(anchor="w")
        self.progress_label = tk.Label(info, text="", bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                                        font=(FONT_DISPLAY, 12, "bold"))
        self.progress_label.pack(anchor="w")
        NeonButton(top, text="Abandonner", command=self.show_intro, variant="ghost",
                   bg=PALETTE["bg"], height=30).pack(side=tk.RIGHT)

        body = tk.Frame(c, bg=PALETTE["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=24, pady=8)

        self.grid_canvas = ProtectionGrid(body, bg=PALETTE["bg"])
        self.grid_canvas.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

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

        self._refresh_mission_labels()
        self._show_current_question()

    def _refresh_mission_labels(self) -> None:
        from problems import SEGMENTS
        m = self.mission
        self.progress_label.config(
            text=f"Cases verrouillées : {m.closed}/{SEGMENTS}   —   Échecs : {m.mistakes}/{m.max_mistakes}"
        )

    def _show_current_question(self) -> None:
        self.question_label.config(text=f"{self.mission.current.question} = ?")
        self.answer_var.set("")
        try:
            self._answer_entry.focus_set()
        except tk.TclError:
            pass

    def _submit_answer(self) -> None:
        if self.mission is None or self.mission.finished:
            return
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
        self._clear_content()
        c = self.content

        banner_color = PALETTE["accent2"] if victory else PALETTE["danger"]
        banner_text = "GRILLE VERROUILLÉE — MISSION ACCOMPLIE" if victory else "BRÈCHE DÉTECTÉE — LES ALIENS ONT PERCÉ"

        tk.Label(c, text=banner_text, bg=PALETTE["bg"], fg=banner_color,
                 font=(FONT_DISPLAY, 20, "bold")).pack(pady=(60, 10))
        tk.Label(c, text=f"Cases verrouillées : {score}/{total}", bg=PALETTE["bg"], fg=PALETTE["text_strong"],
                 font=(FONT_DISPLAY, 14)).pack(pady=(0, 6))
        if credit_gain > 0 or xp_gain > 0:
            tk.Label(c, text=f"+{credit_gain} crédits   +{xp_gain} XP", bg=PALETTE["bg"], fg=PALETTE["accent"],
                     font=(FONT_DISPLAY, 12, "bold")).pack(pady=(0, 6))
        if newly_unlocked:
            names = ", ".join(badge_name(bid) for bid in newly_unlocked)
            tk.Label(c, text=f"Nouveau(x) succès : {names}", bg=PALETTE["bg"], fg=PALETTE["accent2"],
                     font=(FONT_BODY, 11, "italic")).pack(pady=(0, 30))
        else:
            tk.Label(c, text="", bg=PALETTE["bg"]).pack(pady=(0, 30))

        btn_row = tk.Frame(c, bg=PALETTE["bg"])
        btn_row.pack()
        NeonButton(btn_row, text="Rejouer ce niveau", command=lambda: self._replay(level),
                   variant="solid", bg=PALETTE["bg"], height=38).pack(side=tk.LEFT, padx=8)
        NeonButton(btn_row, text="Panthéon", command=self._open_high_scores,
                   variant="ghost", bg=PALETTE["bg"], height=38).pack(side=tk.LEFT, padx=8)
        NeonButton(btn_row, text="Retour à la transmission", command=self.show_intro,
                   variant="ghost", bg=PALETTE["bg"], height=38).pack(side=tk.LEFT, padx=8)

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
    root = tk.Tk()
    log_tk_exceptions(root)
    MathsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
