# tests/test_campaign.py
"""Tests de CampaignRunner avec un faux process (aucun vrai sous-processus
lancé, aucun Tk)."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from campaign import CampaignRunner  # noqa: E402


class FakeProcess:
    def __init__(self):
        self._finished = False

    def finish(self):
        self._finished = True

    def poll(self):
        return 0 if self._finished else None


GAMES = [{"id": "dictee"}, {"id": "maths"}]


def _make_runner(games=GAMES, on_finished=None):
    processes = []

    def launch_fn(game):
        p = FakeProcess()
        processes.append((game, p))
        return p

    runner = CampaignRunner(games, launch_fn, on_finished=on_finished)
    return runner, processes


def test_start_launches_first_game():
    runner, processes = _make_runner()
    runner.start()
    assert runner.current_game == GAMES[0]
    assert runner.is_running
    assert len(processes) == 1


def test_poll_advances_to_next_game_once_current_finishes():
    runner, processes = _make_runner()
    runner.start()
    processes[0][1].finish()

    still_running = runner.poll()

    assert still_running
    assert runner.current_game == GAMES[1]
    assert len(processes) == 2


def test_poll_returns_true_while_current_game_still_open():
    runner, processes = _make_runner()
    runner.start()
    still_running = runner.poll()
    assert still_running
    assert runner.current_game == GAMES[0]  # inchangé : le process n'est pas fini


def test_finishing_last_game_calls_on_finished_and_stops():
    calls = []
    runner, processes = _make_runner(on_finished=lambda: calls.append(True))
    runner.start()
    processes[0][1].finish()
    runner.poll()  # avance au jeu 2 (maths)
    processes[1][1].finish()
    still_running = runner.poll()

    assert not still_running
    assert not runner.is_running
    assert calls == [True]


def test_empty_games_list_finishes_immediately():
    calls = []
    runner, _ = _make_runner(games=[], on_finished=lambda: calls.append(True))
    runner.start()
    assert not runner.is_running
    assert calls == [True]


def test_poll_before_start_returns_false():
    runner, _ = _make_runner()
    assert runner.poll() is False
