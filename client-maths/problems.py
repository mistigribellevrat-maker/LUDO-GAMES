# problems.py
"""Génération des opérations mathématiques et logique de mission — aucune
dépendance Tk : entièrement testable sans fenêtre graphique (voir tests/).

Une "mission" = verrouiller une grille de protection à SEGMENTS cases en
répondant juste à des opérations. Le joueur a droit à MAX_MISTAKES erreurs
avant que les aliens ne franchissent la grille (défaite). Chaque niveau
scolaire met l'accent sur une opération dominante, de difficulté croissante à
l'intérieur du niveau — pas d'appel IA : génération déterministe, gratuite,
instantanée.
"""

import os
import random
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

# --- commun/ : barème de récompenses partagé par tous les jeux. Même résolution
# de chemin que main.py (dossier distribué ou dossier frère en dev), répétée ici
# pour que problems.py reste importable seul (tests, futurs outils). ---
_HERE = os.path.dirname(os.path.abspath(__file__))
for _commun_candidate in (os.path.join(_HERE, "commun"), os.path.join(_HERE, "..", "commun")):
    if os.path.isdir(_commun_candidate):
        if _commun_candidate not in sys.path:
            sys.path.insert(0, _commun_candidate)
        break

from scoring import LEVEL_MULTIPLIERS, clamp_ratio  # noqa: E402
from scoring import compute_rewards as _compute_rewards  # noqa: E402

LEVELS = ["CE1", "CE2", "CM1", "CM2", "Collège"]

SEGMENTS = 10
MAX_MISTAKES = 2  # 2 échecs autorisés ; le 3e déclenche la défaite

# Temps accordé par question (secondes) : décroît avec le niveau, comme la
# difficulté des calculs eux-mêmes. Un temps écoulé compte comme une mauvaise
# réponse (voir MathsApp._on_time_up dans main.py).
QUESTION_TIME_S: dict[str, int] = {
    "CE1": 14,
    "CE2": 12,
    "CM1": 10,
    "CM2": 9,
    "Collège": 8,
}

# Poids de ce jeu dans l'XP commune : une mission de maths dure autant qu'une
# dictée, elle vaut donc autant (voir commun/scoring.py::compute_rewards).
GAME_WEIGHT = 1.0


def evaluate_badges(victory: bool, mistakes: int, best_scores: dict, badges: list) -> list:
    """Succès de ce jeu — mêmes identifiants attendus par le catalogue partagé
    dans client-dictee/main.py (BADGES), car les badges sont une progression
    GLOBALE partagée entre tous les jeux (voir serveur/server.py). Ne mute pas
    `badges` (liste déjà débloquée) : retourne seulement les nouveaux
    identifiants, à ajouter par l'appelant."""
    newly = []

    def unlock(bid):
        if bid not in badges and bid not in newly:
            newly.append(bid)

    if victory:
        unlock("maths_premiere_victoire")
        if mistakes == 0:
            unlock("maths_grille_parfaite")
    if all(level in best_scores for level in LEVELS):
        unlock("maths_explorateur")
    return newly


def compute_rewards(level: str, score: int, segments: int = SEGMENTS) -> tuple[int, int]:
    """Crédits et XP gagnés pour une mission terminée avec `score` cases
    fermées sur `segments`. Retourne (0, 0) si `score` est nul (mission perdue
    sans avoir fermé la moindre case) — pas de récompense pour rien.

    Ne fait que traduire l'échelle propre à ce jeu (cases fermées / total) en
    ratio 0-1 : le barème lui-même vit dans commun/scoring.py, partagé avec la
    dictée et tout jeu à venir. Une réimplémentation locale finirait par
    diverger, et « 100 % au niveau Collège » ne voudrait plus dire la même
    chose d'un jeu à l'autre."""
    return _compute_rewards(level, clamp_ratio(score, segments), game_weight=GAME_WEIGHT)


@dataclass(frozen=True)
class Problem:
    question: str
    answer: int


# Intensité de fin de mission : les nombres s'élargissent progressivement à
# l'approche de la victoire (voir MathMission._intensity), jamais à l'approche
# de la défaite — durcir le jeu quand le joueur est déjà en difficulté serait
# décourageant, pas stimulant. Fourchette resserrée (1.0 -> 1.5) : ça doit
# rester le même niveau scolaire, juste un peu plus tendu sur la dernière ligne
# droite, pas un niveau différent.
MAX_INTENSITY = 1.5


def _addition_soustraction(low: int, high: int, intensity: float = 1.0) -> Problem:
    # `intensity` est toujours clampée à [1.0, MAX_INTENSITY] par l'appelant
    # (voir MathMission._intensity), donc pas de plafond supplémentaire ici.
    scaled_high = round(high * intensity)
    a = random.randint(low, scaled_high)
    b = random.randint(low, scaled_high)
    if random.random() < 0.5:
        return Problem(f"{a} + {b}", a + b)
    if a < b:
        a, b = b, a
    return Problem(f"{a} - {b}", a - b)


def _ce1(_level: str, intensity: float = 1.0) -> Problem:
    return _addition_soustraction(1, 20, intensity)


def _ce2(_level: str, intensity: float = 1.0) -> Problem:
    return _addition_soustraction(10, 100, intensity)


def _cm1(_level: str, intensity: float = 1.0) -> Problem:
    high = min(12, round(10 * intensity))
    a = random.randint(2, high)
    b = random.randint(2, high)
    return Problem(f"{a} × {b}", a * b)


def _cm2(_level: str, intensity: float = 1.0) -> Problem:
    diviseur = random.randint(2, min(12, round(10 * intensity)))
    quotient = random.randint(2, min(18, round(12 * intensity)))
    dividende = diviseur * quotient
    return Problem(f"{dividende} ÷ {diviseur}", quotient)


def _college(_level: str, intensity: float = 1.0) -> Problem:
    """Opérations mixtes avec priorité de la multiplication — calculée
    directement (pas d'`eval`), pour rester déterministe et sûr."""
    high = min(18, round(12 * intensity))
    a = random.randint(1, high)
    b = random.randint(1, high)
    c = random.randint(1, high)
    template = random.choice(["add_then_mul", "mul_then_add", "mul_then_sub"])
    if template == "add_then_mul":
        # a + b × c
        return Problem(f"{a} + {b} × {c}", a + b * c)
    if template == "mul_then_add":
        # a × b + c
        return Problem(f"{a} × {b} + {c}", a * b + c)
    # mul_then_sub : a × b - c, borné pour rester positif
    product = a * b
    c = min(c, product)
    return Problem(f"{a} × {b} - {c}", product - c)


_GENERATORS: dict[str, Callable[[str, float], Problem]] = {
    "CE1": _ce1,
    "CE2": _ce2,
    "CM1": _cm1,
    "CM2": _cm2,
    "Collège": _college,
}


def generate_problem(level: str, intensity: float = 1.0) -> Problem:
    generator = _GENERATORS.get(level)
    if generator is None:
        raise ValueError(f"Niveau inconnu : {level}")
    return generator(level, intensity)


@dataclass
class MathMission:
    """Machine à états d'une mission : suit la progression (segments fermés,
    erreurs) et fournit le problème courant. Ne touche à aucun widget Tk —
    l'UI ne fait que lire son état et appeler `answer()`."""

    level: str
    segments: int = SEGMENTS
    max_mistakes: int = MAX_MISTAKES
    closed: int = 0
    mistakes: int = 0
    finished: bool = False
    victory: bool = False
    current: Problem = field(init=False)

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"Niveau inconnu : {self.level}")
        self.current = generate_problem(self.level, self._intensity())

    def _intensity(self) -> float:
        """Monte progressivement de 1.0 à MAX_INTENSITY à l'approche de la
        victoire (jamais en fonction des erreurs — voir la note sur
        MAX_INTENSITY ci-dessus)."""
        if self.segments <= 0:
            return 1.0
        progress = self.closed / self.segments
        return 1.0 + (MAX_INTENSITY - 1.0) * progress

    def answer(self, value) -> str:
        """Soumet une réponse. Retourne "correct", "wrong", "victory" ou
        "defeat". N'a plus d'effet une fois la mission terminée."""
        if self.finished:
            return "victory" if self.victory else "defeat"

        try:
            is_correct = int(value) == self.current.answer
        except (TypeError, ValueError):
            is_correct = False

        if is_correct:
            self.closed += 1
            if self.closed >= self.segments:
                self.finished = True
                self.victory = True
                return "victory"
            self.current = generate_problem(self.level, self._intensity())
            return "correct"

        self.mistakes += 1
        if self.mistakes > self.max_mistakes:
            self.finished = True
            self.victory = False
            return "defeat"
        self.current = generate_problem(self.level, self._intensity())
        return "wrong"

    @property
    def mistakes_remaining(self) -> int:
        return max(0, self.max_mistakes - self.mistakes)
