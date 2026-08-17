# campaign.py
"""Logique d'enchaînement du mode Campagne — aucune dépendance Tk/subprocess
concrète : `CampaignRunner` reçoit une fonction de lancement (`launch_fn`) qui
retourne n'importe quel objet exposant `.poll()` (comme `subprocess.Popen`),
ce qui la rend testable avec un faux process (voir tests/test_campaign.py).
"""

from typing import Callable, List, Optional


class CampaignRunner:
    """Enchaîne une liste de jeux en sous-processus, un à la fois : lance le
    suivant seulement après la fin (fermeture de fenêtre) du précédent."""

    def __init__(self, games: List[dict], launch_fn: Callable[[dict], object],
                 on_finished: Optional[Callable[[], None]] = None) -> None:
        self.games = list(games)
        self._launch_fn = launch_fn
        self.on_finished = on_finished
        self.index = -1
        self.current_process = None

    def start(self) -> None:
        self.index = -1
        self.current_process = None
        self._advance()

    def _advance(self) -> None:
        self.index += 1
        if self.index >= len(self.games):
            self.current_process = None
            if self.on_finished is not None:
                self.on_finished()
            return
        self.current_process = self._launch_fn(self.games[self.index])

    @property
    def current_game(self) -> Optional[dict]:
        if 0 <= self.index < len(self.games):
            return self.games[self.index]
        return None

    @property
    def is_running(self) -> bool:
        return self.current_process is not None

    def poll(self) -> bool:
        """À appeler périodiquement (ex: `root.after`). Avance automatiquement
        au jeu suivant quand le process courant est terminé. Retourne True
        tant qu'un jeu est en cours (campagne active), False une fois tous
        les jeux joués (ou si la campagne n'a jamais démarré)."""
        if self.current_process is None:
            return False
        if self.current_process.poll() is not None:
            self._advance()
            return self.current_process is not None
        return True
