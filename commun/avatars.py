# commun/avatars.py
"""Catalogue des avatars, partagé par tous les jeux.

L'avatar fait partie de l'identité GLOBALE du joueur : le serveur le stocke sur
le joueur (`players.avatar_path`), la dictée en fait sa vidéo de démarrage, le
jeu de maths et le classement du Hub en affichent le portrait.

**Ajouter des avatars ne demande aucun changement de code** : déposer un couple
`X.mp4` + `X.jpg` (même nom de base) dans `commun/assets/avatars/` suffit — la
liste est découverte à chaque démarrage, dans l'ordre alphabétique. C'est ce qui
remplace les listes codées en dur qui existaient côté dictée.

Aucune dépendance Tk ici : ces fonctions sont testables sans fenêtre.

Note sur les chemins : la convention historique (serveur, profils de jeux)
stocke un chemin ABSOLU vers le `.mp4`, donc invalide d'un PC à l'autre. C'est
la raison d'être de `resolve_avatar`, qui retombe sur le nom de fichier.
"""

import os

# Un avatar = une vidéo .mp4 (dictée) + une miniature .jpg de même nom de base
# (Hub, maths, classement).
AVATAR_EXT = ".mp4"
THUMB_EXT = ".jpg"


def avatars_dir(commun_dir: str) -> str:
    return os.path.join(commun_dir, "assets", "avatars")


def list_avatars(commun_dir: str) -> list:
    """Avatars disponibles (chemins absolus vers le .mp4), triés par nom.

    Un .mp4 sans miniature est ignoré : il s'afficherait comme une case vide
    dans le sélecteur et comme un portrait manquant dans le classement.

    Sans `commun_dir`, retourne une liste vide plutôt que de résoudre un chemin
    relatif : sinon le résultat dépendrait du répertoire courant du processus,
    donc de la façon dont le jeu a été lancé."""
    if not commun_dir:
        return []
    directory = avatars_dir(commun_dir)
    if not os.path.isdir(directory):
        return []
    found = []
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(AVATAR_EXT):
            continue
        path = os.path.join(directory, name)
        if os.path.exists(thumbnail_path(path)):
            found.append(path)
    return found


def thumbnail_path(avatar_path: str) -> str:
    """Miniature .jpg d'un avatar (même nom de base que la vidéo)."""
    return os.path.splitext(avatar_path)[0] + THUMB_EXT


def avatar_label(avatar_path: str) -> str:
    """Libellé lisible : « Avatar 1a » plutôt que « 1a.mp4 »."""
    base = os.path.splitext(os.path.basename(avatar_path))[0]
    return f"Avatar {base}"


def resolve_avatar(avatar_path: str, options: list) -> str | None:
    """Ramène un chemin d'avatar (venant du serveur ou d'un profil local) vers
    l'option correspondante SUR CE PC.

    Trois cas, dans l'ordre : chemin exact connu ; même nom de fichier à un
    autre emplacement (avatar choisi sur un autre PC, ou dossier d'installation
    différent) ; sinon None, à l'appelant de choisir un repli."""
    if not avatar_path or not options:
        return None
    if avatar_path in options:
        return avatar_path
    wanted = os.path.basename(avatar_path).lower()
    for option in options:
        if os.path.basename(option).lower() == wanted:
            return option
    return None


def default_avatar(options: list) -> str | None:
    """Avatar de repli quand le joueur n'en a pas encore choisi."""
    return options[0] if options else None
