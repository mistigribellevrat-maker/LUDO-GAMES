# conjugation_data.py
"""Table de conjugaison — pure donnée, aucune logique.

Table curée à la main plutôt que générée algorithmiquement : le français a
trop d'exceptions (verbes irréguliers) pour qu'un générateur de règles reste
fiable à 100 %, et une conjugaison fausse ici serait un vrai bug pédagogique
(on apprendrait une mauvaise forme à un enfant). Chaque forme ci-dessous est
la phrase complète (pronom + verbe, avec les élisions correctes : "j'ai",
"qu'il", etc.) plutôt qu'un simple radical+terminaison à recomposer — plus
sûr, aucune règle de composition à maintenir.

13 verbes : 3 réguliers des trois groupes (manger/-er, finir/-ir, vendre/-re)
+ 10 irréguliers très fréquents. 6 temps × 6 pronoms = 36 formes par verbe,
468 au total.

Les mauvaises réponses du jeu piochent TOUJOURS dans cette table (une autre
forme du même verbe, à un autre temps) — jamais une chaîne inventée.
"""

# Index des pronoms : je, tu, il/elle, nous, vous, ils/elles.
PRONOUN_LABELS = ["je", "tu", "il / elle", "nous", "vous", "ils / elles"]

# Ordre d'affichage et libellés des temps.
TENSES = ["present", "imparfait", "futur", "passe_compose", "conditionnel", "subjonctif"]
TENSE_LABELS = {
    "present": "présent",
    "imparfait": "imparfait",
    "futur": "futur simple",
    "passe_compose": "passé composé",
    "conditionnel": "conditionnel présent",
    "subjonctif": "subjonctif présent",
}

REGULAR_VERBS = ["manger", "finir", "vendre"]
IRREGULAR_VERBS = ["être", "avoir", "aller", "faire", "dire", "pouvoir",
                    "vouloir", "venir", "prendre", "voir"]
ALL_VERBS = REGULAR_VERBS + IRREGULAR_VERBS

# VERBS[verbe][temps] = [je, tu, il, nous, vous, ils] (6 formes complètes).
VERBS: dict[str, dict[str, list[str]]] = {
    "manger": {
        "present": ["je mange", "tu manges", "il mange", "nous mangeons", "vous mangez", "ils mangent"],
        "imparfait": ["je mangeais", "tu mangeais", "il mangeait", "nous mangions", "vous mangiez", "ils mangeaient"],
        "futur": ["je mangerai", "tu mangeras", "il mangera", "nous mangerons", "vous mangerez", "ils mangeront"],
        "passe_compose": ["j'ai mangé", "tu as mangé", "il a mangé", "nous avons mangé", "vous avez mangé", "ils ont mangé"],
        "conditionnel": ["je mangerais", "tu mangerais", "il mangerait", "nous mangerions", "vous mangeriez", "ils mangeraient"],
        "subjonctif": ["que je mange", "que tu manges", "qu'il mange", "que nous mangions", "que vous mangiez", "qu'ils mangent"],
    },
    "finir": {
        "present": ["je finis", "tu finis", "il finit", "nous finissons", "vous finissez", "ils finissent"],
        "imparfait": ["je finissais", "tu finissais", "il finissait", "nous finissions", "vous finissiez", "ils finissaient"],
        "futur": ["je finirai", "tu finiras", "il finira", "nous finirons", "vous finirez", "ils finiront"],
        "passe_compose": ["j'ai fini", "tu as fini", "il a fini", "nous avons fini", "vous avez fini", "ils ont fini"],
        "conditionnel": ["je finirais", "tu finirais", "il finirait", "nous finirions", "vous finiriez", "ils finiraient"],
        "subjonctif": ["que je finisse", "que tu finisses", "qu'il finisse", "que nous finissions", "que vous finissiez", "qu'ils finissent"],
    },
    "vendre": {
        "present": ["je vends", "tu vends", "il vend", "nous vendons", "vous vendez", "ils vendent"],
        "imparfait": ["je vendais", "tu vendais", "il vendait", "nous vendions", "vous vendiez", "ils vendaient"],
        "futur": ["je vendrai", "tu vendras", "il vendra", "nous vendrons", "vous vendrez", "ils vendront"],
        "passe_compose": ["j'ai vendu", "tu as vendu", "il a vendu", "nous avons vendu", "vous avez vendu", "ils ont vendu"],
        "conditionnel": ["je vendrais", "tu vendrais", "il vendrait", "nous vendrions", "vous vendriez", "ils vendraient"],
        "subjonctif": ["que je vende", "que tu vendes", "qu'il vende", "que nous vendions", "que vous vendiez", "qu'ils vendent"],
    },
    "être": {
        "present": ["je suis", "tu es", "il est", "nous sommes", "vous êtes", "ils sont"],
        "imparfait": ["j'étais", "tu étais", "il était", "nous étions", "vous étiez", "ils étaient"],
        "futur": ["je serai", "tu seras", "il sera", "nous serons", "vous serez", "ils seront"],
        "passe_compose": ["j'ai été", "tu as été", "il a été", "nous avons été", "vous avez été", "ils ont été"],
        "conditionnel": ["je serais", "tu serais", "il serait", "nous serions", "vous seriez", "ils seraient"],
        "subjonctif": ["que je sois", "que tu sois", "qu'il soit", "que nous soyons", "que vous soyez", "qu'ils soient"],
    },
    "avoir": {
        "present": ["j'ai", "tu as", "il a", "nous avons", "vous avez", "ils ont"],
        "imparfait": ["j'avais", "tu avais", "il avait", "nous avions", "vous aviez", "ils avaient"],
        "futur": ["j'aurai", "tu auras", "il aura", "nous aurons", "vous aurez", "ils auront"],
        "passe_compose": ["j'ai eu", "tu as eu", "il a eu", "nous avons eu", "vous avez eu", "ils ont eu"],
        "conditionnel": ["j'aurais", "tu aurais", "il aurait", "nous aurions", "vous auriez", "ils auraient"],
        "subjonctif": ["que j'aie", "que tu aies", "qu'il ait", "que nous ayons", "que vous ayez", "qu'ils aient"],
    },
    "aller": {
        "present": ["je vais", "tu vas", "il va", "nous allons", "vous allez", "ils vont"],
        "imparfait": ["j'allais", "tu allais", "il allait", "nous allions", "vous alliez", "ils allaient"],
        "futur": ["j'irai", "tu iras", "il ira", "nous irons", "vous irez", "ils iront"],
        "passe_compose": ["je suis allé", "tu es allé", "il est allé", "nous sommes allés", "vous êtes allés", "ils sont allés"],
        "conditionnel": ["j'irais", "tu irais", "il irait", "nous irions", "vous iriez", "ils iraient"],
        "subjonctif": ["que j'aille", "que tu ailles", "qu'il aille", "que nous allions", "que vous alliez", "qu'ils aillent"],
    },
    "faire": {
        "present": ["je fais", "tu fais", "il fait", "nous faisons", "vous faites", "ils font"],
        "imparfait": ["je faisais", "tu faisais", "il faisait", "nous faisions", "vous faisiez", "ils faisaient"],
        "futur": ["je ferai", "tu feras", "il fera", "nous ferons", "vous ferez", "ils feront"],
        "passe_compose": ["j'ai fait", "tu as fait", "il a fait", "nous avons fait", "vous avez fait", "ils ont fait"],
        "conditionnel": ["je ferais", "tu ferais", "il ferait", "nous ferions", "vous feriez", "ils feraient"],
        "subjonctif": ["que je fasse", "que tu fasses", "qu'il fasse", "que nous fassions", "que vous fassiez", "qu'ils fassent"],
    },
    "dire": {
        "present": ["je dis", "tu dis", "il dit", "nous disons", "vous dites", "ils disent"],
        "imparfait": ["je disais", "tu disais", "il disait", "nous disions", "vous disiez", "ils disaient"],
        "futur": ["je dirai", "tu diras", "il dira", "nous dirons", "vous direz", "ils diront"],
        "passe_compose": ["j'ai dit", "tu as dit", "il a dit", "nous avons dit", "vous avez dit", "ils ont dit"],
        "conditionnel": ["je dirais", "tu dirais", "il dirait", "nous dirions", "vous diriez", "ils diraient"],
        "subjonctif": ["que je dise", "que tu dises", "qu'il dise", "que nous disions", "que vous disiez", "qu'ils disent"],
    },
    "pouvoir": {
        "present": ["je peux", "tu peux", "il peut", "nous pouvons", "vous pouvez", "ils peuvent"],
        "imparfait": ["je pouvais", "tu pouvais", "il pouvait", "nous pouvions", "vous pouviez", "ils pouvaient"],
        "futur": ["je pourrai", "tu pourras", "il pourra", "nous pourrons", "vous pourrez", "ils pourront"],
        "passe_compose": ["j'ai pu", "tu as pu", "il a pu", "nous avons pu", "vous avez pu", "ils ont pu"],
        "conditionnel": ["je pourrais", "tu pourrais", "il pourrait", "nous pourrions", "vous pourriez", "ils pourraient"],
        "subjonctif": ["que je puisse", "que tu puisses", "qu'il puisse", "que nous puissions", "que vous puissiez", "qu'ils puissent"],
    },
    "vouloir": {
        "present": ["je veux", "tu veux", "il veut", "nous voulons", "vous voulez", "ils veulent"],
        "imparfait": ["je voulais", "tu voulais", "il voulait", "nous voulions", "vous vouliez", "ils voulaient"],
        "futur": ["je voudrai", "tu voudras", "il voudra", "nous voudrons", "vous voudrez", "ils voudront"],
        "passe_compose": ["j'ai voulu", "tu as voulu", "il a voulu", "nous avons voulu", "vous avez voulu", "ils ont voulu"],
        "conditionnel": ["je voudrais", "tu voudrais", "il voudrait", "nous voudrions", "vous voudriez", "ils voudraient"],
        "subjonctif": ["que je veuille", "que tu veuilles", "qu'il veuille", "que nous voulions", "que vous vouliez", "qu'ils veuillent"],
    },
    "venir": {
        "present": ["je viens", "tu viens", "il vient", "nous venons", "vous venez", "ils viennent"],
        "imparfait": ["je venais", "tu venais", "il venait", "nous venions", "vous veniez", "ils venaient"],
        "futur": ["je viendrai", "tu viendras", "il viendra", "nous viendrons", "vous viendrez", "ils viendront"],
        "passe_compose": ["je suis venu", "tu es venu", "il est venu", "nous sommes venus", "vous êtes venus", "ils sont venus"],
        "conditionnel": ["je viendrais", "tu viendrais", "il viendrait", "nous viendrions", "vous viendriez", "ils viendraient"],
        "subjonctif": ["que je vienne", "que tu viennes", "qu'il vienne", "que nous venions", "que vous veniez", "qu'ils viennent"],
    },
    "prendre": {
        "present": ["je prends", "tu prends", "il prend", "nous prenons", "vous prenez", "ils prennent"],
        "imparfait": ["je prenais", "tu prenais", "il prenait", "nous prenions", "vous preniez", "ils prenaient"],
        "futur": ["je prendrai", "tu prendras", "il prendra", "nous prendrons", "vous prendrez", "ils prendront"],
        "passe_compose": ["j'ai pris", "tu as pris", "il a pris", "nous avons pris", "vous avez pris", "ils ont pris"],
        "conditionnel": ["je prendrais", "tu prendrais", "il prendrait", "nous prendrions", "vous prendriez", "ils prendraient"],
        "subjonctif": ["que je prenne", "que tu prennes", "qu'il prenne", "que nous prenions", "que vous preniez", "qu'ils prennent"],
    },
    "voir": {
        "present": ["je vois", "tu vois", "il voit", "nous voyons", "vous voyez", "ils voient"],
        "imparfait": ["je voyais", "tu voyais", "il voyait", "nous voyions", "vous voyiez", "ils voyaient"],
        "futur": ["je verrai", "tu verras", "il verra", "nous verrons", "vous verrez", "ils verront"],
        "passe_compose": ["j'ai vu", "tu as vu", "il a vu", "nous avons vu", "vous avez vu", "ils ont vu"],
        "conditionnel": ["je verrais", "tu verrais", "il verrait", "nous verrions", "vous verriez", "ils verraient"],
        "subjonctif": ["que je voie", "que tu voies", "qu'il voie", "que nous voyions", "que vous voyiez", "qu'ils voient"],
    },
}

# --- Barème par niveau : temps ciblés + réservoir de verbes ---------------
TENSE_BY_LEVEL: dict[str, list[str]] = {
    "CE1": ["present"],
    "CE2": ["present"],
    "CM1": ["imparfait"],
    "CM2": ["futur", "passe_compose"],
    "Collège": ["conditionnel", "subjonctif"],
}

VERB_POOL_BY_LEVEL: dict[str, list[str]] = {
    "CE1": REGULAR_VERBS,
    "CE2": ALL_VERBS,
    "CM1": ALL_VERBS,
    "CM2": ALL_VERBS,
    "Collège": ALL_VERBS,
}
