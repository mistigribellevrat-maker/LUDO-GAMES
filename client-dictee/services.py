# services.py

import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from enum import Enum

# NOUVEAU : Imports Tkinter requis pour le VideoService
import tkinter as tk

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
import requests
from gtts import gTTS, gTTSError
import pygame

# Lecteur vidéo partagé (commun/video.py) : il vivait ici, il sert désormais
# aussi au Hub et au jeu de maths. Une seule copie de ce code sensible au
# threading Tk, pas trois.
from video import ControlledVideoPlayer

logger = logging.getLogger(__name__)


# --- Énumération pour les états Vidéo ---
class VideoState(Enum):
    STARTUP = "1.mp4"
    TRANSMISSION = "2.mp4"
    VALIDATION_SUCCESS = "3p.mp4"
    VALIDATION_FAIL = "3.mp4"
    FINAL_VICTORY = "4.mp4"
    IDLE = None

# --- Définition des Services ---

class VideoService:
    TARGET_FPS = 16

    def __init__(self, parent_frame: tk.Widget, width: int, height: int) -> None:
        self.frame = parent_frame
        self.width = width
        self.height = height
        self.player: ControlledVideoPlayer | None = None
        self.current_video_file: str | None = None
        self.video_label = tk.Label(self.frame, bg="#000000")
        self.video_label.pack(expand=True, fill="both")
        # Allow overriding the default STARTUP video (used as avatar)
        self._startup_override: str | None = None

    def set_video(self, state: VideoState) -> None:
        # Resolve the target file, supporting a custom startup override
        if state == VideoState.STARTUP and self._startup_override:
            video_file = self._startup_override
        else:
            video_file = state.value
        if video_file == self.current_video_file: return
        if self.player: self.player.stop()
        self.player = None
        self.current_video_file = video_file
        if video_file and os.path.exists(video_file):
            try:
                self.video_label.config(text="")
                self.player = ControlledVideoPlayer(self.video_label, video_file, (self.width, self.height), fps=self.TARGET_FPS)
                self.player.play()
            except (OSError, tk.TclError) as e:
                logger.error("Erreur lors du chargement de la vidéo %s: %s", video_file, e)
                self.show_placeholder(f"Erreur vidéo:\n{video_file}")
        elif video_file:
            logger.warning("Fichier vidéo '%s' non trouvé.", video_file)
            self.show_placeholder(f"Vidéo manquante:\n{video_file}")
        else:
            self.show_placeholder("TRANSMISSION\nTERMINÉE")

    def show_placeholder(self, text: str) -> None:
        if self.player: self.player.stop()
        self.player = None
        self.video_label.config(image="", text=text, font=("Bahnschrift", 12, "bold"), fg="#00d9ff", bg="#000000")
        self.current_video_file = None

    def set_startup_video(self, video_path: str | None):
        """
        Define a custom video file to be used when state is VideoState.STARTUP.
        Pass None to clear the override and fallback to the default mapping ("1.mp4").
        """
        self._startup_override = video_path if video_path else None

class MusicService:
    def __init__(self, music_file: str = "main.mp3", volume: float = 0.3) -> None:
        self.music_file: str | None = music_file
        self.volume = volume
        self.is_playing = False
        if not os.path.exists(self.music_file):
            logger.warning("Fichier musical '%s' non trouvé.", self.music_file)
            self.music_file = None

    def play_background(self) -> None:
        if not self.music_file or not pygame.mixer.get_init() or self.is_playing: return
        try:
            pygame.mixer.music.load(self.music_file)
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play(-1)
            self.is_playing = True
        except pygame.error as e:
            logger.error("Erreur lors du lancement de la musique de fond : %s", e)

    def stop_background(self, fade_ms: int = 1000) -> None:
        if not self.music_file or not pygame.mixer.get_init() or not self.is_playing: return
        pygame.mixer.music.fadeout(fade_ms)
        self.is_playing = False

    def resume_background(self) -> None: self.play_background()

class AntiCheatService:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def _block_process(self) -> None:
        while not self.stop_event.is_set():
            if sys.platform == "win32":
                try:
                    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError as e:
                    logger.debug("taskkill indisponible ou a échoué : %s", e)
            time.sleep(2)

    def start(self) -> None:
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._block_process, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=1)

class GeminiService:
    """Enveloppe autour du SDK ``google.genai`` : génération de dictées et
    explications pédagogiques des fautes de l'enfant.

    Contrat FIGÉ avec ``main.py`` (ne pas changer sans coordination) :
      - ``generate_dictation`` retourne toujours une ``list[str]`` non vide. En cas
        d'échec, l'unique élément contient "Erreur" ou "Désolé" (voir
        ``DictationApp._on_dictation_generated``).
      - ``get_error_explanation`` / ``get_insertion_explanation`` retournent
        toujours une ``str``. En cas d'échec, cette chaîne commence exactement par
        ``FAILURE_PREFIX`` (voir ``DictationApp._GEMINI_FAILURE_PREFIX``).
      - Aucune des trois méthodes ne lève jamais : toute exception est avalée et
        traduite en message lisible pour l'enfant/le parent.

    Migré le 15 août 2026 de l'ancien SDK ``google.generativeai`` (déprécié,
    ``genai.GenerativeModel``) vers le nouveau SDK ``google.genai``
    (``genai.Client().models.generate_content(...)``).
    """

    # Modèle Gemini utilisé, surchargeable sans toucher au code via la variable
    # d'environnement GEMINI_MODEL (pratique pour tester un autre modèle).
    DEFAULT_MODEL_NAME = "gemini-3.5-flash-lite"

    # Niveau de réflexion du modèle (thinking). En HIGH, le modèle « réfléchit »
    # davantage avant de répondre : dictées mieux calibrées sur le niveau
    # scolaire demandé, et surtout explications de fautes plus justes — c'est un
    # outil pédagogique, une explication approximative apprend une bêtise à
    # l'enfant. Le prix : des réponses plus lentes (d'où les timeouts relevés
    # ci-dessous) et un peu plus de jetons facturés.
    # Surchargeable sans toucher au code : GEMINI_THINKING_LEVEL=MINIMAL|LOW|MEDIUM|HIGH.
    DEFAULT_THINKING_LEVEL = "HIGH"

    # Préfixe EXACT attendu par main.py (_GEMINI_FAILURE_PREFIX) pour détecter un
    # échec de get_error_explanation / get_insertion_explanation. Ne pas modifier
    # cette chaîne sans mettre à jour main.py en conséquence.
    FAILURE_PREFIX = "Désolé, une erreur est survenue"

    # Timeouts réseau explicites (secondes) : sans eux, un appel Gemini peut
    # pendre indéfiniment et geler l'attente de l'enfant, même si l'appel tourne
    # sur un thread worker côté main.py. Transmis via
    # genai.types.GenerateContentConfig(http_options=genai.types.HttpOptions(timeout=ms))
    # — HttpOptions.timeout est en MILLISECONDES (vérifié dans le SDK installé).
    # Relevés (25 -> 45 et 15 -> 30) en passant le modèle en réflexion HIGH : la
    # phase de réflexion s'ajoute au temps de génération, et un timeout se
    # traduit à l'écran par une erreur pour l'enfant.
    DICTATION_TIMEOUT_S = 45
    EXPLANATION_TIMEOUT_S = 30

    # Raisons d'arrêt du modèle qui signalent un contenu bloqué par les filtres de
    # sécurité (plutôt qu'une génération normale) : voir genai.types.FinishReason.
    _BLOCKING_FINISH_REASONS = frozenset({
        "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII",
        "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT",
    })

    # La dictée doit contenir exactement ce nombre de phrases (voir le prompt).
    SENTENCE_COUNT = 3
    # Bornes de plausibilité (nombre de mots) utilisées pour rejeter une réponse
    # manifestement cassée (paragraphe entier, phrase tronquée, etc.). Volontairement
    # larges : elles ne valident pas la "qualité pédagogique" du niveau (c'est le
    # rôle du prompt), seulement la forme.
    MIN_WORDS_PER_SENTENCE = 3
    MAX_WORDS_PER_SENTENCE = 45

    # Une seule reprise en cas de réponse inexploitable (pas de boucle infinie).
    MAX_GENERATION_ATTEMPTS = 2

    # Consignes de difficulté par niveau, injectées dans le prompt de dictée.
    # Clés alignées sur main.py: DIFFICULTY_LEVELS = ["CE1", "CE2", "CM1", "CM2", "Collège"].
    _LEVEL_GUIDELINES: dict[str, str] = {
        "CE1": (
            "Niveau CE1 (6-7 ans). Phrases très courtes : 4 à 7 mots. Uniquement le "
            "présent de l'indicatif. Vocabulaire concret et quotidien (la maison, "
            "l'école, les animaux, la famille). Sujets simples (un nom propre, "
            "'le/la/les + nom', 'il/elle/on'). Un seul piège par phrase maximum : "
            "accord singulier/pluriel évident dans le groupe nominal (le chat / les "
            "chats), accord simple sujet-verbe au présent. Pas de subordonnées, pas "
            "d'homophones grammaticaux."
        ),
        "CE2": (
            "Niveau CE2 (7-8 ans). Phrases courtes : 6 à 9 mots. Présent de "
            "l'indicatif, avec éventuellement une phrase au passé composé. "
            "Vocabulaire quotidien un peu plus varié. Pièges visés : accord dans le "
            "groupe nominal (déterminant-nom-adjectif simple), accord sujet-verbe, "
            "et un seul type d'homophone parmi a/à, et/est, son/sont."
        ),
        "CM1": (
            "Niveau CM1 (8-9 ans). Phrases moyennes : 8 à 12 mots, avec au plus une "
            "subordonnée simple (que, qui, parce que). Temps utilisés : présent, "
            "imparfait, passé composé. Pièges visés : accords dans le groupe "
            "nominal avec adjectifs, accord sujet-verbe (y compris sujet inversé ou "
            "éloigné du verbe), homophones a/à, et/est, on/ont, ce/se, son/sont."
        ),
        "CM2": (
            "Niveau CM2 (9-10 ans). Phrases plus longues : 10 à 15 mots, avec au "
            "moins une proposition relative ou une subordonnée. Temps utilisés : "
            "imparfait, passé composé, futur simple, présent. Pièges visés : accord "
            "du participe passé avec être dans les cas simples, accords dans des "
            "groupes nominaux plus complexes, homophones plus fins (leur/leurs, "
            "quel/quels/qu'elle, ces/ses, tout/tous)."
        ),
        "Collège": (
            "Niveau Collège — entrée en 6e/5e (11-13 ans), PAS un niveau 4e/3e : ce "
            "doit rester accessible à un enfant qui vient tout juste de terminer le "
            "CM2, une marche au-dessus de CM2, pas trois. Phrases longues et "
            "structurées : 12 à 18 mots, avec une ou deux subordonnées (relative, "
            "complétive, causale). Temps utilisés : présent, imparfait, passé "
            "composé, futur simple, et passé simple uniquement pour des verbes "
            "fréquents (être, avoir, aller, dire, faire, verbes du premier groupe) "
            "dans un court récit. Subjonctif présent autorisé seulement dans des "
            "tournures figées très courantes ('il faut que', 'pour que', 'bien "
            "que') avec des verbes simples. Pièges visés : accord du participe "
            "passé avec avoir dans les cas simples (sujet avant le verbe, sans COD "
            "complexe placé avant), accords dans des groupes nominaux étoffés, "
            "homophones grammaticaux de ce niveau : quand/quant/qu'en, sans/s'en, "
            "peu/peut/peux, quel(s)/quelle(s)/qu'elle(s). Interdits à ce niveau : "
            "COD antéposé complexe avec avoir, distinction quoique/quoi que, "
            "davantage/d'avantage, concordance des temps élaborée — ce sont des "
            "pièges de fin de collège, pas d'entrée en 6e."
        ),
    }
    _DEFAULT_LEVEL_KEY = "CM1"

    def __init__(self, api_key: str) -> None:
        """Configure le SDK Gemini et instancie le modèle.

        Lève ``ConnectionError`` si la configuration échoue localement (clé
        absente/malformée) : ce comportement est volontairement conservé tel
        quel, car il est géré au démarrage de l'application (voir le bloc
        ``if __name__ == "__main__":`` de main.py), pas pendant une partie.
        """
        model_name = os.getenv("GEMINI_MODEL", self.DEFAULT_MODEL_NAME)
        self.thinking_level = self._resolve_thinking_level()
        try:
            self.client = genai.Client(api_key=api_key)
            self.model_name = model_name
        except Exception as e:
            raise ConnectionError(f"Erreur de configuration de Gemini. Vérifiez votre clé API. Détails: {e}")

    @classmethod
    def _resolve_thinking_level(cls):
        """Niveau de réflexion demandé au modèle, validé contre l'énumération du
        SDK. Une valeur inconnue dans GEMINI_THINKING_LEVEL retombe sur HIGH avec
        un avertissement, plutôt que de faire échouer chaque appel : le jeu doit
        rester jouable même après une faute de frappe dans le .env."""
        raw = (os.getenv("GEMINI_THINKING_LEVEL") or cls.DEFAULT_THINKING_LEVEL).strip().upper()
        try:
            return genai_types.ThinkingLevel(raw)
        except ValueError:
            logger.warning(
                "GEMINI_THINKING_LEVEL='%s' inconnu, repli sur %s. Valeurs acceptées : %s",
                raw, cls.DEFAULT_THINKING_LEVEL,
                ", ".join(level.value for level in genai_types.ThinkingLevel),
            )
            return genai_types.ThinkingLevel(cls.DEFAULT_THINKING_LEVEL)

    def _generate(self, prompt: str, timeout_s: float):
        """Appel bas niveau au SDK, avec timeout explicite en millisecondes."""
        return self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                http_options=genai_types.HttpOptions(timeout=int(timeout_s * 1000)),
                thinking_config=genai_types.ThinkingConfig(thinking_level=self.thinking_level),
            ),
        )

    def _extract_text(self, response) -> str:
        """Extrait le texte d'une réponse Gemini, ou lève ``ValueError`` avec un
        message diagnostique si la réponse est vide ou bloquée par les filtres de
        sécurité. Ne laisse jamais passer d'exception SDK brute : ``_describe_error``
        s'appuie sur le contenu du message pour catégoriser l'échec."""
        feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(feedback, "block_reason", None)
        if block_reason:
            raise ValueError(f"réponse bloquée par les filtres de sécurité (SAFETY) : {block_reason}")

        candidates = getattr(response, "candidates", None)
        if not candidates:
            raise ValueError("aucune réponse générée (candidates vide)")

        finish_reason = getattr(candidates[0], "finish_reason", None)
        finish_name = getattr(finish_reason, "name", None) or (str(finish_reason) if finish_reason else "")
        if finish_name in self._BLOCKING_FINISH_REASONS:
            raise ValueError(f"réponse bloquée par les filtres de sécurité (SAFETY) : {finish_name}")

        text = (response.text or "").strip()
        if not text:
            raise ValueError("réponse vide")
        return text

    # ------------------------------------------------------------------
    # Dictée
    # ------------------------------------------------------------------
    def generate_dictation(self, level: str, theme: str) -> list[str]:
        """Génère une dictée de ``SENTENCE_COUNT`` phrases adaptées au niveau donné.

        Retourne toujours une liste non vide de chaînes. En cas d'échec réseau/API
        (clé invalide, quota dépassé, timeout, réponse bloquée par les filtres de
        sécurité), retourne immédiatement une liste à un seul élément décrivant le
        problème. En cas de réponse structurellement inexploitable (mauvais nombre
        de phrases, Markdown résiduel, préambule non voulu...), retente une seule
        fois avant d'abandonner avec un message d'erreur.
        """
        prompt = self._build_dictation_prompt(level, theme)
        last_raw: str | None = None
        for attempt in range(1, self.MAX_GENERATION_ATTEMPTS + 1):
            try:
                response = self._generate(prompt, self.DICTATION_TIMEOUT_S)
                raw_text = self._extract_text(response)
            except Exception as e:
                logger.error(
                    "Échec de génération de dictée (tentative %d/%d): %s",
                    attempt, self.MAX_GENERATION_ATTEMPTS, e,
                )
                return [f"Erreur lors de la génération de la dictée : {self._describe_error(e)}"]

            sentences = self._clean_dictation_response(raw_text)
            if sentences is not None:
                return sentences
            last_raw = raw_text
            logger.warning(
                "Réponse de dictée inexploitable (tentative %d/%d), nouvelle tentative: %r",
                attempt, self.MAX_GENERATION_ATTEMPTS, (raw_text or "")[:200],
            )

        logger.error("Dictée toujours inexploitable après reprise. Dernière réponse brute: %r", (last_raw or "")[:200])
        return ["Désolé, je n'ai pas pu générer une dictée exploitable. Essayez un autre thème."]

    def _build_dictation_prompt(self, level: str, theme: str) -> str:
        """Construit le prompt de génération, modulé explicitement par niveau
        scolaire (longueur de phrase, temps verbaux, pièges orthographiques visés)."""
        guidelines = self._LEVEL_GUIDELINES.get(level, self._LEVEL_GUIDELINES[self._DEFAULT_LEVEL_KEY])
        safe_theme = (theme or "").strip() or "la vie de tous les jours"
        return (
            "Tu es un instituteur francophone qui prépare une dictée pour un exercice "
            "scolaire à la maison. Le texte sera ensuite lu à voix haute par une "
            "synthèse vocale (gTTS), puis l'enfant devra le retranscrire à l'écrit.\n\n"
            f"{guidelines}\n\n"
            f"Thème demandé par l'enfant : \"{safe_theme}\". Ce thème peut être "
            "fantaisiste, mal orthographié ou inapproprié : dans tous les cas, "
            "adapte-le, édulcore-le ou remplace-le par un thème neutre et joyeux, "
            "mais reste toujours strictement adapté à un enfant. Interdits absolus, "
            "quel que soit le thème demandé : violence, peur, mort, sang, armes, "
            "contenu sexuel ou adulte, insultes, drogue, sujets anxiogènes ou "
            "tristes. En cas de doute, choisis un sujet neutre (nature, école, "
            "sport, animaux, cuisine, aventure douce, espace).\n\n"
            "Contraintes de forme, à respecter strictement :\n"
            f"- Exactement {self.SENTENCE_COUNT} phrases distinctes, chacune sur sa "
            "propre ligne, séparées par un simple retour à la ligne.\n"
            "- Chaque phrase se termine par un point, un point d'exclamation ou un "
            "point d'interrogation, et contient au moins une virgule si elle est "
            "assez longue pour cela.\n"
            "- Aucun titre, aucune introduction, aucune conclusion, aucun "
            "commentaire : uniquement les phrases de la dictée, rien d'autre.\n"
            "- Aucun format Markdown : pas de puces, pas de numérotation "
            "(\"1.\", \"-\"), pas d'astérisques ni de gras.\n"
            "- Texte destiné à être lu à voix haute par une synthèse vocale : "
            "n'utilise jamais de chiffres écrits en chiffres (écris les nombres en "
            "toutes lettres), pas de sigles ni d'abréviations, pas de parenthèses, "
            "pas de guillemets imbriqués, pas de symboles inhabituels.\n"
            "- N'écris jamais le mot \"cœur\" (utilise un synonyme si besoin).\n"
        )

    def _clean_dictation_response(self, raw_text: str | None) -> list[str] | None:
        """Nettoie et valide la réponse brute du modèle.

        Retire les artefacts Markdown, puces, numérotation, et les lignes de
        préambule ("Voici la dictée :"...), puis vérifie qu'il reste exactement
        ``SENTENCE_COUNT`` phrases de longueur plausible et sans résidu Markdown.
        Retourne ``None`` si la réponse reste inexploitable après nettoyage
        (déclenche la reprise dans ``generate_dictation``).
        """
        if not raw_text or not raw_text.strip():
            return None

        import re

        preamble_pattern = re.compile(
            r"^(voici|voil[àa]|titre\s*:|dict[ée]e\s*:)", re.IGNORECASE
        )
        bullet_prefix = re.compile(r"^\s{0,3}(?:[-*•]|\d+[\.\)])\s+")

        cleaned: list[str] = []
        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if preamble_pattern.match(line):
                continue
            line = bullet_prefix.sub("", line)
            line = line.replace("**", "").replace("__", "").replace("`", "")
            line = line.strip("# ").strip()
            if not line or not re.search(r"[A-Za-zÀ-ÿ]", line):
                continue
            cleaned.append(line)

        if len(cleaned) != self.SENTENCE_COUNT:
            return None

        for sentence in cleaned:
            word_count = len(sentence.split())
            if not (self.MIN_WORDS_PER_SENTENCE <= word_count <= self.MAX_WORDS_PER_SENTENCE):
                return None
            if "**" in sentence or "```" in sentence or re.match(r"^\d+[\.\)]\s", sentence):
                return None

        return cleaned

    # ------------------------------------------------------------------
    # Explications pédagogiques
    # ------------------------------------------------------------------
    def get_error_explanation(self, original_sentence: str, original_word: str, user_word: str) -> str:
        """Explique en une ou deux phrases pourquoi ``user_word`` est fautif par
        rapport à ``original_word``, dans le contexte de ``original_sentence``.

        Retourne toujours une chaîne. En cas d'échec, elle commence par
        ``FAILURE_PREFIX`` (contrat exploité par ``main.py``).
        """
        prompt = (
            "Tu es un coach d'orthographe bienveillant pour un enfant. La phrase "
            f"correcte est : \"{original_sentence}\". Mot correct : \"{original_word}\". "
            f"L'enfant a écrit : \"{user_word}\". Explique l'erreur en une ou deux "
            "phrases courtes et bienveillantes, 220 caractères maximum. Sois concret "
            "(orthographe, accord, conjugaison, homophone, ponctuation collée). "
            "N'écris jamais le mot \"cœur\". Réponds en texte brut uniquement, sans "
            "listes, sans astérisques, sans Markdown."
        )
        return self._ask(prompt, self.EXPLANATION_TIMEOUT_S)

    def get_insertion_explanation(self, original_sentence: str, user_word: str) -> str:
        """Explique pourquoi ``user_word`` est un mot ajouté en trop par rapport à
        ``original_sentence``. Mêmes garanties de retour que ``get_error_explanation``."""
        prompt = (
            "Tu es un coach d'orthographe bienveillant pour un enfant. Dans la "
            f"phrase correcte : \"{original_sentence}\", le mot \"{user_word}\" a "
            "été ajouté par erreur. Explique en une ou deux phrases courtes et "
            "bienveillantes, 220 caractères maximum, pourquoi il est en trop ou mal "
            "placé. N'écris jamais le mot \"cœur\". Réponds en texte brut "
            "uniquement : pas de Markdown, pas de listes, pas d'astérisques."
        )
        return self._ask(prompt, self.EXPLANATION_TIMEOUT_S)

    def _ask(self, prompt: str, timeout_s: float) -> str:
        """Appelle le modèle avec un timeout explicite et convertit tout échec en
        message lisible préfixé par ``FAILURE_PREFIX`` — ne lève jamais."""
        try:
            response = self._generate(prompt, timeout_s)
            return self._extract_text(response)
        except Exception as e:
            logger.error("Échec d'appel Gemini (explication): %s", e)
            return f"{self.FAILURE_PREFIX} : {self._describe_error(e)}"

    # ------------------------------------------------------------------
    # Catégorisation des erreurs
    # ------------------------------------------------------------------
    def _describe_error(self, exc: Exception) -> str:
        """Traduit une exception SDK/réseau en message actionnable pour
        l'utilisateur (clé API, quota, réseau, filtre de sécurité...), plutôt que
        de renvoyer une trace brute illisible pour un enfant ou un parent.

        ``genai.errors.APIError.code`` porte directement le code HTTP retourné par
        l'API (401/403/429/5xx...), ce qui est plus précis que la taxonomie
        d'exceptions de l'ancien SDK ``google.generativeai``."""
        if isinstance(exc, genai_errors.APIError):
            code = exc.code
            if code in (401, 403):
                return "clé API Gemini invalide ou refusée. Vérifiez la clé API configurée dans le fichier .env."
            if code == 429:
                return "quota Gemini dépassé. Réessayez plus tard ou vérifiez votre forfait."
            if code in (408, 504):
                return "le serveur Gemini n'a pas répondu à temps (délai réseau dépassé)."
            if code in (500, 502, 503):
                return "service Gemini injoignable (réseau ou serveur indisponible)."
            return f"erreur Gemini ({code}) : {exc.message or exc}"
        if isinstance(exc, httpx.TimeoutException):
            return "délai réseau dépassé en contactant Gemini."
        if isinstance(exc, httpx.HTTPError):
            return "connexion réseau impossible vers Gemini."
        if isinstance(exc, ValueError) and "SAFETY" in str(exc):
            return "la réponse a été bloquée par les filtres de sécurité de Gemini (thème probablement inapproprié)."
        if isinstance(exc, ValueError):
            return f"réponse Gemini vide ou invalide ({exc})."
        return f"erreur inattendue ({exc})."

class TTSService:
    # Délai réseau max pour la synthèse gTTS : évite un blocage indéfini si le
    # serveur Google Translate ne répond pas.
    GTTS_TIMEOUT_S = 10

    def __init__(self, temp_dir: str = "temp_audio") -> None:
        self.temp_dir = temp_dir
        if not os.path.exists(self.temp_dir): os.makedirs(self.temp_dir)
        self._cleanup_stale_temp_files()
        # Ce verrou ne sérialise plus que la lecture audio (pause musique -> son -> reprise
        # musique), pas la synthèse réseau gTTS : plusieurs speak() peuvent ainsi préparer
        # leur fichier en parallèle sans bloquer les autres appels.
        self.audio_lock = threading.Lock()
        self.mixer_initialized = False
        try:
            pygame.mixer.init()
            self.mixer_initialized = True
        except pygame.error as e:
            logger.error("Initialisation mixer Pygame échouée: %s", e)

    def _cleanup_stale_temp_files(self) -> None:
        """Supprime les fichiers audio temporaires laissés par une session précédente
        (ex : suppression échouée à cause d'un verrou fichier Windows) pour éviter
        que temp_audio/ ne grossisse indéfiniment."""
        try:
            for name in os.listdir(self.temp_dir):
                if name.startswith("temp_audio_") and name.endswith(".mp3"):
                    try:
                        os.remove(os.path.join(self.temp_dir, name))
                    except OSError:
                        pass  # probablement encore utilisé, on retentera au prochain lancement
        except OSError as e:
            logger.debug("Nettoyage de %s impossible: %s", self.temp_dir, e)

    def _get_temp_file(self) -> str:
        return os.path.join(self.temp_dir, f"temp_audio_{uuid.uuid4().hex}.mp3")

    def _prepare_text_for_speech(self, text: str) -> str:
        replacements = {",": " virgule", ".": " point", "!": " point d'exclamation", "?": " point d'interrogation", ";": " point-virgule", ":": " deux-points"}
        for p, r in replacements.items(): text = text.replace(p, r)
        return text

    def speak(self, text: str, is_dictation_sentence: bool = False) -> None:
        text_to_speak = self._prepare_text_for_speech(text) if is_dictation_sentence else text

        def _speak_thread() -> None:
            temp_file = self._get_temp_file()

            # Synthèse réseau HORS verrou : un appel gTTS lent ne doit pas bloquer
            # les autres threads de lecture qui attendent seulement audio_lock.
            try:
                tts = gTTS(text=text_to_speak, lang='fr', timeout=self.GTTS_TIMEOUT_S)
                tts.save(temp_file)
            except (gTTSError, requests.exceptions.RequestException, OSError) as e:
                logger.error("Erreur de synthèse TTS: %s", e)
                return

            with self.audio_lock:
                was_playing = pygame.mixer.music.get_busy()
                if was_playing:
                    pygame.mixer.music.pause()
                try:
                    if not self.mixer_initialized:
                        try:
                            pygame.mixer.init()
                            self.mixer_initialized = True
                        except pygame.error as e:
                            logger.error("Ré-init mixer Pygame échouée: %s", e)
                    sound = pygame.mixer.Sound(temp_file)
                    sound.play()
                    while pygame.mixer.get_busy(): time.sleep(0.1)
                except pygame.error as e:
                    logger.error("Erreur de lecture Pygame: %s", e)
                finally:
                    # On ne reprend la musique de fond que si c'est nous qui l'avons mise
                    # en pause (sinon on la démarrerait alors qu'elle était déjà arrêtée).
                    if was_playing:
                        pygame.mixer.music.unpause()
                    time.sleep(0.2)
                    if os.path.exists(temp_file):
                        try: os.remove(temp_file)
                        except PermissionError as e:
                            logger.debug("Impossible de supprimer %s (conflit probable): %s", temp_file, e)

        threading.Thread(target=_speak_thread, daemon=True).start()