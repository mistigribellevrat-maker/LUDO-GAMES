# Système de points comparable entre joueurs

> **Statut : implémenté le 17 août 2026** (étapes 1 à 5 de §5). Ce document
> reste la référence sur le *pourquoi* ; l'état de mise en œuvre et les
> décisions prises sont consignés en §5 et §7. Reste optionnel : §3.5
> (compteur mensuel), à ne construire que si le besoin se confirme.
>
> **Décisions prises** (les points ouverts de §7 sont tranchés) :
> - la stat de comparaison **garde le nom « XP »** — mot déjà connu des enfants,
>   déjà affiché partout, et surtout **aucune migration serveur** (la colonne
>   `players.xp` est conservée telle quelle). C'est son *calcul* qui change,
>   pas son nom ;
> - `game_weight` = 1.0 pour la dictée et les maths (missions de durée
>   comparable), ajustable par jeu sans toucher aux crédits ;
> - grades étendus à 8 paliers, seuils recalibrés (voir §7).

Contexte : 4 joueurs inscrits (Arthur, Oscar, Cloclo, Greg) sur un serveur commun,
2 jeux actifs (Dictée, Grille de Protection) et d'autres à venir (histoire-géo
citée dans `commun/server_client.py`, potentiellement d'autres). Les joueurs
vont vouloir se comparer — le système actuel n'a pas été pensé pour ça. Ce
document analyse pourquoi, et propose une refonte qui tient sur tous les jeux
présents et futurs.

Aucun code n'a été modifié : ceci est une proposition à valider avant
implémentation.

---

## 1. Ce qui existe aujourd'hui

Trois mécaniques de progression, toutes **globales** (partagées entre jeux,
table `players` du serveur) :

| Mécanique | Sert à | Calcul (Dictée) | Calcul (Maths) |
|---|---|---|---|
| **Crédits** | Monnaie dépensable (boutique d'armes/aides) | `round(shield_% × multiplicateur_niveau)` | `round(%_grille × multiplicateur_niveau)` |
| **XP → Grade** | Titre affiché (Recrue → Grand Stratège) | `score/20 × 10` | `round(score/segments × 20) × 10` |
| **Badges** | Succès débloqués, listés dans un panneau perso | déclenchés par seuils (score, temps, série...) | idem |

Plus un classement **par jeu et par niveau de difficulté** ("Panthéon des
Héros" / `GET /api/scores/<jeu>/<difficulté>`), et une série quotidienne
(`streak`) qui donne un bonus de crédits.

### Ce qui marche déjà bien (à garder)
- La progression est **globale entre jeux** — un crédit gagné en maths est
  visible en dictée. Bonne base, à conserver pour tout ce qui suit.
- Le serveur est déjà la seule source de vérité (pas de triche côté client),
  et scope tout par `game` — l'architecture supporte déjà d'ajouter des jeux
  sans tout casser.
- Les crédits pondèrent déjà par difficulté (`LEVEL_MULTIPLIERS`) — un
  sans-faute Collège rapporte 2× plus qu'un CE1. Ce principe est bon, il
  manque juste à un autre endroit (voir 2.2).

---

## 2. Pourquoi ça ne marche pas pour se comparer

### 2.1. Les crédits ne sont pas un score — c'est de l'argent de poche

Les crédits **se dépensent** (boutique). Le solde affiché reflète autant
« combien j'ai économisé » que « combien j'ai gagné ». Deux joueurs au même
niveau réel peuvent afficher des soldes très différents selon qu'ils ont
acheté des armes ou pas. **Inutilisable tel quel comme classement.**

### 2.2. L'XP ne récompense pas la difficulté

`XP_PER_POINT` s'applique au score brut (0-20), **sans multiplicateur de
niveau** — contrairement aux crédits. Un sans-faute en CE1 donne exactement
autant d'XP qu'un sans-faute au Collège. Un joueur qui veut monter en grade
a donc intérêt à répéter le niveau le plus facile, jamais à se challenger.
C'est l'inverse de l'effet recherché.

### 2.3. Le grade plafonne à 1000 XP

5 paliers, le dernier (« Grand Stratège ») à 1000 XP. Avec des parties à
~100-200 XP chacune, ce plafond est atteint en quelques jours de jeu régulier.
Une fois les 4 joueurs au grade max, **plus aucune différenciation possible**
— alors que c'est exactement le moment où ils commencent à vouloir se
comparer sérieusement.

### 2.4. Le classement peut être monopolisé par un seul joueur

`add_score` enregistre **chaque tentative**, sans limite. Le top 10 est trié
par score puis durée, sans dédoublonner par joueur
(`server.py::ScoreStore.top`). Un joueur qui rejoue 15 fois le même niveau
peut occuper la moitié du top 10 avec ses propres tentatives, écrasant les
scores des autres. Pour 4 joueurs qui veulent se comparer, c'est le bug le
plus visible et le plus frustrant.

### 2.5. Le classement est fragmenté, pas de vue d'ensemble

Le Panthéon existe **par jeu × par niveau** (2 jeux × 5 niveaux = 10
classements séparés aujourd'hui, et ça grandit à chaque niveau/jeu ajouté).
Il n'existe **aucun endroit** où un joueur voit « qui est le meilleur, toutes
missions confondues ». C'est pourtant la question que 4 frères et sœurs vont
se poser en premier.

### 2.6. Deux formules de récompense qui divergent déjà

`client-dictee/main.py` calcule les crédits/XP en ligne dans `end_dictation`.
`client-maths/problems.py::compute_rewards` réimplémente la même idée
séparément. Elles se ressemblent aujourd'hui par discipline du développeur,
mais rien n'empêche qu'elles divergent au prochain jeu — et donc que
« 20/20 » ne veuille plus dire la même chose d'un jeu à l'autre.

---

## 3. Proposition

Trois idées, qui peuvent se déployer indépendamment (voir §5 pour l'ordre
recommandé).

### 3.1. Séparer « ce qu'on dépense » de « ce qui prouve le niveau »

Garder les **Crédits** tels quels, purement pour la boutique, et faire de
l'**XP** la seule stat de comparaison : globale, non dépensable, qui ne fait
que croître. (Retenu plutôt qu'une nouvelle stat « Renommée » : même rôle,
mais sans renommer une colonne serveur ni un mot que les enfants connaissent
déjà — voir §7.)

- Gagnée aux mêmes moments qu'avant (fin de mission réussie).
- **Pondérée par la difficulté**, comme les crédits :
  `xp_gagnée = ratio_de_réussite × 200 × multiplicateur_niveau × poids_du_jeu`
  (le `poids_du_jeu` — 1.0 pour Dictée comme pour Maths — permet de
  calibrer un futur jeu plus long/court sans déséquilibrer les autres).
- **Jamais plafonnée.** Les grades (Recrue → Légende Galactique) deviennent
  des paliers cosmétiques le long d'une échelle qui continue de grandir : même
  au dernier titre, l'XP départage encore deux joueurs dans le classement
  global, et d'autres paliers peuvent être ajoutés plus tard.

### 3.2. Un contrat de calcul commun à tous les jeux

Créer `commun/scoring.py`, utilisé par **tous** les jeux (présents et
futurs) :

```python
def compute_rewards(level: str, ratio: float, level_multipliers: dict,
                     game_weight: float = 1.0) -> tuple[int, int]:
    """ratio = score/max_score du jeu, entre 0 et 1.
    Retourne (credits_gagnés, renommée_gagnée)."""
    if ratio <= 0:
        return 0, 0
    mult = level_multipliers.get(level, 1.0)
    credits = round(ratio * 100 * mult)
    renommee = round(ratio * 100 * mult * game_weight)
    return credits, renommee
```

Chaque jeu fournit juste son `ratio` (score/20 pour la dictée,
score/segments pour la grille) et ses propres `LEVEL_MULTIPLIERS`. Ça
garantit que « 100 % de réussite en Collège » vaut la même chose partout,
aujourd'hui et pour le prochain jeu — sans copier-coller la formule.

### 3.3. Des classements qui donnent vraiment envie de se comparer

**a) Corriger le Panthéon existant** — dédoublonner par joueur (`SELECT`
avec `GROUP BY player_id` gardant la meilleure ligne) avant de prendre le
top 10. Petit changement côté `ScoreStore.top()`, gros gain d'équité :
chaque joueur n'occupe plus qu'une ligne.

**b) Ajouter un classement global** — nouvel endpoint
`GET /api/leaderboard` : les 4 joueurs (ou plus), triés par Renommée totale,
avec pour chacun le grade, le nombre de badges, et un mini récap par jeu
(ex. « 2 badges Dictée, 1 badge Maths »). C'est la vue « qui est le
meilleur commandant, toutes missions confondues » qui manque aujourd'hui.
Affichage naturel : un nouvel onglet dans le Hub (déjà en place, voir la
carte de profil ajoutée récemment) — un bouton « Classement » à côté de
« Changer de commandant ».

**c) Garder les classements par jeu/niveau** (bragging rights spécifiques —
« le meilleur en calcul mental CM2 ») en plus du classement global, pas à sa
place.

### 3.4. Rendre les badges comparables

Les badges existent déjà et sont partagés globalement (`players.badges`).
Il suffit de les **afficher dans le classement** (nombre de badges, ou liste
au survol) — aucun calcul nouveau, juste de la visibilité. Simple et déjà
prêt côté données.

### 3.5. (Optionnel, phase ultérieure) Un compteur qui repart régulièrement

Avec seulement 4 joueurs dont un qui a commencé avant les autres (Greg,
déjà à 0 crédit/XP pour l'instant donc pas encore un souci, mais à anticiper
si un des enfants commence plus tard), la Renommée à vie avantage toujours
le premier arrivé. Piste pour plus tard, pas urgente : un compteur
« Renommée du mois » qui se remet à zéro chaque mois (table séparée,
horodatée), affiché à côté de la Renommée à vie. Donne un classement
« frais » régulièrement, sans jamais toucher à la progression permanente.
À ne construire que si le besoin se confirme à l'usage — complexité serveur
non négligeable (job de reset, nouvelle table) pour un gain incertain avec
seulement 4 joueurs.

---

## 4. Migration des données existantes

**Aucune migration nécessaire, et rien à convertir.** Le nom « XP » et la
colonne `players.xp` sont conservés ; seul le calcul change. Au moment du
changement, les 4 joueurs (`player_id` 1 à 4) étaient tous à 0 crédit / 0 XP
et la table `scores` était vide — c'était donc aussi le bon moment pour
recalibrer les seuils de grade (§7), ce qui aurait sinon dévalué une
progression déjà acquise.

---

## 5. État de mise en œuvre

1. ✅ **`commun/scoring.py`** — barème commun (crédits + XP + grades). Dictée
   (`main.py`) et Maths (`problems.py::compute_rewards`) l'utilisent ; plus
   aucune formule dupliquée. Les crédits gagnés sont **inchangés** à tous les
   niveaux (vérifié score par score) : seul l'XP change.
2. ✅ **XP pondérée et déplafonnée** — le multiplicateur de niveau s'applique
   désormais à l'XP comme aux crédits (un sans-faute Collège = 400 XP contre
   200 en CE1 ; avant, 200 dans les deux cas). Grades portés à 8 paliers.
   Aucune migration : la colonne `players.xp` est conservée (voir statut).
3. ✅ **Panthéon dédoublonné** — `ScoreStore.top()` ne garde que la meilleure
   ligne de chaque joueur. `rank`/`total` comptent désormais des joueurs, pas
   des tentatives, pour que le rang annoncé corresponde à la ligne affichée.
4. ✅ **Classement global** — `GET /api/leaderboard` côté serveur,
   `HighScoreService.get_leaderboard()` côté client, écran
   `client-hub/leaderboard.py` ouvert par le bouton « Classement » du Hub.
5. ✅ **Badges visibles dans le classement** — et catalogue sorti dans
   `commun/badges.py` (il vivait dans `client-dictee/main.py`, le Hub n'y avait
   pas accès et affichait les identifiants bruts : « Sans faute cm1 »).
6. ⬜ *(Plus tard, si le besoin se confirme)* XP mensuelle (§3.5).

**Fichiers touchés** : `commun/scoring.py` (nouveau), `commun/badges.py`
(nouveau), `commun/server_client.py`, `serveur/server.py`,
`client-hub/leaderboard.py` (nouveau), `client-hub/main.py`,
`client-dictee/main.py`, `client-maths/main.py`, `client-maths/problems.py`,
plus les suites de tests et les deux `manifest.json` (les nouveaux modules
partagés sont distribués aux joueurs).

---

## 6. Contrat pour tout futur jeu (histoire-géo, etc.)

Pour qu'un nouveau jeu s'intègre proprement dans la comparaison entre
joueurs dès son premier lancement :

- Utiliser `commun/scoring.py::compute_rewards` — jamais réimplémenter la
  formule localement.
- Définir un `ratio` de réussite entre 0 et 1 (quelle que soit l'échelle
  interne du jeu) et ses propres `LEVEL_MULTIPLIERS` par niveau de
  difficulté.
- Envoyer `game` distinct au serveur (déjà la convention actuelle) pour que
  ses classements par niveau restent séparés, tout en contribuant à la
  Renommée globale et au classement toutes missions confondues.
- Réutiliser les grades partagés (`commun/scoring.py::GRADES`, `grade_info`)
  plutôt que redéfinir sa propre liste de titres.
- Déclarer ses succès dans `commun/badges.py` (identifiants préfixés par le
  nom du jeu) plutôt que dans une liste locale : c'est ce catalogue que lisent
  le Panthéon des succès de la dictée et le classement du Hub.

---

## 7. Points tranchés

- **Nom affiché** : « XP » conservé (plutôt que « Renommée »). Mot déjà
  connu des enfants, déjà affiché dans le Hub et les deux jeux, et migration
  serveur nulle. Le nom ne change pas, le calcul si.
- **Poids par jeu** (`game_weight`) : 1.0 pour la Dictée et les Maths — deux
  missions de durée comparable. Le paramètre existe dans
  `commun/scoring.py::compute_rewards` pour caler un futur jeu plus long sans
  toucher aux crédits (économie de boutique commune).
- **Grades** : 8 paliers. Les seuils de départ proposés (Amiral 2000, etc.)
  ont été revus à la hausse, parce que l'XP est maintenant pondérée par la
  difficulté : une mission rapporte 200 à 400 XP, donc 2000 XP se serait
  atteint en une poignée de parties.

  | Grade | XP | ~missions Collège parfaites |
  |---|---|---|
  | Recrue | 0 | — |
  | Soldat | 500 | 1 |
  | Caporal | 1 500 | 4 |
  | Vétéran | 3 500 | 9 |
  | Grand Stratège | 7 000 | 18 |
  | Amiral | 14 000 | 35 |
  | Maître de Guerre | 28 000 | 70 |
  | Légende Galactique | 56 000 | 140 |

  L'écart double à chaque palier : les premiers grades tombent vite (accroche),
  le sommet reste un horizon lointain. Recalibrage sans coût : les 4 joueurs
  étaient à 0 XP et la table `scores` était vide au moment du changement.
