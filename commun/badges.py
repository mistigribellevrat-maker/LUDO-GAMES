# commun/badges.py
"""Catalogue des succès, partagé par TOUS les jeux.

Les badges sont une progression GLOBALE : le serveur les stocke sur le joueur,
pas sur le jeu (voir serveur/server.py, table `players.badges`). Un succès
décroché en maths doit donc s'afficher avec le même nom dans la dictée, dans le
Panthéon des succès et dans le classement du Hub.

Avant, le catalogue vivait dans client-dictee/main.py et le jeu de maths en
gardait une copie partielle : le Hub, lui, n'avait rien et affichait les
identifiants bruts (« Sans faute cm1 »). Une seule liste ici, importée partout.

Chaque jeu déclare ses propres succès dans la section qui lui correspond, en
préfixant leur identifiant par le nom du jeu (sauf la dictée, historique et
non préfixée : renommer ses identifiants effacerait les succès déjà acquis
côté serveur).
"""

BADGES = [
    # --- Dictée (identifiants historiques, non préfixés) ---
    {"id": "premiere_victoire", "name": "Première victoire", "desc": "Remporter une mission (score > 0)."},
    {"id": "sans_faute", "name": "Sans faute", "desc": "Terminer une mission avec 20/20 points."},
    {"id": "eclair", "name": "Éclair", "desc": "Terminer une mission en moins de 3 minutes."},
    {"id": "explorateur", "name": "Explorateur", "desc": "Jouer sur les 5 niveaux de menace."},
    {"id": "grand_strategie", "name": "Grand Stratège", "desc": "Remporter une mission au niveau Collège."},
    {"id": "riche", "name": "Crésus", "desc": "Atteindre 300 crédits."},
    # Sans-faute par niveau : le générique "sans_faute" ci-dessus ne distinguait
    # pas les niveaux, donc rien à viser une fois le Collège maîtrisé.
    {"id": "sans_faute_ce1", "name": "Sans faute — CE1", "desc": "Terminer une mission CE1 avec 20/20 points."},
    {"id": "sans_faute_ce2", "name": "Sans faute — CE2", "desc": "Terminer une mission CE2 avec 20/20 points."},
    {"id": "sans_faute_cm1", "name": "Sans faute — CM1", "desc": "Terminer une mission CM1 avec 20/20 points."},
    {"id": "sans_faute_cm2", "name": "Sans faute — CM2", "desc": "Terminer une mission CM2 avec 20/20 points."},
    {"id": "sans_faute_college", "name": "Sans faute — Collège", "desc": "Terminer une mission Collège avec 20/20 points."},
    # Paliers de série quotidienne (streak global, partagé entre les jeux).
    {"id": "streak_7", "name": "Semaine parfaite", "desc": "Série de 7 jours d'affilée."},
    {"id": "streak_30", "name": "Mois de fer", "desc": "Série de 30 jours d'affilée."},
    {"id": "streak_100", "name": "Légende", "desc": "Série de 100 jours d'affilée."},

    # --- Grille de Protection (maths) ---
    {"id": "maths_premiere_victoire", "name": "Grille verrouillée", "desc": "Remporter une mission de maths."},
    {"id": "maths_grille_parfaite", "name": "Grille intacte", "desc": "Remporter une mission de maths sans la moindre erreur."},
    {"id": "maths_explorateur", "name": "Ingénieur en chef", "desc": "Fermer au moins une case sur chacun des 5 niveaux de maths."},
]

BADGE_NAMES = {b["id"]: b["name"] for b in BADGES}


def badge_name(badge_id: str) -> str:
    """Nom affichable d'un succès. Un identifiant inconnu (succès d'un jeu plus
    récent que cette copie du catalogue, chez un joueur pas encore mis à jour)
    est rendu lisible plutôt qu'ignoré."""
    if badge_id in BADGE_NAMES:
        return BADGE_NAMES[badge_id]
    return str(badge_id).replace("_", " ").capitalize()
