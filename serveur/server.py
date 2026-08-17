# server.py
"""Serveur de scores commun à tous les mini-jeux — Python standard uniquement
(aucune dépendance). Un seul process sert tous les univers (dictée, maths,
histoire-géo, ...) : chaque requête est scopée par un champ `game`, pour que
les classements et profils de jeux différents ne se mélangent jamais.

À lancer sur le PC serveur (réseau local) :

    python server.py

Pour un lancement au démarrage de Windows sans installer de service : mettre un
raccourci vers LANCER_SERVEUR.bat (ce dossier) dans le dossier de démarrage
(touche Windows + R -> "shell:startup"). Ce script relance automatiquement le
serveur s'il s'arrête (crash, coupure réseau). Logs dans server.log (ce
dossier, rotation automatique à 2 Mo).

Variables d'environnement optionnelles (ou arguments) :
    DICTEE_SERVER_HOST   adresse d'écoute (défaut 0.0.0.0, i.e. toutes les interfaces)
    DICTEE_SERVER_PORT   port d'écoute (défaut 8000)
    DICTEE_DB_PATH       chemin du fichier SQLite (défaut ./scores.db)
    DICTEE_SERVER_TOKEN  jeton partagé optionnel. S'il est défini, le client doit
                         envoyer l'en-tête `X-Auth-Token` avec la même valeur.

Endpoints (tous scopés par `game`, ex: "dictee", "maths", "histoire-geo") :
    GET  /api/health                       -> état du service
    POST /api/identify                     -> {"name","game","avatar_path"?} => identité
                                               globale (pseudo + avatar, partagés entre
                                               jeux) + profil de CE jeu (crée/reconnecte
                                               le joueur ; avatar_path optionnel, mis à
                                               jour s'il est fourni)
    POST /api/profile                      -> {"name","game","profile", "credits"?,"xp"?,
                                               "badges"?,"streak"?,"last_play_date"?} =>
                                               sauvegarde le profil de CE jeu (obligatoire)
                                               et, si fournis, met à jour la progression
                                               GLOBALE (partagée entre tous les jeux)
    POST /api/scores                       -> {"name","game","difficulty","score",
                                               "duration","date"}
    GET  /api/scores/<game>/<difficulty>   -> classement (top 10) de ce jeu/niveau,
                                               une seule ligne par joueur (son
                                               meilleur score)
    GET  /api/leaderboard                  -> classement GLOBAL toutes missions
                                               confondues : joueurs triés par XP,
                                               avec grade, badges et récap par jeu

Le serveur est la seule source de vérité : un client ne peut soumettre qu'UN score
à la fois, jamais modifier/effacer le classement d'autrui (contrairement à l'ancien
système FTP où n'importe qui pouvait écraser tout le fichier).
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler

MAX_TOP = 10
MAX_LEADERBOARD = 50  # classement global : 4 joueurs aujourd'hui, large de côté
MAX_NAME_LENGTH = 40
MAX_GAME_LENGTH = 40
MAX_DIFFICULTY_LENGTH = 40
MAX_SCORE = 1_000_000  # plafond de sécurité générique, pas l'échelle 0-20 de la dictée
MAX_AVATAR_PATH_LENGTH = 200
MAX_BODY_SIZE = 65536  # 64 Ko : largement suffisant pour un profil joueur + score

# Progression globale (partagée entre tous les jeux, voir players.credits/xp/...)
MAX_CREDITS = 10_000_000
MAX_XP = 10_000_000
MAX_STREAK = 100_000
MAX_LAST_PLAY_DATE_LENGTH = 20
MAX_BADGES_COUNT = 200
MAX_BADGE_ID_LENGTH = 60

logger = logging.getLogger("games_score_server")


def _setup_logging() -> None:
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.log")
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    avatar_path TEXT,
    credits INTEGER NOT NULL DEFAULT 0,
    xp INTEGER NOT NULL DEFAULT 0,
    badges TEXT,
    streak INTEGER NOT NULL DEFAULT 0,
    last_play_date TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS player_profiles (
    player_id INTEGER NOT NULL REFERENCES players(id),
    game TEXT NOT NULL,
    profile TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (player_id, game)
);
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    game TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    score INTEGER NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scores_game_difficulty ON scores(game, difficulty);
"""


# Classement d'un jeu/niveau, dédoublonné : on ne garde que LA meilleure ligne de
# chaque joueur (meilleur score, puis le plus rapide à score égal), puis on trie
# ces lignes entre elles avec le même critère. Fragment partagé par `top` et
# `_rank_of` pour que le rang annoncé au joueur corresponde toujours exactement à
# la ligne qu'il voit. Attend les paramètres (game, difficulty) dans cet ordre.
_BEST_PER_PLAYER = (
    " FROM scores s JOIN players p ON p.id = s.player_id"
    " WHERE s.game = ? AND s.difficulty = ?"
    " AND s.id = (SELECT s2.id FROM scores s2"
    "             WHERE s2.player_id = s.player_id AND s2.game = s.game"
    "               AND s2.difficulty = s.difficulty"
    "             ORDER BY s2.score DESC, s2.duration ASC, s2.created_at ASC, s2.id ASC"
    "             LIMIT 1)"
    " ORDER BY s.score DESC, s.duration ASC, s.created_at ASC, s.id ASC"
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _validate_slug(value: str, field_name: str, max_length: int) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{field_name} ne peut pas être vide.")
    if len(value) > max_length:
        raise ValueError(f"{field_name} ne peut pas dépasser {max_length} caractères.")
    return value


def _validate_int(value, field_name: str, max_value: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} doit être un entier.")
    if not 0 <= value <= max_value:
        raise ValueError(f"{field_name} doit être entre 0 et {max_value}.")
    return value


def _validate_badges(value) -> list:
    if not isinstance(value, list):
        raise ValueError("badges doit être une liste.")
    if len(value) > MAX_BADGES_COUNT:
        raise ValueError(f"badges ne peut pas dépasser {MAX_BADGES_COUNT} entrées.")
    badges = []
    for item in value:
        item = str(item).strip()
        if not item:
            continue
        if len(item) > MAX_BADGE_ID_LENGTH:
            raise ValueError(f"Un identifiant de succès ne peut pas dépasser {MAX_BADGE_ID_LENGTH} caractères.")
        badges.append(item)
    return badges


class ScoreStore:
    """Accès SQLite thread-safe : une connexion par opération (jamais partagée entre threads)."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    @staticmethod
    def _parse_profile(raw):
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    def _get_or_create_player(self, name: str, avatar_path: str = None) -> dict:
        name = _validate_slug(name, "Le nom de Commandant", MAX_NAME_LENGTH)
        if avatar_path is not None:
            avatar_path = str(avatar_path).strip()
            if len(avatar_path) > MAX_AVATAR_PATH_LENGTH:
                raise ValueError(f"L'avatar ne peut pas dépasser {MAX_AVATAR_PATH_LENGTH} caractères.")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO players (name, created_at) VALUES (?, ?)",
                (name, _now()),
            )
            if avatar_path:
                conn.execute(
                    "UPDATE players SET avatar_path = ? WHERE name = ? COLLATE NOCASE",
                    (avatar_path, name),
                )
            row = conn.execute(
                "SELECT id, name, avatar_path, credits, xp, badges, streak, last_play_date"
                " FROM players WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
        return {
            "player_id": row["id"],
            "name": row["name"],
            "avatar_path": row["avatar_path"],
            "credits": row["credits"],
            "xp": row["xp"],
            "badges": self._parse_badges(row["badges"]),
            "streak": row["streak"],
            "last_play_date": row["last_play_date"],
        }

    @staticmethod
    def _parse_badges(raw):
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def identify(self, name: str, game: str, avatar_path: str = None) -> dict:
        """Identité globale (pseudo, avatar, crédits, XP, badges, série quotidienne —
        partagés entre TOUS les jeux) + profil du jeu demandé uniquement (ce qui reste
        propre à chaque jeu : meilleurs scores, inventaire d'armes de la dictée, ...)."""
        game = _validate_slug(game, "Le jeu", MAX_GAME_LENGTH)
        player = self._get_or_create_player(name, avatar_path)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile FROM player_profiles WHERE player_id = ? AND game = ?",
                (player["player_id"], game),
            ).fetchone()
        profile = self._parse_profile(row["profile"]) if row else None
        return {**player, "profile": profile}

    def save_profile(self, name: str, game: str, profile: dict, credits=None, xp=None,
                      badges=None, streak=None, last_play_date=None) -> dict:
        """Sauvegarde le profil DU JEU DEMANDÉ (`profile`, obligatoire) et, en option,
        met à jour la progression GLOBALE (`credits`/`xp`/`badges`/`streak`/
        `last_play_date`, partagée entre tous les jeux). Un champ global omis (None)
        n'est pas modifié — un jeu qui ne pousse que son profil ne doit jamais
        écraser le pactole accumulé sur un autre jeu."""
        game = _validate_slug(game, "Le jeu", MAX_GAME_LENGTH)
        if not isinstance(profile, dict):
            raise ValueError("Le profil doit être un objet JSON.")

        updates, params = [], []
        if credits is not None:
            updates.append("credits = ?")
            params.append(_validate_int(credits, "credits", MAX_CREDITS))
        if xp is not None:
            updates.append("xp = ?")
            params.append(_validate_int(xp, "xp", MAX_XP))
        if badges is not None:
            updates.append("badges = ?")
            params.append(json.dumps(_validate_badges(badges), ensure_ascii=False))
        if streak is not None:
            updates.append("streak = ?")
            params.append(_validate_int(streak, "streak", MAX_STREAK))
        if last_play_date is not None:
            last_play_date = str(last_play_date).strip()
            if len(last_play_date) > MAX_LAST_PLAY_DATE_LENGTH:
                raise ValueError(f"last_play_date ne peut pas dépasser {MAX_LAST_PLAY_DATE_LENGTH} caractères.")
            updates.append("last_play_date = ?")
            params.append(last_play_date)

        player = self._get_or_create_player(name)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO player_profiles (player_id, game, profile, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(player_id, game) DO UPDATE SET profile = excluded.profile,"
                " updated_at = excluded.updated_at",
                (player["player_id"], game, json.dumps(profile, ensure_ascii=False), _now()),
            )
            if updates:
                params.append(player["player_id"])
                conn.execute(f"UPDATE players SET {', '.join(updates)} WHERE id = ?", params)
        return {"player_id": player["player_id"], "name": player["name"]}

    def add_score(self, name: str, game: str, difficulty: str, score: int, duration: float, date: str) -> dict:
        game = _validate_slug(game, "Le jeu", MAX_GAME_LENGTH)
        difficulty = _validate_slug(difficulty, "La difficulté", MAX_DIFFICULTY_LENGTH)
        try:
            score = int(score)
        except (TypeError, ValueError):
            raise ValueError("Le score doit être un entier.")
        if not 0 <= score <= MAX_SCORE:
            raise ValueError(f"Le score doit être entre 0 et {MAX_SCORE}.")
        try:
            duration = float(duration or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration < 0:
            duration = 0.0
        date = (date or "").strip() or datetime.now().strftime("%Y-%m-%d")

        player = self._get_or_create_player(name)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO scores (player_id, game, difficulty, score, duration, date, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (player["player_id"], game, difficulty, score, duration, date, _now()),
            )
        return {
            "rank": self._rank_of(player["player_id"], game, difficulty),
            "total": self._total(game, difficulty),
            "top": self.top(game, difficulty),
        }

    def _rank_of(self, player_id: int, game: str, difficulty: str) -> int:
        """Place du joueur dans le classement dédoublonné (voir `top`) — donc la
        ligne qu'il voit vraiment à l'écran. Rejouer un moins bon score ne change
        pas son rang, et n'en fait jamais apparaître un second."""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT s.player_id{_BEST_PER_PLAYER}", (game, difficulty)
            ).fetchall()
        for index, row in enumerate(rows):
            if row["player_id"] == player_id:
                return index + 1
        return 0

    def _total(self, game: str, difficulty: str) -> int:
        """Nombre de JOUEURS classés (pas de tentatives) : cohérent avec le rang
        renvoyé par `_rank_of` — « 2e sur 4 » et non « 2e sur 37 essais »."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT player_id) AS n FROM scores WHERE game = ? AND difficulty = ?",
                (game, difficulty),
            ).fetchone()
        return row["n"]

    def top(self, game: str, difficulty: str) -> list:
        """Top 10 d'un jeu/niveau, **une seule ligne par joueur** (son meilleur
        score). Sans ce dédoublonnage, un joueur qui rejoue 15 fois occupait la
        moitié du classement avec ses propres tentatives et éjectait les
        autres — le défaut le plus visible quand une fratrie se compare."""
        game = _validate_slug(game, "Le jeu", MAX_GAME_LENGTH)
        difficulty = _validate_slug(difficulty, "La difficulté", MAX_DIFFICULTY_LENGTH)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT p.name, s.score, s.duration, s.date{_BEST_PER_PLAYER} LIMIT ?",
                (game, difficulty, MAX_TOP),
            ).fetchall()
        return [
            {"name": r["name"], "score": r["score"], "duration": r["duration"], "date": r["date"]}
            for r in rows
        ]

    def leaderboard(self, limit: int = MAX_LEADERBOARD) -> list:
        """Classement GLOBAL, toutes missions confondues — la vue « qui est le
        meilleur commandant » qui manquait : les classements par jeu × par
        niveau ne répondent jamais à cette question.

        Trié par XP (progression pondérée par la difficulté et jamais plafonnée,
        voir commun/scoring.py), pas par crédits : les crédits se dépensent en
        boutique, donc deux joueurs de même niveau réel peuvent afficher des
        soldes très différents.

        Le grade n'est PAS calculé ici : le serveur reste sans dépendance, et
        les paliers vivent dans commun/scoring.py (source unique, partagée avec
        les jeux). Le client déduit le grade de l'`xp` renvoyée.
        """
        with self._connect() as conn:
            players = conn.execute(
                "SELECT id, name, avatar_path, credits, xp, badges FROM players"
                " ORDER BY xp DESC, credits DESC, name COLLATE NOCASE ASC LIMIT ?",
                (limit,),
            ).fetchall()
            stats = conn.execute(
                "SELECT player_id, game, COUNT(*) AS plays, MAX(score) AS best"
                " FROM scores GROUP BY player_id, game"
            ).fetchall()
        per_player: dict = {}
        for row in stats:
            per_player.setdefault(row["player_id"], []).append(
                {"game": row["game"], "plays": row["plays"], "best_score": row["best"]}
            )
        entries = []
        for index, row in enumerate(players):
            games = sorted(per_player.get(row["id"], []), key=lambda g: (-g["plays"], g["game"]))
            entries.append({
                "rank": index + 1,
                "name": row["name"],
                "avatar_path": row["avatar_path"],
                "credits": row["credits"],
                "xp": row["xp"],
                "badges": self._parse_badges(row["badges"]),
                "games": games,
                "plays": sum(g["plays"] for g in games),
            })
        return entries


def make_handler(store: ScoreStore, token: str):
    """Construit une classe de handler liée à `store` et `token` (testable, sans état global)."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "GamesScoreServer/2.0"

        def log_message(self, format, *args):  # silence les logs d'accès par défaut
            pass

        # --- Helpers HTTP ---
        def _send_json(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > MAX_BODY_SIZE:
                raise ValueError("Corps de requête trop volumineux.")
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError:
                raise ValueError("Corps JSON invalide.")
            except UnicodeDecodeError:
                raise ValueError("Encodage invalide (attendu UTF-8).")

        def _authorized(self) -> bool:
            if not token:
                return True
            return self.headers.get("X-Auth-Token") == token

        # --- Routage ---
        def do_GET(self):
            try:
                path = self.path.split("?")[0].rstrip("/")
                if path in ("", "/api", "/api/health"):
                    return self._send_json(200, {"status": "ok", "time": _now()})
                if path == "/api/leaderboard":
                    return self._send_json(200, {"leaderboard": store.leaderboard()})
                prefix = "/api/scores/"
                if path.startswith(prefix):
                    parts = path[len(prefix):].split("/")
                    if len(parts) != 2:
                        return self._send_json(400, {"error": "Route attendue : /api/scores/<jeu>/<difficulte>"})
                    game, difficulty = parts
                    try:
                        scores = store.top(game, difficulty)
                    except ValueError as e:
                        return self._send_json(400, {"error": str(e)})
                    return self._send_json(200, {"scores": scores})
                self._send_json(404, {"error": "Route inconnue."})
            except Exception:
                logger.exception("Erreur inattendue sur GET %s", self.path)
                self._send_json(500, {"error": "Erreur interne du serveur."})

        def do_POST(self):
            try:
                if not self._authorized():
                    return self._send_json(401, {"error": "Jeton d'authentification invalide."})
                path = self.path.split("?")[0].rstrip("/")
                try:
                    data = self._read_json()
                    if path == "/api/identify":
                        return self._send_json(
                            200, store.identify(data.get("name"), data.get("game"), data.get("avatar_path"))
                        )
                    if path == "/api/profile":
                        return self._send_json(200, store.save_profile(
                            data.get("name"), data.get("game"), data.get("profile"),
                            credits=data.get("credits"), xp=data.get("xp"), badges=data.get("badges"),
                            streak=data.get("streak"), last_play_date=data.get("last_play_date"),
                        ))
                    if path == "/api/scores":
                        result = store.add_score(
                            data.get("name"),
                            data.get("game"),
                            data.get("difficulty"),
                            data.get("score"),
                            data.get("duration"),
                            data.get("date"),
                        )
                        return self._send_json(200, result)
                    self._send_json(404, {"error": "Route inconnue."})
                except ValueError as e:
                    self._send_json(400, {"error": str(e)})
            except Exception:
                logger.exception("Erreur inattendue sur POST %s", self.path)
                self._send_json(500, {"error": "Erreur interne du serveur."})

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True  # un client bloqué ne doit jamais empêcher l'arrêt du serveur
    allow_reuse_address = True  # redémarrage immédiat possible après un crash (pas de TIME_WAIT)


def main() -> None:
    _setup_logging()
    host = os.getenv("DICTEE_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("DICTEE_SERVER_PORT", "8000"))
    db_path = os.getenv(
        "DICTEE_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "scores.db")
    )
    token = os.getenv("DICTEE_SERVER_TOKEN", "")

    store = ScoreStore(db_path)
    try:
        server = _Server((host, port), make_handler(store, token))
    except OSError as e:
        logger.error("Impossible d'écouter sur %s:%s (%s). Le port est-il déjà utilisé ?", host, port, e)
        raise
    actual_port = server.server_address[1]
    print("=" * 50)
    print("  Serveur de scores — jeux éducatifs")
    print(f"  Écoute sur  http://{host}:{actual_port}")
    print(f"  Base SQLite : {db_path}")
    print(f"  Jeton : {'ACTIVÉ' if token else 'désactivé (réseau local ouvert)'}")
    print("  Ctrl+C pour arrêter.")
    print("=" * 50)
    logger.info("Démarrage du serveur sur %s:%s (base=%s, jeton=%s)", host, actual_port, db_path, bool(token))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")
        logger.info("Arrêt du serveur (Ctrl+C).")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
