# problems.py
"""Génération des vagues d'ennemis et logique de mission — aucune dépendance
Tk : entièrement testable sans fenêtre graphique (voir tests/).

Une "mission" = repousser SEGMENTS vagues en tirant sur le vaisseau portant la
bonne forme conjuguée avant qu'un vaisseau n'atteigne le dôme. Le joueur a
droit à MAX_MISTAKES erreurs (mauvais vaisseau touché, ou vaisseau non
intercepté) avant la défaite. Le contenu linguistique (verbes/formes) vit
dans conjugation_data.py ; ce module ne fait que piocher dedans et suivre
l'état de la mission — même séparation que client-maths/problems.py."""

import os
import random
import sys
from dataclasses import dataclass, field

# --- commun/ : barème de récompenses partagé par tous les jeux. Même
# résolution de chemin que main.py, répétée ici pour que ce module reste
# importable seul (tests, futurs outils). ---
_HERE = os.path.dirname(os.path.abspath(__file__))
for _commun_candidate in (os.path.join(_HERE, "commun"), os.path.join(_HERE, "..", "commun")):
    if os.path.isdir(_commun_candidate):
        if _commun_candidate not in sys.path:
            sys.path.insert(0, _commun_candidate)
        break

from scoring import clamp_ratio  # noqa: E402
from scoring import compute_rewards as _compute_rewards  # noqa: E402

from conjugation_data import PRONOUN_LABELS, TENSE_BY_LEVEL, VERB_POOL_BY_LEVEL, VERBS  # noqa: E402

LEVELS = ["CE1", "CE2", "CM1", "CM2", "Collège"]

SEGMENTS = 10
MAX_MISTAKES = 2  # 2 échecs autorisés ; le 3e déclenche la défaite

# Vaisseaux par vague (1 correct + N leurres) : plus de leurres = plus dur à
# repérer. Temps de vol (secondes) avant qu'un vaisseau non intercepté
# n'atteigne le dôme : décroît avec le niveau, comme QUESTION_TIME_S dans
# client-maths/problems.py.
SHIP_COUNT: dict[str, int] = {"CE1": 3, "CE2": 3, "CM1": 4, "CM2": 4, "Collège": 5}
FLIGHT_TIME_S: dict[str, float] = {"CE1": 9, "CE2": 8, "CM1": 7, "CM2": 6, "Collège": 5}

# Poids de ce jeu dans l'XP commune : une mission de conjugaison dure autant
# qu'une dictée ou une grille de maths, elle vaut donc autant (voir
# commun/scoring.py::compute_rewards).
GAME_WEIGHT = 1.0


@dataclass(frozen=True)
class ShipForm:
    text: str
    is_correct: bool


@dataclass(frozen=True)
class Wave:
    verb: str
    tense: str
    pronoun_index: int
    ships: list[ShipForm]

    @property
    def correct_text(self) -> str:
        for ship in self.ships:
            if ship.is_correct:
                return ship.text
        raise ValueError("Vague sans vaisseau correct (bug de génération)")


def generate_wave(level: str, n_ships: int | None = None) -> Wave:
    """Choisit un temps et un verbe autorisés pour `level`, puis compose une
    vague : un vaisseau correct + des leurres qui sont TOUJOURS d'autres
    formes réelles du même verbe (même pronom, autre temps) — jamais une
    chaîne inventée (voir conjugation_data.py)."""
    if level not in TENSE_BY_LEVEL:
        raise ValueError(f"Niveau inconnu : {level}")
    tense = random.choice(TENSE_BY_LEVEL[level])
    verb = random.choice(VERB_POOL_BY_LEVEL[level])
    pronoun_index = random.randrange(len(PRONOUN_LABELS))
    correct_text = VERBS[verb][tense][pronoun_index]

    decoy_pool = [
        VERBS[verb][other_tense][pronoun_index]
        for other_tense in VERBS[verb]
        if other_tense != tense
    ]
    decoy_pool = [text for text in dict.fromkeys(decoy_pool) if text != correct_text]

    n_ships = n_ships if n_ships is not None else SHIP_COUNT[level]
    n_decoys = min(n_ships - 1, len(decoy_pool))
    decoys = random.sample(decoy_pool, n_decoys)

    ships = [ShipForm(correct_text, True)] + [ShipForm(text, False) for text in decoys]
    random.shuffle(ships)
    return Wave(verb=verb, tense=tense, pronoun_index=pronoun_index, ships=ships)


def evaluate_badges(victory: bool, mistakes: int, best_scores: dict, badges: list) -> list:
    """Succès de ce jeu — mêmes conventions que client-maths/problems.py::
    evaluate_badges (ids préfixés `conj_`, catalogue de noms affichables dans
    commun/badges.py). Ne mute pas `badges` : retourne seulement les
    identifiants nouvellement débloqués."""
    newly = []

    def unlock(bid):
        if bid not in badges and bid not in newly:
            newly.append(bid)

    if victory:
        unlock("conj_premiere_victoire")
        if mistakes == 0:
            unlock("conj_defense_parfaite")
    if all(level in best_scores for level in LEVELS):
        unlock("conj_polyglotte")
    return newly


def compute_rewards(level: str, score: int, segments: int = SEGMENTS) -> tuple[int, int]:
    """Crédits et XP gagnés pour une mission terminée avec `score` vagues
    repoussées sur `segments`. Ne fait que traduire l'échelle propre à ce jeu
    en ratio 0-1 : le barème lui-même vit dans commun/scoring.py, partagé
    avec la dictée et les maths."""
    return _compute_rewards(level, clamp_ratio(score, segments), game_weight=GAME_WEIGHT)


@dataclass
class ConjugationMission:
    """Machine à états d'une mission : suit la progression (vagues
    repoussées, erreurs) et fournit la vague courante. Ne touche à aucun
    widget Tk — l'UI ne fait que lire son état et appeler `resolve()`."""

    level: str
    segments: int = SEGMENTS
    max_mistakes: int = MAX_MISTAKES
    closed: int = 0
    mistakes: int = 0
    finished: bool = False
    victory: bool = False
    current: Wave = field(init=False)

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"Niveau inconnu : {self.level}")
        self.current = generate_wave(self.level)

    def resolve(self, hit: bool) -> str:
        """Résout l'issue d'une vague. `hit=True` : le bon vaisseau a été
        touché à temps. `hit=False` : un mauvais vaisseau a été touché, OU un
        vaisseau a atteint le dôme sans être intercepté — les deux comptent
        comme une erreur, indifféremment (voir ui_components.py::TurretScene).
        Retourne "correct"/"wrong"/"victory"/"defeat". N'a plus d'effet une
        fois la mission terminée."""
        if self.finished:
            return "victory" if self.victory else "defeat"

        if hit:
            self.closed += 1
            if self.closed >= self.segments:
                self.finished = True
                self.victory = True
                return "victory"
            self.current = generate_wave(self.level)
            return "correct"

        self.mistakes += 1
        if self.mistakes > self.max_mistakes:
            self.finished = True
            self.victory = False
            return "defeat"
        self.current = generate_wave(self.level)
        return "wrong"

    @property
    def mistakes_remaining(self) -> int:
        return max(0, self.max_mistakes - self.mistakes)
