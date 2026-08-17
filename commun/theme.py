# theme.py
#
# Système de design central de DICTATION WAR.
# Toutes les couleurs, polices et métriques de l'interface vivent ici, afin que
# l'habillage reste cohérent et réglable en un seul endroit (au lieu d'éparpiller
# des hexadécimaux dans main.py / ui_components.py).
#
# Palette construite sur une base « espace profond » teintée de bleu (hue unique,
# chroma basse pour les surfaces, chroma haute pour les accents néon). Les rapports
# de contraste texte/fond sont vérifiés : >= 7:1 pour le texte courant, >= 5:1 pour
# les accents, conformément aux critères de lisibilité (WCAG) — crucial pour un
# public enfant.

from __future__ import annotations

from typing import Tuple


# ---------------------------------------------------------------------------
# PALETTE
# ---------------------------------------------------------------------------
# Rôles :
#   bg_*        -> fonds (la toile la plus profonde)
#   panel_*     -> surfaces surélevées / en creux (architecture « double-bezel »)
#   border_*    -> filets de structure (jamais de gris neutre : toujours teintés bleu)
#   accent*     -> couleur primaire (cyan néon), *2 = secondaire (émeraude, succès)
#   danger      -> échec / destruction
#   warning     -> alerte / attente
#   text_*      -> échelle typographique (dégradé bleu-blanc)

PALETTE: dict[str, str] = {
    # Fonds
    "bg":        "#070b12",   # toile principale (presque noir, sous-ton indigo)
    "bg_alt":    "#0a0f1a",   # fond légèrement relevé (rayures, alternance)
    "bg_deep":   "#04060b",   # le plus profond (halo derrière les cartes)

    # Surfaces (double-bezel : coque externe / cœur interne)
    "panel":     "#0e1626",   # coque externe des cartes / barre de commandement
    "panel2":    "#0b1220",   # cœur interne (champs, consoles, inserts)
    "panel3":    "#13203a",   # surface survolée / active

    # Filets de structure (teintés, jamais gris)
    "border":    "#1d2c49",   # hairline standard
    "border_hi": "#2b4068",   # hairline renforcé (focus, contours actifs)

    # Accents néon
    "accent":      "#00d9ff",   # primaire cyan
    "accent_hi":   "#66ecff",   # cyan éclairci (survol)
    "accent_dim":  "#0093b3",   # cyan assombri (pressé)
    "accent2":     "#00ffa3",   # secondaire émeraude (succès, bouclier)
    "accent2_dim": "#00c37e",
    "accent_glow": "#0a2c3a",   # halo diffus derrière l'accent primaire

    # Sémantique
    "danger":      "#ff3b5e",   # échec / destruction / anomalie
    "danger_hi":   "#ff6f88",
    "warning":     "#ffb454",   # alerte / attente
    "warning_dim": "#b57a2e",

    # Échelle typographique
    "text":        "#d8e9ff",   # texte principal (contraste ~16:1)
    "text_strong": "#f4f9ff",   # texte renforcé (titres, valeurs)
    "muted":       "#86a3c8",   # texte secondaire (contraste ~7.6:1)
    "faint":       "#4f6287",   # texte décoratif uniquement
}


# ---------------------------------------------------------------------------
# TYPOGRAPHIE
# ---------------------------------------------------------------------------
# Bahnschrift (DIN 1451) -> affichage HUD / titres, géométrique et aérospatial.
# Segoe UI               -> corps de texte, lisibilité optimale pour les enfants.
# Cascadia Mono          -> console de décodage (terminal), chasse fixe moderne.
# Ces polices sont présentes sur Windows : fini le repli silencieux d'« Orbitron »
# (absent du poste) qui cassait la cohérence typographique.

FONT_DISPLAY = "Bahnschrift"
FONT_BODY    = "Segoe UI"
FONT_MONO    = "Cascadia Mono"

# Échelle typographique (tailles en points, hiérarchie stricte).
FONT_SIZES: dict[str, int] = {
    "hero":    34,   # valeur de bouclier
    "h1":      20,   # titres de section
    "h2":      16,   # sous-titres
    "h3":      13,   # libellés de panneaux
    "body":    12,   # texte courant
    "small":   11,   # texte secondaire
    "micro":   10,   # badges / eyebrow
    "console": 13,   # console de décodage
}

# Espacement de lettrage (px) pour les libellés majuscules type « HUD ».
LETTER_SPACING = 2


# ---------------------------------------------------------------------------
# GÉOMÉTRIE & SURFACES
# ---------------------------------------------------------------------------
RADIUS_LG = 16    # rayon des cartes principales (coque externe)
RADIUS_MD = 10    # rayon des éléments internes (cœur, champs)
RADIUS_SM = 6     # rayon des petits éléments (segments, badges)

BEZEL_INSET = 3   # écart coque externe -> cœur interne (architecture « double-bezel »)

SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 14,
    "lg": 22,
    "xl": 34,
}


# ---------------------------------------------------------------------------
# UTILITAIRES COULEUR
# ---------------------------------------------------------------------------

def hex_to_rgb(color: str) -> Tuple[int, int, int]:
    """Convertit '#rrggbb' en tuple (r, g, b) d'entiers 0..255."""
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    """Convertit un tuple (r, g, b) 0..255 en '#rrggbb'."""
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def mix(c1: str, c2: str, t: float) -> str:
    """Mélange linéaire de deux couleurs hexadécimales (t=0 -> c1, t=1 -> c2)."""
    a = hex_to_rgb(c1)
    b = hex_to_rgb(c2)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))  # type: ignore[arg-type]


def lighten(color: str, t: float) -> str:
    """Éclaircit une couleur en la mélangeant vers le blanc."""
    return mix(color, "#ffffff", t)


def darken(color: str, t: float) -> str:
    """Assombrit une couleur en la mélangeant vers le noir."""
    return mix(color, "#000000", t)


def alpha_over(fg: str, bg: str, a: float) -> str:
    """Composite une couleur `fg` semi-transparente (alpha `a`) sur un fond `bg`.

    Utilisé pour les remplissages « verre » des boutons (accent à ~15 % d'opacité
    par-dessus un panneau) sans dépendre de la transparence native de Tk.
    """
    f, b = hex_to_rgb(fg), hex_to_rgb(bg)
    return rgb_to_hex(tuple(f[i] * a + b[i] * (1 - a) for i in range(3)))  # type: ignore[arg-type]


def relative_luminance(color: str) -> float:
    """Luminance relative WCAG (0..1) d'une couleur hexadécimale."""
    r, g, b = (v / 255 for v in hex_to_rgb(color))

    def _lin(ch: float) -> float:
        return ch / 12.92 if ch <= 0.03928 else ((ch + 0.055) / 1.055) ** 2.4

    r, g, b = _lin(r), _lin(g), _lin(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(c1: str, c2: str) -> float:
    """Rapport de contraste WCAG entre deux couleurs (1.0 à 21.0)."""
    l1, l2 = relative_luminance(c1), relative_luminance(c2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def interpolate(c1: str, c2: str, steps: int):
    """Générateur des `steps` couleurs intermédiaires entre c1 et c2 (bornes incluses)."""
    for i in range(steps):
        yield mix(c1, c2, i / (steps - 1))
