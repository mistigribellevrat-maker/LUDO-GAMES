# services.py
"""Services audio du jeu de maths — copie allégée de la partie générique de
client-dictee/services.py (TTSService), sans les services propres à la
dictée (Gemini, lecteur vidéo, anti-triche). Pas d'appel IA dans ce jeu : les
opérations sont générées localement (voir problems.py), donc pas de clé API
requise pour y jouer.
"""

import logging
import os
import threading
import time
import uuid

import pygame
import requests
from gtts import gTTS, gTTSError

logger = logging.getLogger(__name__)


class TTSService:
    """Synthèse vocale (gTTS + pygame), utilisée pour la transmission d'intro
    du space marine. Voir client-dictee/services.py::TTSService pour le
    contexte détaillé de chaque choix (verrouillage, nettoyage, timeouts) —
    logique identique, dupliquée ici pour que ce jeu reste un dossier
    autonome (voir commun/ pour ce qui est réellement partagé)."""

    GTTS_TIMEOUT_S = 10

    def __init__(self, temp_dir: str = "temp_audio") -> None:
        self.temp_dir = temp_dir
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
        self._cleanup_stale_temp_files()
        self.audio_lock = threading.Lock()
        self.mixer_initialized = False
        try:
            pygame.mixer.init()
            self.mixer_initialized = True
        except pygame.error as e:
            logger.error("Initialisation mixer Pygame échouée: %s", e)

    def _cleanup_stale_temp_files(self) -> None:
        try:
            for name in os.listdir(self.temp_dir):
                if name.startswith("temp_audio_") and name.endswith(".mp3"):
                    try:
                        os.remove(os.path.join(self.temp_dir, name))
                    except OSError:
                        pass
        except OSError as e:
            logger.debug("Nettoyage de %s impossible: %s", self.temp_dir, e)

    def _get_temp_file(self) -> str:
        return os.path.join(self.temp_dir, f"temp_audio_{uuid.uuid4().hex}.mp3")

    def speak(self, text: str) -> None:
        def _speak_thread() -> None:
            temp_file = self._get_temp_file()
            try:
                tts = gTTS(text=text, lang="fr", timeout=self.GTTS_TIMEOUT_S)
                tts.save(temp_file)
            except (gTTSError, requests.exceptions.RequestException, OSError) as e:
                logger.error("Erreur de synthèse TTS: %s", e)
                return

            with self.audio_lock:
                try:
                    if not self.mixer_initialized:
                        try:
                            pygame.mixer.init()
                            self.mixer_initialized = True
                        except pygame.error as e:
                            logger.error("Ré-init mixer Pygame échouée: %s", e)
                    sound = pygame.mixer.Sound(temp_file)
                    sound.play()
                    while pygame.mixer.get_busy():
                        time.sleep(0.1)
                except pygame.error as e:
                    logger.error("Erreur de lecture Pygame: %s", e)
                finally:
                    time.sleep(0.2)
                    if os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                        except PermissionError as e:
                            logger.debug("Impossible de supprimer %s (conflit probable): %s", temp_file, e)

        threading.Thread(target=_speak_thread, daemon=True).start()
