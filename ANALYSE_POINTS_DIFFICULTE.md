# Analyse — Points & niveaux de difficulté (DICTATION WAR)

Document de référence : comment les points sont comptés, et comment les 5 niveaux
de difficulté sont construits. Chaque section cite le code concerné.

---

## 1. Le score = les boucliers de la ville

Le « score » de la partie est une **jauge de bouclier** qui démarre à 20 points.

| Élément | Valeur | Où |
|---|---|---|
| Score initial | `self.score = 20` (100 %) | `main.py` `__init__` et reset dans `_generate_dictation_thread` |
| Affichage | `int((score / 20) * 100)` → « XX % » | `main.py:update_score_display` |
| Défaite | `score <= 0` → `handle_game_over` | `main.py:handle_game_over` |
| Victoire | `score > 0` à la fin des 3 phrases | `main.py:end_dictation` |

La jauge visuelle change de couleur selon le pourcentage :
- vert `accent2` si > 60 %
- orange `warning` si > 25 %
- rouge `danger` sinon

Chaque point perdu détruit visuellement **un immeuble** de la ville
(`lose_points` → `city_manager.destroy_building`).

---

## 2. Comment on perd des points

### 2.1. Les fautes (anomalies)

À la validation d'une phrase (`validate_sentence`), le texte tapé est comparé à la
phrase dictée via `display_errors` :

1. Les deux textes sont **tokenisés** en mots (lettres/chiffres Unicode, ponctuation
   ignorée) — `_tokenize_words`.
2. Comparaison par `difflib.SequenceMatcher` (insensible à la casse, `autojunk=False`).
3. Pour chaque opération **non égale**, `mistake_count += max(i2 - i1, j2 - j1)` :
   - `replace` → mot remplacé (anomalie + suggestion)
   - `delete` → mot oublié (« signal manquant »)
   - `insert` → mot en trop (« signal parasite »)
4. `mistake_count` fautes → `lose_points(mistake_count)` : **1 point = 1 faute**.

**Point de vigilance (pédagogie/équité)** : une phrase encore fausse est
**re-pénalisée à chaque revalidation** (`validate_sentence` → `display_errors(..., penalize=True)`).
Un élève qui bute plusieurs fois sur la même phrase perd plusieurs points pour la
même faute, ce qui peut être décourageant. Piste : ne pénaliser que la **première**
validation par phrase, ou plafonner la perte par phrase.

### 2.2. L'aide (diagnostic Gemini)

| Situation | Coût | Où |
|---|---|---|
| Il reste des jetons gratuits | 1 jeton (du pool d'arme) | `_on_help_ready` |
| Plus de jeton | **1 point de bouclier** | `_on_help_ready` → `lose_points(1)` |

Le coût n'est prélevé **que si l'appel Gemini réussit** (sinon 0 jeton, 0 point).

---

## 3. Fin de partie → crédits et XP

En fin de dictée (`end_dictation`), si `score > 0`, le barème **commun à tous
les jeux** (`commun/scoring.py::compute_rewards`, voir
PROPOSITION_SYSTEME_POINTS.md) est appelé avec le ratio de réussite :

```
ratio   = score / 20
crédits = round(ratio × 100 × LEVEL_MULTIPLIERS[niveau])
xp      = round(ratio × 200 × LEVEL_MULTIPLIERS[niveau] × poids_du_jeu)
```

Le même barème sert au jeu de maths (`problems.py::compute_rewards` ne fait
que convertir « cases fermées / 10 » en ratio) : une même performance au même
niveau rapporte donc exactement pareil des deux côtés.

`LEVEL_MULTIPLIERS` (`commun/scoring.py`) — appliqués aux crédits **et** à
l'XP :

| Niveau | Multiplicateur |
|---|---|
| CE1 | 1.0 |
| CE2 | 1.25 |
| CM1 | 1.5 |
| CM2 | 1.75 |
| Collège | 2.0 |

→ Plus le niveau est dur, plus un « sans faute » rapporte (max théorique :
20/20 → 100 crédits et 200 XP en CE1, 200 crédits et 400 XP au Collège).
L'XP n'était pas pondérée avant : répéter le niveau le plus facile était alors
le chemin le plus rapide vers le grade suivant.

### 3.1. À quoi servent les crédits (boutique)

`SHOP_ITEMS` (`main.py`) — chaque arme achetée donne des **aides gratuites** :

| Arme | Prix (crédits) | Aides offertes |
|---|---|---|
| Couteau laser | 120 | 1 |
| Pistolet plasma | 250 | 2 |
| Fusil ionique | 400 | 4 |
| Canon à particules | 650 | 7 |
| Sabre quantique | 900 | 10 |

Les aides (= jetons) servent à faire corriger une faute **sans perdre de bouclier**.
La boucle d'économie : **jouer → gagner des crédits → acheter des armes → plus
d'aides → meilleur score → plus de crédits**.

### 3.2. Le Panthéon (classement par jeu × niveau)

Le score final (`score`, 1..20) est envoyé au serveur (`HighScoreService.add_score`)
si `score > 0`. Le classement est trié par **score décroissant**, puis **durée
croissante** (à score égal, le plus rapide gagne), top 10 par niveau, avec
**une seule ligne par joueur** (sa meilleure tentative) — sinon celui qui
rejoue le plus occupe tout le classement.

### 3.3. Le Classement général (toutes missions confondues)

Ouvert depuis le Hub (bouton « Classement »), alimenté par
`GET /api/leaderboard` : les joueurs triés par **XP totale**, avec grade,
succès et récap par jeu. C'est la vue de comparaison entre joueurs ; le
Panthéon ci-dessus reste pour les records d'un niveau précis.

---

## 4. Les 5 niveaux de difficulté

Liste : `DIFFICULTY_LEVELS = ["CE1", "CE2", "CM1", "CM2", "Collège"]`
(`main.py`), défaut = **CM1**.

La difficulté est **réellement modulée** dans le prompt Gemini via
`_LEVEL_GUIDELINES` (`services.py`), injecté par `_build_dictation_prompt`.

| Niveau | Âge | Longueur de phrase | Temps verbaux | Pièges ciblés |
|---|---|---|---|---|
| **CE1** | 6-7 | 4 à 7 mots | présent indicatif seul | accord GN simple, accord sujet-verbe présent ; pas de subordonnées, pas d'homophones |
| **CE2** | 7-8 | 6 à 9 mots | présent + éventuel passé composé | accord dét-nom-adj simple, accord sujet-verbe, 1 homophone (a/à, et/est, son/sont) |
| **CM1** | 8-9 | 8 à 12 mots, ≤1 subordonnée simple | présent, imparfait, passé composé | accords GN + adjectifs, sujet inversé/éloigné, homophones a/à, et/est, on/ont, ce/se, son/sont |
| **CM2** | 9-10 | 10 à 15 mots, ≥1 relative/subordonnée | imparfait, passé composé, futur, présent | accord participe passé (être), GN complexes, homophones fins (leur/leurs, quel/quels/qu'elle, ces/ses, tout/tous) |
| **Collège** | 11-14 | 12 à 20 mots, subordonnées variées | passé simple, imparfait, passé composé, futur, subjonctif | accord participe passé avec avoir (COD avant), concordance des temps, homophones avancés (quoique/quoi que, davantage/d'avantage, leur/leurs), accords complexes |

### 4.1. Contraintes de forme (tous niveaux)

Imposées dans `_build_dictation_prompt` et validées par `_clean_dictation_response` :

- **Exactement 3 phrases** (`SENTENCE_COUNT = 3`), une par ligne.
- 3 à 45 mots par phrase (`MIN/MAX_WORDS_PER_SENTENCE`).
- 2 tentatives de génération max (`MAX_GENERATION_ATTEMPTS`), puis abandon.
- Pas de titre/intro/conclusion, pas de Markdown, nombres en toutes lettres,
  pas de sigles/parenthèses, thème « enfant » imposé (garde-fous de contenu),
  le mot « cœur » interdit (contrainte produit).

### 4.2. Le thème

Le joueur choisit un **thème libre** (`theme_var`) passé au prompt. Un thème
fantaisiste/inapproprié est édulcoré ou remplacé par un thème neutre.

### 4.3. Technique

- Modèle : `GEMINI_MODEL` (défaut `gemini-3.5-flash-lite`).
- Timeouts : dictée 25 s, explication 15 s.
- Échec distingué (clé invalide / quota / réseau / filtres) via `_describe_error`.

---

## 5. Synthèse des leviers de rejouabilité (existants)

- **Boucle crédits → armes → aides** : progression persistée (local + serveur).
- **Panthéon** : records par jeu et par niveau, une ligne par joueur.
- **Classement général** : comparaison entre joueurs toutes missions
  confondues (XP, grade, succès) — voir 3.3.
- **Grades** : 8 paliers sans plafond, l'XP monte plus vite dans les niveaux
  difficiles (voir PROPOSITION_SYSTEME_POINTS.md §7).
- **Succès (badges)** : partagés entre tous les jeux, visibles dans le
  classement (`commun/badges.py`).
- **Série quotidienne** : bonus de crédits, paliers 7 / 30 / 100 jours.
- **5 niveaux** : progression de difficulté réelle (CE1 → Collège).
- **Thèmes libres** : variété infinie de dictées.
