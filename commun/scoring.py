# commun/scoring.py
"""Barème commun de récompenses et de grades — partagé par TOUS les jeux.

C'est le contrat unique qui garantit qu'« une mission réussie à 100 % au niveau
Collège » vaut exactement la même chose en dictée, en maths et dans tout jeu à
venir. Avant ce module, chaque jeu réimplémentait sa propre formule
(client-dictee/main.py et client-maths/problems.py) : elles se ressemblaient par
discipline, rien ne garantissait qu'elles le restent.

Deux monnaies, deux rôles bien distincts :

* **Crédits** — argent de poche, DÉPENSABLE en boutique. Le solde reflète autant
  ce qu'on a gagné que ce qu'on a économisé : inutilisable pour se comparer.
* **XP** — preuve de niveau, jamais dépensable, ne fait que croître. C'est la
  seule stat sur laquelle les joueurs se comparent (classement global du Hub,
  voir serveur/server.py::ScoreStore.leaderboard).

Les deux sont pondérés par la difficulté (`LEVEL_MULTIPLIERS`) : un sans-faute
au Collège rapporte 2× un sans-faute en CE1. Avant, seuls les crédits l'étaient
— répéter le niveau le plus facile était donc la façon la plus rapide de monter
en grade, exactement l'inverse de l'effet recherché.

Un jeu n'a que deux choses à fournir : un `ratio` de réussite entre 0 et 1
(quelle que soit son échelle interne : /20 en dictée, /10 cases en maths) et le
niveau joué.
"""

# Multiplicateur de récompense par niveau scolaire. Un jeu peut passer sa propre
# table à compute_rewards() si ses niveaux diffèrent, mais tant que les niveaux
# sont les mêmes, la table commune garde les jeux comparables entre eux.
LEVEL_MULTIPLIERS = {
    "CE1": 1.0,
    "CE2": 1.25,
    "CM1": 1.5,
    "CM2": 1.75,
    "Collège": 2.0,
}

# Barème de base pour une mission réussie à 100 % en CE1 (multiplicateur 1.0).
CREDITS_PER_MISSION = 100  # inchangé : c'est le barème crédits historique
XP_PER_MISSION = 200       # inchangé en CE1 (20 points × 10 XP historiques)

# Grades affichés (progression XP visible). Seuils recalibrés pour l'XP
# désormais pondérée par la difficulté : une mission rapporte 200 XP (CE1) à
# 400 XP (Collège), donc les anciens paliers (max 1000 XP) étaient atteints en
# 3 parties. L'écart entre paliers double à chaque fois : le sommet reste un
# horizon lointain (~190 missions) plutôt qu'une prochaine étape.
GRADES = [
    {"name": "Recrue", "xp": 0},
    {"name": "Soldat", "xp": 500},
    {"name": "Caporal", "xp": 1500},
    {"name": "Vétéran", "xp": 3500},
    {"name": "Grand Stratège", "xp": 7000},
    {"name": "Amiral", "xp": 14000},
    {"name": "Maître de Guerre", "xp": 28000},
    {"name": "Légende Galactique", "xp": 56000},
]


def clamp_ratio(score, maximum) -> float:
    """Ratio de réussite d'un jeu ramené entre 0 et 1, quelle que soit son
    échelle interne (score/20 en dictée, cases/10 en maths). Retourne 0 pour un
    maximum absurde plutôt que de lever : un barème ne doit jamais faire planter
    une fin de mission."""
    try:
        maximum = float(maximum)
        if maximum <= 0:
            return 0.0
        return max(0.0, min(1.0, float(score) / maximum))
    except (TypeError, ValueError):
        return 0.0


def compute_rewards(level: str, ratio: float, level_multipliers: dict = None,
                    game_weight: float = 1.0) -> tuple[int, int]:
    """Récompenses d'une mission terminée. Retourne `(crédits, xp)`.

    `ratio` : réussite entre 0 et 1 (voir clamp_ratio).
    `game_weight` : pondère l'XP d'un jeu plus long ou plus court que les
    autres, sans toucher aux crédits (l'économie de boutique reste commune).
    Laissé à 1.0 partout aujourd'hui — les deux jeux durent le même temps.

    Une mission à 0 ne rapporte rien : pas de récompense pour rien.
    """
    ratio = clamp_ratio(ratio, 1)
    if ratio <= 0:
        return 0, 0
    multipliers = level_multipliers if level_multipliers is not None else LEVEL_MULTIPLIERS
    mult = multipliers.get(level, 1.0)
    credits = int(round(ratio * CREDITS_PER_MISSION * mult))
    xp = int(round(ratio * XP_PER_MISSION * mult * game_weight))
    return credits, xp


def grade_info(xp: int) -> tuple[str, str | None, int, int]:
    """Grade courant d'un joueur. Retourne
    `(grade, grade_suivant_ou_None, xp_dans_le_palier, xp_requis_pour_le_suivant)`.

    Au dernier palier, `grade_suivant` vaut None et `xp_requis` vaut 0 — mais
    l'XP, elle, continue de monter sans plafond : c'est ce qui permet de
    départager deux joueurs déjà au grade maximum dans le classement global.
    """
    try:
        xp = int(xp or 0)
    except (TypeError, ValueError):
        xp = 0
    current, nxt = GRADES[0], None
    for i, grade in enumerate(GRADES):
        if xp >= grade["xp"]:
            current = grade
            nxt = GRADES[i + 1] if i + 1 < len(GRADES) else None
    if nxt:
        return current["name"], nxt["name"], xp - current["xp"], nxt["xp"] - current["xp"]
    return current["name"], None, xp, 0


def grade_name(xp: int) -> str:
    return grade_info(xp)[0]
