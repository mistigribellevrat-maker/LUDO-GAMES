# commun/logs.py
"""Journalisation fichier partagée par les jeux.

Les jeux se lancent désormais sans fenêtre console (`pythonw`, voir les
LANCER.bat) : la console qui restait ouverte derrière le jeu a disparu, et avec
elle le seul endroit où s'affichaient les erreurs. Tout part donc dans un
fichier `game.log` à côté du jeu.

Trois sources d'erreurs sont capturées, sans quoi un plantage serait totalement
silencieux pour l'utilisateur comme pour le dépannage :
* les messages `logging` des modules ;
* les exceptions non rattrapées du programme (`sys.excepthook`) ;
* les exceptions levées dans un callback Tk (`report_callback_exception`), qui
  ne passent PAS par `sys.excepthook` — c'est le cas le plus fréquent dans une
  application Tk, où presque tout le code tourne dans un callback.
"""

import logging
import os
import sys
import tkinter as tk
from logging.handlers import RotatingFileHandler

LOG_FILENAME = "game.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 2


def setup_file_logging(app_dir: str, filename: str = LOG_FILENAME,
                       level: int = logging.INFO) -> str | None:
    """Installe la journalisation fichier (rotation à 1 Mo, 2 archives).

    Retourne le chemin du journal, ou None si le fichier n'est pas ouvrable
    (dossier en lecture seule, disque plein) : un problème de journalisation ne
    doit jamais empêcher un enfant de jouer.
    """
    log_path = os.path.join(app_dir, filename)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if any(getattr(h, "_ludo_file_handler", False) for h in root_logger.handlers):
        return log_path  # déjà installé (double appel)
    try:
        handler = RotatingFileHandler(log_path, maxBytes=MAX_BYTES,
                                      backupCount=BACKUP_COUNT, encoding="utf-8")
    except OSError as e:
        logging.basicConfig(level=level)
        logging.getLogger(__name__).warning("Journal fichier indisponible (%s): %s", log_path, e)
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    handler._ludo_file_handler = True
    root_logger.addHandler(handler)

    # Sans console, une exception non rattrapée disparaîtrait sans laisser de trace.
    previous_hook = sys.excepthook

    def _log_uncaught(exc_type, exc_value, exc_tb):
        logging.getLogger("uncaught").critical(
            "Exception non rattrapée", exc_info=(exc_type, exc_value, exc_tb))
        previous_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _log_uncaught
    logging.getLogger(__name__).info("--- Démarrage (journal : %s) ---", log_path)
    return log_path


def log_tk_exceptions(root: tk.Tk) -> None:
    """Envoie aussi au journal les exceptions levées dans un callback Tk.

    Tkinter les intercepte lui-même et les imprime sur stderr : sans console,
    elles seraient perdues, et l'application continue de tourner comme si de
    rien n'était (le symptôme classique du « bouton qui ne fait rien »).
    """
    def _report(exc_type, exc_value, exc_tb):
        logging.getLogger("tk").error(
            "Exception dans un callback Tk", exc_info=(exc_type, exc_value, exc_tb))

    root.report_callback_exception = _report
