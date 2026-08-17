# commun/server_client.py
"""Client HTTP partagé du serveur de scores (voir serveur/server.py).

Ce module est la source de vérité unique pour parler au serveur de scores,
réutilisée par chaque jeu (client-dictee, et les futurs client-maths,
client-histoire-geo, ...). Chaque jeu le référence via son propre `sys.path`
en développement, et reçoit sa propre copie vendue dans son manifest de
distribution (voir generate_manifest.py côté client) — chaque installation
joueur reste autonome.

Remplace l'ancien système FTP (identifiants en clair, tout joueur pouvait
écraser le classement) par une API REST en écriture seule, où le serveur est
la seule source de vérité.
"""

import json
import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# Résolu par rapport au répertoire courant du JEU qui importe ce module (pas à
# l'emplacement de ce fichier, qui vit dans un dossier partagé entre jeux).
# `server_config.json`/`server_config.local.json` doivent rester propres à
# chaque jeu (chacun avec son propre "game"). Le jeu est toujours lancé avec
# le CWD sur son propre dossier (`python main.py` en dev, ou via launcher.py
# qui fait un `Popen` héritant de son CWD), donc c'est fiable.
_CONFIG_DIR = os.getcwd()
_LOCAL_SERVER_CONFIG = os.path.join(_CONFIG_DIR, "server_config.local.json")
_DEFAULT_SERVER_CONFIG = os.path.join(_CONFIG_DIR, "server_config.json")

_DEFAULT_GAME = "dictee"


def _read_json_file(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Config serveur illisible (%s): %s", path, e)
        return {}


def load_server_config() -> dict:
    """Résout la config du serveur de scores.

    `server_url`/`server_token`, par ordre de priorité :
    1. `server_config.local.json` — réglage propre à ce PC (fait via Paramètres),
       jamais distribué, jamais écrasé par une mise à jour du jeu.
    2. `server_config.json` — valeurs par défaut distribuées avec le jeu.
    3. Variables d'environnement `SERVER_URL`/`SERVER_TOKEN` (rétro-compatibilité
       et confort de développement local).

    `game` est résolu SÉPARÉMENT, toujours depuis `server_config.json` (ou la
    variable d'environnement `SERVER_GAME` à défaut) : c'est une propriété du
    jeu installé dans ce dossier, jamais du PC. `server_config.local.json` ne
    contient jamais de `game` (voir `save_server_config_override`) — le lire
    comme prioritaire ferait retomber silencieusement sur "dictee" dès qu'un
    joueur corrige l'adresse du serveur dans Paramètres sur un AUTRE jeu que
    la dictée, mélangeant sa progression avec le mauvais jeu côté serveur.
    """
    server_url, server_token = "", ""
    for path in (_LOCAL_SERVER_CONFIG, _DEFAULT_SERVER_CONFIG):
        data = _read_json_file(path)
        url = (data.get("server_url") or "").strip()
        if url:
            server_url = url
            server_token = (data.get("server_token") or "").strip()
            break
    if not server_url:
        server_url = (os.getenv("SERVER_URL") or "").strip()
        server_token = (os.getenv("SERVER_TOKEN") or "").strip()

    game = (_read_json_file(_DEFAULT_SERVER_CONFIG).get("game") or "").strip()
    if not game:
        game = (os.getenv("SERVER_GAME") or "").strip()

    return {"server_url": server_url, "server_token": server_token, "game": game}


def save_server_config_override(server_url: str, server_token: str = "") -> None:
    """Enregistre le réglage serveur propre à ce PC dans `server_config.local.json`.

    Fichier volontairement exclu du manifest de distribution (voir
    generate_manifest.py côté client) : une mise à jour du jeu via le
    launcher ne l'écrase jamais. Ne modifie pas le `game` : celui-ci est fixé
    par le jeu lui-même (server_config.json), pas par l'utilisateur.
    """
    server_url = (server_url or "").strip()
    with open(_LOCAL_SERVER_CONFIG, "w", encoding="utf-8") as f:
        json.dump({"server_url": server_url, "server_token": (server_token or "").strip()}, f, indent=4)


class HighScoreService:
    """Client HTTP du serveur de scores (PC serveur, réseau local).

    Toutes les requêtes sont scopées au jeu (`game`) résolu à la construction
    (config locale > config distribuée > variable d'environnement > "dictee"
    par défaut), pour que les classements/profils de jeux différents ne se
    mélangent jamais sur un même serveur.
    """

    def __init__(self, game: str = None) -> None:
        config = load_server_config()
        self.base_url = config["server_url"].rstrip("/")
        self.token = config["server_token"]
        self.game = (game or config.get("game") or _DEFAULT_GAME).strip() or _DEFAULT_GAME
        if not self.base_url:
            raise ConnectionError(
                "Adresse du serveur de scores non configurée. "
                "Renseignez-la dans Paramètres, ou dans server_config.json/.env "
                "(ex: http://192.168.1.20:8000)."
            )

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Auth-Token"] = self.token
        return headers

    def _request(self, method: str, path: str, payload: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            if method == "GET":
                response = requests.get(url, headers=self._headers(), timeout=10)
            else:
                response = requests.post(url, json=payload, headers=self._headers(), timeout=10)
            if response.status_code == 401:
                raise ConnectionError("Jeton d'authentification refusé par le serveur (SERVER_TOKEN).")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error("Erreur de connexion au serveur de scores (%s): %s", url, e)
            raise ConnectionError(f"Impossible de joindre le serveur de scores : {e}")

    def identify(self, name: str, avatar_path: str = None) -> dict:
        """Enregistre (ou reconnecte) le joueur au démarrage.
        Retourne {player_id, name, avatar_path, credits, xp, badges, streak,
        last_play_date, profile}.

        Le pseudo, l'avatar ET la progression globale (crédits, XP, badges, série
        quotidienne) sont une identité PARTAGÉE entre tous les jeux — un crédit
        gagné en maths est visible en dictée, et inversement. Seul `profile`
        (meilleurs scores, inventaire propre à un jeu, ...) est spécifique au jeu
        courant. `avatar_path` est optionnel : à ne passer que lorsque le joueur
        vient d'en choisir un (sinon la valeur déjà enregistrée côté serveur est
        conservée)."""
        payload = {"name": name, "game": self.game}
        if avatar_path:
            payload["avatar_path"] = avatar_path
        return self._request("POST", "/api/identify", payload)

    def save_profile(self, name: str, profile: dict, credits: int = None, xp: int = None,
                      badges: list = None, streak: int = None, last_play_date: str = None) -> None:
        """Pousse le profil du jeu courant (`profile`, obligatoire) et, en option,
        la progression globale partagée entre tous les jeux (`credits`/`xp`/
        `badges`/`streak`/`last_play_date`). Un champ global omis n'est PAS
        remis à zéro côté serveur — seuls les champs explicitement fournis sont
        mis à jour."""
        payload = {"name": name, "game": self.game, "profile": profile}
        for key, value in (
            ("credits", credits), ("xp", xp), ("badges", badges),
            ("streak", streak), ("last_play_date", last_play_date),
        ):
            if value is not None:
                payload[key] = value
        self._request("POST", "/api/profile", payload)

    def get_scores(self, difficulty: str) -> list[dict]:
        data = self._request("GET", f"/api/scores/{self.game}/{difficulty}")
        return data.get("scores", [])

    def get_leaderboard(self) -> list[dict]:
        """Classement GLOBAL, toutes missions confondues : un joueur par ligne,
        trié par XP décroissante. Volontairement NON scopé par `game` — c'est
        justement la vue qui agrège tous les jeux (voir serveur/server.py::
        ScoreStore.leaderboard). Chaque entrée porte `rank`, `name`, `xp`,
        `credits`, `badges` et un récap `games` (parties jouées et meilleur
        score par jeu). Le grade se déduit de `xp` via commun/scoring.py."""
        data = self._request("GET", "/api/leaderboard")
        return data.get("leaderboard", [])

    def add_score(self, difficulty: str, name: str, score: int, duration) -> None:
        self._request("POST", "/api/scores", {
            "name": name,
            "game": self.game,
            "difficulty": difficulty,
            "score": int(score),
            "duration": float(duration or 0),
            "date": datetime.now().strftime("%Y-%m-%d"),
        })
